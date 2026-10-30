"""Click-through test of app.py with Streamlit's AppTest on a temp database and inbox
(model calls stubbed). Run: python test_app.py"""
import os
import tempfile
import time
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["SHA_I_DB"] = str(tmp / "t.db")
os.environ["INBOX_DIR"] = str(tmp / "inbox")

from streamlit.testing.v1 import AppTest  # noqa: E402

import router  # noqa: E402

router.ask = lambda *a, **kw: "Posts publicly; check the caption."
router.ask_json = lambda *a, **kw: {"venture": "UGC", "tags": ["tiktok"], "summary": "Brand brief.", "confidence": 0.9}


def main():
    inbox_dir = tmp / "inbox"
    inbox_dir.mkdir()
    (inbox_dir / "brief.txt").write_text("3 TikTok videos for a serum brand", encoding="utf-8")
    old = time.time() - 10
    os.utime(inbox_dir / "brief.txt", (old, old))

    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, at.exception
    next(b for b in at.button if b.label == "Scan inbox folder").click().run()
    assert not at.exception, at.exception
    assert any("Brand brief." in m.value for m in at.markdown), "tagged item not shown"
    assert [m.value for m in at.metric if m.label == "UGC"] == ["1"]

    import approvals
    approvals.request("spend", "Boost reel", {"days": 3}, venture="UGC", amount=40, currency="USD")
    at.sidebar.radio[0].set_value("Approvals").run()
    assert not at.exception, at.exception
    assert any("Posts publicly" in i.value for i in at.info)
    next(b for b in at.button if b.label == "Approve").click().run()
    assert not at.exception, at.exception
    assert any("Nothing waiting" in s.value for s in at.success)

    at.sidebar.radio[0].set_value("Reels").run()
    assert not at.exception, at.exception
    print("All app checks passed.")


if __name__ == "__main__":
    main()
