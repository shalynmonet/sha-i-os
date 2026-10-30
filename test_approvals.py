"""Test approvals.py on a temp database (review stubbed). Run: python test_approvals.py"""
import sqlite3
import tempfile
from pathlib import Path

import approvals


def main():
    approvals.router.ask = lambda *a, **kw: "Posts the reel publicly; check the caption."
    ran = []
    approvals.executor("post")(lambda payload: ran.append(payload) or "posted")
    approvals.executor("spend")(lambda payload: 1 / 0)

    with tempfile.TemporaryDirectory() as tmp:
        conn = approvals.connect(Path(tmp) / "t.db")
        post = approvals.request("post", "Post reel", {"file": "r.mp4"}, venture="Namastays", conn=conn)
        spend = approvals.request("spend", "Buy ads", {"to": "meta"}, amount=50, currency="USD", conn=conn)
        nope = approvals.request("send", "Email brand", {"to": "x@y.z"}, conn=conn)

        assert conn.execute("SELECT review FROM actions WHERE id=?", (post,)).fetchone()[0].startswith("Posts")
        try:  # nothing runs before approval
            approvals.execute(post, conn)
            raise AssertionError("ran without approval")
        except PermissionError:
            pass
        assert ran == []

        approvals.decide(post, True, "looks good", conn)
        approvals.decide(spend, True, conn=conn)
        approvals.decide(nope, False, "not now", conn)
        try:
            approvals.decide(nope, True, conn=conn)  # decisions are final
            raise AssertionError("re-decided")
        except ValueError:
            pass

        assert approvals.run_approved(conn) == {post: "done", spend: "failed"}
        assert ran == [{"file": "r.mp4"}]
        assert approvals.run_approved(conn) == {}  # done actions never run twice

        events = [r[0] for r in conn.execute("SELECT event FROM action_log WHERE action_id=? ORDER BY id", (post,))]
        assert events == ["requested", "blocked", "approved", "executing", "done"], events
        try:
            conn.execute("DELETE FROM action_log")
            raise AssertionError("log was deletable")
        except sqlite3.DatabaseError:
            pass
        conn.close()
    print("All approval checks passed.")


if __name__ == "__main__":
    main()
