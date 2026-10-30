"""Inspiration inbox: watch a folder of screenshots and notes, tag each item by
venture with Nemotron Nano, and store it in SQLite.

    python inbox.py            # watch data/inbox and process new files
    python inbox.py --once     # process what's there now, then exit
    python inbox.py --list     # show the latest stored items
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import router

ROOT = Path(__file__).parent
INBOX_DIR = Path(os.getenv("INBOX_DIR", ROOT / "data" / "inbox"))
DB_PATH = Path(os.getenv("SHA_I_DB", ROOT / "data" / "sha_i.db"))

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
NOTE_EXTS = {".txt", ".md"}
SETTLE_SECONDS = 2  # skip files still being written

# Short descriptions help Nano tell the ventures apart; edit them freely.
VENTURES = {
    "SHA-I": "private creative AI operating system, personal AI tooling, agents",
    "Namastays": "travel and stays brand: retreats, properties, destinations, hospitality",
    "UGC": "user-generated content work: brand deals, product videos, creator content",
    "hackathons": "hackathon entries, deadlines, prizes, demos, pitches",
    "other": "anything that fits none of the above",
}

TAG_SYSTEM = (
    "You sort inspiration items into ventures. Ventures:\n"
    + "\n".join(f"- {name}: {desc}" for name, desc in VENTURES.items())
    + '\nReply with only JSON: {"venture": <one venture name exactly as listed>, '
    '"tags": [up to 5 short lowercase keywords], "summary": <one sentence>, '
    '"confidence": <0 to 1>}'
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    sha256 TEXT UNIQUE NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT,
    venture TEXT,
    tags TEXT,
    summary TEXT,
    confidence REAL,
    error TEXT,
    added_at TEXT NOT NULL
)
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(path: Path) -> tuple[str, str]:
    """Return (kind, text content) for a screenshot or note."""
    if path.suffix.lower() in IMAGE_EXTS:
        text = router.see(path, "Describe this screenshot for an inspiration board: "
                                "transcribe any visible text, then say what it shows. Be brief.")
        return "screenshot", text
    return "note", path.read_text(encoding="utf-8", errors="replace")


def tag(content: str) -> dict:
    result = router.ask_json(f"Item:\n{content[:4000]}", tier="nano", system=TAG_SYSTEM)
    venture = next((v for v in VENTURES if v.lower() == str(result.get("venture", "")).lower()), "other")
    tags = [str(t).lower() for t in result.get("tags", [])][:5]
    try:
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"venture": venture, "tags": tags, "summary": str(result.get("summary", "")), "confidence": confidence}


def pending_files(inbox: Path) -> list[Path]:
    now = time.time()
    return sorted(
        p for p in inbox.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS | NOTE_EXTS
        and now - p.stat().st_mtime >= SETTLE_SECONDS
    )


def process(path: Path, conn: sqlite3.Connection) -> dict | None:
    """Tag and store one file. Returns the stored row, or None if already seen."""
    digest = file_hash(path)
    if conn.execute("SELECT 1 FROM items WHERE sha256 = ?", (digest,)).fetchone():
        return None
    row = {"sha256": digest, "path": str(path), "kind": None, "content": None, "venture": None,
           "tags": None, "summary": None, "confidence": None, "error": None,
           "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        row["kind"], row["content"] = extract(path)
        result = tag(row["content"])
        row.update(result, tags=json.dumps(result["tags"]))
    except Exception as e:  # keep the item so it isn't retried forever; the error is stored
        row["kind"] = row["kind"] or "unknown"
        row["error"] = f"{type(e).__name__}: {e}"[:500]
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO items ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    conn.commit()
    return row


def run_once(inbox: Path = INBOX_DIR, conn: sqlite3.Connection | None = None) -> int:
    inbox.mkdir(parents=True, exist_ok=True)
    conn = conn or connect()
    count = 0
    for path in pending_files(inbox):
        row = process(path, conn)
        if row:
            count += 1
            label = row["error"] or f"{row['venture']} {json.loads(row['tags'])} {row['summary']}"
            print(f"[{row['kind']}] {path.name}: {label}")
    return count


def watch(inbox: Path = INBOX_DIR, interval: float = 5) -> None:
    conn = connect()
    print(f"Watching {inbox} (Ctrl+C to stop)")
    try:
        while True:
            run_once(inbox, conn)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped.")


def show(limit: int = 20) -> None:
    for r in connect().execute("SELECT * FROM items ORDER BY id DESC LIMIT ?", (limit,)):
        name = Path(r["path"]).name
        print(f"{r['id']:>4} {r['venture'] or 'ERROR':<11} {name:<30} {r['summary'] or r['error']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="process current files and exit")
    parser.add_argument("--list", action="store_true", help="show latest stored items")
    parser.add_argument("--interval", type=float, default=5, help="seconds between scans")
    args = parser.parse_args()
    if args.list:
        show()
    elif args.once:
        print(f"Processed {run_once()} new item(s).")
    else:
        watch(interval=args.interval)
