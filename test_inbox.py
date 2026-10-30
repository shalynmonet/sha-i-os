"""Offline test for inbox.py (model calls stubbed). Run: python test_inbox.py"""
import json
import os
import tempfile
import time
from pathlib import Path

import inbox


def main():
    calls = []
    inbox.router.see = lambda path, prompt, **kw: calls.append("see") or "Screenshot: Bali villa retreat"
    inbox.router.ask_json = lambda prompt, **kw: calls.append("nano") or {
        "venture": "namastays", "tags": ["Bali", "villa"], "summary": "A Bali villa.", "confidence": 1.4}

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "inbox"
        folder.mkdir()
        (folder / "idea.md").write_text("Retreat idea for Bali", encoding="utf-8")
        (folder / "shot.png").write_bytes(b"\x89PNG fake")
        (folder / "dupe.md").write_text("Retreat idea for Bali", encoding="utf-8")  # same content, skipped
        (folder / "ignore.pdf").write_bytes(b"%PDF")
        old = time.time() - 10
        for p in folder.iterdir():
            os.utime(p, (old, old))

        conn = inbox.connect(Path(tmp) / "test.db")
        assert inbox.run_once(folder, conn) == 2
        assert inbox.run_once(folder, conn) == 0  # nothing reprocessed

        rows = conn.execute("SELECT * FROM items ORDER BY path").fetchall()
        assert [r["kind"] for r in rows] == ["note", "screenshot"]
        assert all(r["venture"] == "Namastays" for r in rows)  # case normalised
        assert json.loads(rows[0]["tags"]) == ["bali", "villa"]
        assert rows[0]["confidence"] == 1.0  # clamped
        assert calls.count("see") == 1
        conn.close()
    print("All inbox checks passed.")


if __name__ == "__main__":
    main()
