"""SHA-I Streamlit UI: inspiration inbox, reels, approvals.

    streamlit run app.py
"""
import json
from datetime import datetime
from pathlib import Path

import streamlit as st

import approvals
import inbox
import reel
import router

st.set_page_config(page_title="SHA-I", page_icon="✦", layout="wide")


def db():
    return approvals.connect()  # also creates the inbox table


# ---------- Sidebar ----------

with st.sidebar:
    st.title("✦ SHA-I")
    st.caption("Private creative OS")
    page = st.radio("Go to", ["Inbox", "Reels", "Approvals"], label_visibility="collapsed")
    pending = db().execute("SELECT COUNT(*) FROM actions WHERE status = 'pending'").fetchone()[0]
    if pending:
        st.warning(f"{pending} action(s) waiting for approval")
    st.divider()
    st.caption("NVIDIA Nemotron via Nebius Token Factory")
    for tier in router.TIERS:
        try:
            st.caption(f"**{tier}** · {router.model_for(tier).split('/')[-1]}")
        except RuntimeError:
            st.caption(f"**{tier}** · not set")


# ---------- Inbox ----------

def inbox_page():
    st.header("Inspiration inbox")
    st.caption(f"Drop screenshots and notes here or into `{inbox.INBOX_DIR}`. Nemotron tags each by venture.")

    with st.form("upload", clear_on_submit=True):
        files = st.file_uploader("Add screenshots or notes", accept_multiple_files=True,
                                 type=[e.lstrip(".") for e in inbox.IMAGE_EXTS | inbox.NOTE_EXTS])
        add = st.form_submit_button("Add and tag")
    b1, b2 = st.columns(2)
    from_photos = b1.button("Pick screenshots from Google Photos", type="primary")
    scan = b2.button("Scan inbox folder")

    conn = db()
    if from_photos:
        import photos_picker
        with st.spinner("Finish picking in the Google Photos tab that just opened, then Nemotron tags them..."):
            photos_picker.pick(folder=inbox.INBOX_DIR, photos_only=True, max_side=2048)
            st.toast(f"Added {inbox.run_once(conn=conn, settle=0)} item(s) from Google Photos")
    if add and files:
        inbox.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        with st.spinner("Tagging with Nemotron..."):
            for f in files:
                path = inbox.INBOX_DIR / f.name
                path.write_bytes(f.getvalue())
                row = inbox.process(path, conn)
                if row is None:
                    st.info(f"{f.name} is already in the inbox.")
                elif row["error"]:
                    st.error(f"{f.name}: {row['error']}")
        st.toast(f"Added {len(files)} item(s)")
    if scan:
        with st.spinner("Scanning..."):
            st.toast(f"Processed {inbox.run_once(conn=conn)} new item(s)")

    rows = conn.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    if not rows:
        st.info("Nothing here yet.")
        return

    counts = {v: sum(r["venture"] == v for r in rows) for v in inbox.VENTURES}
    for col, (venture, n) in zip(st.columns(len(counts)), counts.items()):
        col.metric(venture, n)

    f1, f2 = st.columns([2, 3])
    chosen = f1.multiselect("Venture", list(inbox.VENTURES), placeholder="All ventures")
    query = f2.text_input("Search", placeholder="tags, summary, text").lower()
    shown = [r for r in rows
             if (not chosen or r["venture"] in chosen)
             and (not query or query in " ".join(str(r[k] or "") for k in ("tags", "summary", "content")).lower())]
    st.caption(f"{len(shown)} of {len(rows)} items")

    for r in shown:
        with st.container(border=True):
            left, right = st.columns([1, 3])
            path = Path(r["path"])
            if r["kind"] == "screenshot" and path.exists():
                left.image(str(path), width="stretch")
            else:
                left.markdown(f"📝 **{path.name}**")
            right.markdown(f"**{r['venture'] or 'error'}** · {path.name}")
            right.write(r["summary"] or r["error"])
            if r["tags"]:
                right.caption(" ".join(f"#{t}" for t in json.loads(r["tags"])))
            ventures = list(inbox.VENTURES)
            new = right.selectbox("Venture", ventures, key=f"v{r['id']}", label_visibility="collapsed",
                                  index=ventures.index(r["venture"]) if r["venture"] in ventures else len(ventures) - 1)
            if new != r["venture"]:
                conn.execute("UPDATE items SET venture = ? WHERE id = ?", (new, r["id"]))
                conn.commit()
                st.rerun()
            with right.expander("Content"):
                st.write(r["content"])


# ---------- Reels ----------

