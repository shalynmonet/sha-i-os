"""Executors for approved actions. Each one runs only after approval (see approvals.py).

No real posting, sending or payment integration is wired up yet. "post" exports the
approved file and caption to data/outbox/ so you can upload it by hand; "send" and
"spend" have no executor, so approved ones wait until an integration is added here.
"""
import shutil
from pathlib import Path

from approvals import executor

OUTBOX = Path(__file__).parent / "data" / "outbox"


@executor("post")
def export_post(payload: dict) -> str:
    folder = OUTBOX / Path(payload["file"]).stem
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(payload["file"], folder)
    (folder / "caption.txt").write_text(payload.get("caption", ""), encoding="utf-8")
    return f"ready to upload in {folder}"
