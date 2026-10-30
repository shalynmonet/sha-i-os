"""Approval queue and action log: nothing that sends, posts, or spends runs
until you approve it, and every step is written to an append-only log.

    python approvals.py list                 # pending requests
    python approvals.py list --all           # every request
    python approvals.py show 3
    python approvals.py approve 3 --note "go"
    python approvals.py reject 3 --note "wrong caption"
    python approvals.py run                  # execute everything approved
    python approvals.py log                  # the action log

In code:
    from approvals import request, executor

    @executor("post")
    def post_reel(payload): ...                 # only ever called after approval

    request("post", "Post Bali reel", {"file": "data/reels/x.mp4"}, venture="Namastays")
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Callable

import router
from inbox import DB_PATH, connect as _connect

KINDS = {"send", "post", "spend"}
EXECUTORS: dict[str, Callable[[dict], object]] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    payload TEXT NOT NULL,
    venture TEXT,
    amount REAL,
    currency TEXT,
    review TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, approved, rejected, done, failed
    requested_by TEXT NOT NULL,
    note TEXT,
    result TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    executed_at TEXT
);
CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY,
    action_id INTEGER NOT NULL REFERENCES actions(id),
    event TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS action_log_no_update BEFORE UPDATE ON action_log
BEGIN SELECT RAISE(ABORT, 'action_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS action_log_no_delete BEFORE DELETE ON action_log
BEGIN SELECT RAISE(ABORT, 'action_log is append-only'); END;
"""

REVIEW_SYSTEM = (
    "You review actions an assistant wants to take for its owner. In at most two short "
    "sentences, say plainly what will happen and anything the owner should double-check "
    "(recipient, wording, amount, privacy). No preamble."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path=DB_PATH) -> sqlite3.Connection:
    conn = _connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def log(conn: sqlite3.Connection, action_id: int, event: str, detail: str | None = None) -> None:
    conn.execute("INSERT INTO action_log (action_id, event, detail, at) VALUES (?, ?, ?, ?)",
                 (action_id, event, detail, now()))


def executor(kind: str):
    """Register the function that carries out approved actions of `kind`."""
    def register(fn):
        EXECUTORS[kind] = fn
        return fn
    return register


def review(kind: str, title: str, payload: dict, amount: float | None, currency: str | None) -> str | None:
    """Nemotron Super writes a plain-language check for the approver. Never blocks a request."""
    money = f"\nAmount: {amount} {currency or ''}" if amount is not None else ""
    try:
        return router.ask(f"Action: {kind}\nTitle: {title}{money}\nDetails: {json.dumps(payload)[:3000]}",
                          tier="super", system=REVIEW_SYSTEM)
    except Exception as e:
        return f"(review unavailable: {type(e).__name__})"


def request(kind: str, title: str, payload: dict, venture: str | None = None, amount: float | None = None,
            currency: str | None = None, requested_by: str = "sha-i", with_review: bool = True,
            conn: sqlite3.Connection | None = None) -> int:
    """Queue an action for approval and return its id. Nothing runs yet."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    conn = conn or connect()
    note = review(kind, title, payload, amount, currency) if with_review else None
    cur = conn.execute(
        "INSERT INTO actions (kind, title, payload, venture, amount, currency, review, requested_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, title, json.dumps(payload, ensure_ascii=False), venture, amount, currency, note, requested_by, now()))
    log(conn, cur.lastrowid, "requested", f"{kind} by {requested_by}: {title}")
    conn.commit()
    return cur.lastrowid


def _get(conn: sqlite3.Connection, action_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        raise LookupError(f"No action {action_id}")
    return row


def decide(action_id: int, approve: bool, note: str | None = None, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or connect()
    row = _get(conn, action_id)
    if row["status"] != "pending":
        raise ValueError(f"Action {action_id} is already {row['status']}")
    status = "approved" if approve else "rejected"
    conn.execute("UPDATE actions SET status = ?, note = ?, decided_at = ? WHERE id = ?",
                 (status, note, now(), action_id))
    log(conn, action_id, status, note)
    conn.commit()


def execute(action_id: int, conn: sqlite3.Connection | None = None) -> str:
    """Run one approved action through its executor. Refuses anything not approved."""
    conn = conn or connect()
    row = _get(conn, action_id)
    if row["status"] != "approved":
        log(conn, action_id, "blocked", f"execute refused: status is {row['status']}")
        conn.commit()
        raise PermissionError(f"Action {action_id} is {row['status']}, not approved")
    fn = EXECUTORS.get(row["kind"])
    if fn is None:
        raise LookupError(f"No executor registered for '{row['kind']}'; action {action_id} stays approved")
    log(conn, action_id, "executing")
    conn.commit()
    try:
        result = fn(json.loads(row["payload"]))
        status, detail = "done", None if result is None else str(result)[:2000]
    except Exception as e:
        status, detail = "failed", f"{type(e).__name__}: {e}"[:2000]
    conn.execute("UPDATE actions SET status = ?, result = ?, executed_at = ? WHERE id = ?",
                 (status, detail, now(), action_id))
    log(conn, action_id, status, detail)
    conn.commit()
    return status


def run_approved(conn: sqlite3.Connection | None = None) -> dict[int, str]:
    conn = conn or connect()
    results = {}
    for (action_id,) in conn.execute("SELECT id FROM actions WHERE status = 'approved' ORDER BY id").fetchall():
        try:
            results[action_id] = execute(action_id, conn)
        except LookupError as e:
            results[action_id] = f"skipped: {e}"
    return results


def _print_action(r: sqlite3.Row, full: bool = False) -> None:
    money = f" {r['amount']:g} {r['currency'] or ''}" if r["amount"] is not None else ""
    print(f"#{r['id']:<4} {r['status']:<9} {r['kind']:<6} {r['venture'] or '-':<11} {r['title']}{money}")
    if full:
        print(f"      payload: {r['payload']}")
        for key in ("review", "note", "result"):
            if r[key]:
                print(f"      {key}: {r[key]}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list"); ls.add_argument("--all", action="store_true")
    sh = sub.add_parser("show"); sh.add_argument("id", type=int)
    for name in ("approve", "reject"):
        p = sub.add_parser(name); p.add_argument("id", type=int); p.add_argument("--note")
    sub.add_parser("run")
    lg = sub.add_parser("log"); lg.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    conn = connect()

    if args.cmd == "list":
        where = "" if args.all else "WHERE status = 'pending'"
        rows = conn.execute(f"SELECT * FROM actions {where} ORDER BY id").fetchall()
        for r in rows:
            _print_action(r, full=not args.all)
        print(f"{len(rows)} action(s).")
    elif args.cmd == "show":
        _print_action(_get(conn, args.id), full=True)
    elif args.cmd in ("approve", "reject"):
        decide(args.id, args.cmd == "approve", args.note, conn)
        print(f"Action {args.id} {args.cmd}d.")
    elif args.cmd == "run":
        import actions  # noqa: F401  registers the executors
        for action_id, status in run_approved(conn).items():
            print(f"#{action_id}: {status}")
    elif args.cmd == "log":
        rows = conn.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
        for r in reversed(rows):
            print(f"{r['at']}  #{r['action_id']:<4} {r['event']:<10} {r['detail'] or ''}")
