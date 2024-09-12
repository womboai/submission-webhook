import json
import os
from time import sleep

import bittensor as bt
import requests

from submissions import CheckpointSubmission, get_miner_submissions

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
SAVE_FILE_PATH = "submissions.json"

subtensor = bt.subtensor()
metagraph = bt.metagraph(netuid=39)


def send_webhook(block: int, uid: int, hotkey: str, submission: CheckpointSubmission):
    embed = {
        "title": f"New Miner Submission",
        "color": 0x9F2B68,
        "fields": [
            {
                "name": f"Contest: {submission.contest.name}",
                "value":
                    f"- **Repository**: {submission.repository}\n"
                    f"- **Revision**: [{submission.revision}]({f'{submission.repository}/commit/{submission.revision}'})\n"
                    f"- **Block**: `{block}`\n"
                    f"- **UID**: `{uid}`\n"
                    f"- **Hotkey**: `{hotkey}`"
            }
        ]
    }

    data = {
        "username": "Miner Submission notifs",
        "embeds": [embed],
    }

    response = requests.post(DISCORD_WEBHOOK_URL, json=data)
    response.raise_for_status()


def load_submissions() -> list[CheckpointSubmission | None]:
    if not os.path.exists(SAVE_FILE_PATH):
        return []

    submissions: list[CheckpointSubmission | None] = [None] * metagraph.n.item()

    try:
        with open(SAVE_FILE_PATH, "r") as f:
            data = json.load(f)
            for entry in data:
                uid, submission = CheckpointSubmission.from_json(entry)
                submissions[uid] = submission
    except Exception as e:
        print(f"Error loading submissions: {e}")
        os.remove(SAVE_FILE_PATH)
    return submissions


def save_submissions(submissions: list[tuple[CheckpointSubmission, int] | None]):
    with open(SAVE_FILE_PATH, "w") as f:
        data: list[CheckpointSubmission | None] = []
        for uid, submission in enumerate(submissions):
            if submission:
                data.append(submission[0].to_json(uid))
        json.dump(data, f, indent=4)


def main():
    current_block = subtensor.get_current_block()
    previous_submissions = load_submissions()

    print(f"Loading {len([sub for sub in previous_submissions if sub])} previous submissions")

    new_submissions: list[tuple[CheckpointSubmission, int] | None] = get_miner_submissions(subtensor, metagraph, current_block)

    changed_submissions = []

    for new, old in zip(new_submissions, previous_submissions):
        if new and old and new[0] != old:
            changed_submissions.append(new)
        elif new and not old:
            changed_submissions.append(new)
        else:
            changed_submissions.append(None)

    if previous_submissions:
        for uid, submission in enumerate(new_submissions):
            if submission and submission in changed_submissions:
                hotkey = metagraph.hotkeys[uid]
                send_webhook(submission[1], uid, hotkey, submission[0])
                sleep(1)  # avoid rate limiting

    print(
        f"Found {len([sub for sub in new_submissions if sub])} submissions\n"
        f"Sending {len([sub for sub in changed_submissions if sub])} webhooks."
    )

    save_submissions(new_submissions)


if __name__ == '__main__':
    main()
