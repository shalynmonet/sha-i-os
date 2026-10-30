"""Offline test for photos_picker.py with the Google APIs stubbed. Run: python test_photos_picker.py"""
import io
import tempfile
from pathlib import Path

import photos_picker as pp

ITEMS = [
    {"id": "v1", "type": "VIDEO", "mediaFile": {"baseUrl": "https://x/v1", "filename": "clip.mp4"}},
    {"id": "i1", "type": "PHOTO", "mediaFile": {"baseUrl": "https://x/i1", "filename": "IMG_1.HEIC"}},
]


class FakeResponse(io.BytesIO):
    headers = {"Content-Type": "image/jpeg"}


def run(calls, fetched, **pick_kwargs):
    pages = [{"mediaItems": ITEMS[:1], "nextPageToken": "p2"}, {"mediaItems": ITEMS[1:]}]
    responses = {
        ("POST", "sessions"): {"id": "s1", "pickerUri": "https://photos.google.com/picker/s1",
                               "pollingConfig": {"pollInterval": "0s", "timeoutIn": "60s"}},
        ("GET", "sessions/s1"): {"mediaItemsSet": True},
        ("DELETE", "sessions/s1"): {},
    }

    def fake_api(method, path, body=None, token=None):
        calls.append((method, path.split("?")[0]))
        return pages.pop(0) if path.startswith("mediaItems") else responses[(method, path)]

    def fake_urlopen(req):
        fetched.append((req.full_url, req.headers.get("Authorization")))
        return FakeResponse(b"media-bytes")

    pp.api = fake_api
    pp.urllib.request.urlopen = fake_urlopen
    return pp.pick(**pick_kwargs)


def main():
    pp.access_token = lambda: "tok"
    pp.webbrowser.open = lambda url: None

    with tempfile.TemporaryDirectory() as tmp:
        # Reels: originals of everything, into data/picked/<session>
        calls, fetched = [], []
        pp.PICKED_DIR = Path(tmp)
        folder = run(calls, fetched, max_items=5)
        assert sorted(p.name for p in folder.iterdir()) == ["IMG_1.HEIC", "clip.mp4"]
        assert (folder / "clip.mp4").read_bytes() == b"media-bytes"
        assert ("https://x/v1=dv", "Bearer tok") in fetched  # original video
        assert ("https://x/i1=d", "Bearer tok") in fetched   # full-res photo
        assert calls[-1] == ("DELETE", "sessions/s1")        # session cleaned up
        assert calls.count(("GET", "mediaItems")) == 2       # paginated

        # Inbox: photos only, resized to a readable format, into the given folder
        calls, fetched = [], []
        inbox_dir = Path(tmp) / "inbox"
        run(calls, fetched, folder=inbox_dir, photos_only=True, max_side=2048)
        assert [p.name for p in inbox_dir.iterdir()] == ["IMG_1.jpg"]  # HEIC came back as JPEG
        assert fetched == [("https://x/i1=w2048-h2048", "Bearer tok")]  # video never downloaded

        run([], [], folder=inbox_dir, photos_only=True, max_side=2048)  # same filename again
        assert sorted(p.name for p in inbox_dir.iterdir()) == ["IMG_1.jpg", "IMG_1_i1.jpg"]
    print("All picker checks passed.")


if __name__ == "__main__":
    main()