def reels_page():
    st.header("Reels")

    with st.container(border=True):
        st.subheader("1. Pick clips")
        c1, c2 = st.columns([1, 3])
        max_items = c1.number_input("Max items", 1, 50, 10)
        if c2.button("Pick from Google Photos", type="primary"):
            import photos_picker
            with st.spinner("Finish picking in the Google Photos tab that just opened..."):
                folder = photos_picker.pick(int(max_items))
            st.success(f"Downloaded {len(reel.media_in(folder))} item(s)")

    folders = sorted((p for p in (inbox.ROOT / "data" / "picked").glob("*") if p.is_dir()),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    with st.container(border=True):
        st.subheader("2. Build a reel")
        if not folders:
            st.info("Pick some clips first.")
        else:
            label = lambda p: f"{datetime.fromtimestamp(p.stat().st_mtime):%b %d %H:%M} · {len(reel.media_in(p))} items"
            folder = st.selectbox("Picked set", folders, format_func=label)
            hook = st.text_input("What's it about? (Nemotron writes the caption)", "Namastays Bali retreat")
            caption = st.text_input("Or write the caption yourself")
            secs = st.slider("Seconds per clip", 1.0, 6.0, 3.0, 0.5)
            if st.button("Build reel", type="primary"):
                with st.spinner("Rendering..."):
                    caption = caption or reel.write_hook(hook)
                    out = reel.build(reel.media_in(folder), clip_seconds=secs, caption=caption)
                st.session_state["reel_caption"] = {out.name: caption}
                st.success(f"Saved {out.name} · caption: {caption}")

    reels = sorted(reel.REELS_DIR.glob("*.mp4"), reverse=True) if reel.REELS_DIR.exists() else []
    with st.container(border=True):
        st.subheader("3. Review and queue")
        if not reels:
            st.info("No reels yet.")
            return
        chosen = st.selectbox("Reel", reels, format_func=lambda p: p.name)
        left, right = st.columns([1, 2])
        left.video(str(chosen))
        known = st.session_state.get("reel_caption", {}).get(chosen.name, "")
        post_caption = right.text_area("Post caption", known)
        venture = right.selectbox("Venture", list(inbox.VENTURES))
        if right.button("Queue post for approval"):
            with st.spinner("Nemotron is reviewing the request..."):
                action_id = approvals.request("post", f"Post reel {chosen.name}",
                                              {"file": str(chosen), "caption": post_caption},
                                              venture=venture, requested_by="ui")
            st.success(f"Queued as #{action_id}. Approve it on the Approvals page.")


# ---------- Approvals ----------

def approvals_page():
    st.header("Approvals")
    st.caption("Nothing that sends, posts, or spends runs until you approve it here.")
    conn = db()

    pending = conn.execute("SELECT * FROM actions WHERE status = 'pending' ORDER BY id").fetchall()
    if not pending:
        st.success("Nothing waiting for you.")
    for a in pending:
        payload = json.loads(a["payload"])
        with st.container(border=True):
            money = f" · {a['amount']:g} {a['currency'] or ''}" if a["amount"] is not None else ""
            st.markdown(f"**#{a['id']} {a['title']}**  \n`{a['kind']}` · {a['venture'] or '-'}{money} · "
                        f"requested by {a['requested_by']}")
            if a["review"]:
                st.info(a["review"], icon="🛡️")
            if str(payload.get("file", "")).endswith(".mp4") and Path(payload["file"]).exists():
                st.columns([1, 2])[0].video(payload["file"])
            with st.expander("Details"):
                st.json(payload)
            note = st.text_input("Note", key=f"note{a['id']}", placeholder="optional")
            b1, b2, _ = st.columns([1, 1, 4])
            if b1.button("Approve", key=f"ok{a['id']}", type="primary"):
                approvals.decide(a["id"], True, note or None, conn)
                st.rerun()
            if b2.button("Reject", key=f"no{a['id']}"):
                approvals.decide(a["id"], False, note or None, conn)
                st.rerun()

    approved = conn.execute("SELECT COUNT(*) FROM actions WHERE status = 'approved'").fetchone()[0]
    if approved and st.button(f"Run {approved} approved action(s)", type="primary"):
        import actions  # noqa: F401  registers the executors
        for action_id, status in approvals.run_approved(conn).items():
            st.write(f"#{action_id}: {status}")

    st.subheader("History")
    history = conn.execute("SELECT id, status, kind, venture, title, amount, result, created_at FROM actions "
                           "WHERE status != 'pending' ORDER BY id DESC").fetchall()
    st.dataframe([dict(r) for r in history], hide_index=True, width="stretch")

    st.subheader("Action log")
    log = conn.execute("SELECT at, action_id, event, detail FROM action_log ORDER BY id DESC LIMIT 200").fetchall()
    st.dataframe([dict(r) for r in log], hide_index=True, width="stretch")


{"Inbox": inbox_page, "Reels": reels_page, "Approvals": approvals_page}[page]()
