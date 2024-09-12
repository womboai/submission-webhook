import time
import traceback
from enum import Enum
from typing import cast, Any
from tqdm import tqdm

import bittensor as bt
from bittensor.extrinsics.serving import get_metadata
from pydantic import BaseModel

from network_commitments import Decoder, Encoder

SPEC_VERSION = 4


class ContestId(Enum):
    SDXL_APPLE_SILICON = 0
    SDXL_NEWDREAM_NVIDIA_4090 = 1
    FLUX_NVIDIA_4090 = 2


class CheckpointSubmission(BaseModel):
    repository: str
    revision: str
    contest: ContestId

    def encode(self, encoder: Encoder):
        encoder.write_str(self.repository)
        encoder.write_str(self.revision)
        encoder.write_uint16(self.contest.value)

    @classmethod
    def decode(cls, decoder: Decoder):
        repository = decoder.read_str()
        revision = decoder.read_str()
        contest_id = ContestId(decoder.read_uint16())

        return cls(
            repository=repository,
            revision=revision,
            contest=contest_id,
        )

    def to_json(self, uid: int):
        return {
            "uid": uid,
            "repository": self.repository,
            "revision": self.revision,
            "contest": self.contest.name
        }

    @staticmethod
    def from_json(data) -> tuple[int, "CheckpointSubmission"]:
        return (data["uid"], CheckpointSubmission(
            repository=data["repository"],
            revision=data["revision"],
            contest=ContestId[data["contest"]]
        ))


def get_miner_submissions(subtensor: bt.subtensor, metagraph: bt.metagraph, current_block: int) -> list[tuple[CheckpointSubmission, int] | None]:
    visited_repositories: dict[str, tuple[int, int]] = {}

    miner_info: list[tuple[CheckpointSubmission, int] | None] = []

    for uid in tqdm(range(metagraph.n.item())):
        hotkey = metagraph.hotkeys[uid]
        error: Exception | None = None

        for attempt in range(3):
            try:
                if attempt:
                    bt.logging.warning(f"Failed to get submission, attempt #{attempt + 1}")
                else:
                    bt.logging.info(f"Getting submission for hotkey {hotkey}")

                submission = get_submission(
                    subtensor,
                    metagraph,
                    hotkey,
                    current_block,
                )

                break
            except Exception as e:
                error = e
                time.sleep(0.1)
                continue
        else:
            raise error

        if not submission:
            miner_info.append(None)
            continue

        info, block = submission

        existing_submission = visited_repositories.get(info.repository)

        if existing_submission:
            existing_uid, existing_block = existing_submission

            if block > existing_block:
                miner_info.append(None)
                continue

            miner_info[existing_uid] = None

        miner_info.append((info, block))
        visited_repositories[info.repository] = uid, block

        time.sleep(0.2)

    return miner_info


def get_submission(
        subtensor: bt.subtensor,
        metagraph: bt.metagraph,
        hotkey: str,
        block: int | None = None
) -> tuple[CheckpointSubmission, int] | None:
    try:
        metadata = cast(dict[str, Any], get_metadata(subtensor, metagraph.netuid, hotkey, block))

        if not metadata:
            return None

        block: int = metadata["block"]
        commitment: dict[str, str] = metadata["info"]["fields"][0]
        hex_data = commitment.values().__iter__().__next__()
        data = bytes.fromhex(hex_data[2:])
        decoder = Decoder(data)

        spec_version = decoder.read_uint16()

        if spec_version != SPEC_VERSION:
            return None

        info = CheckpointSubmission.decode(decoder)

        return info, block
    except Exception as e:
        bt.logging.error(f"Failed to get submission from miner {hotkey}, {e}")
        bt.logging.debug(f"Submission parsing error, {traceback.format_exception(e)}")
        return None
