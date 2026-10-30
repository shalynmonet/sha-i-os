"""Offline test for photos_picker.py with the Google APIs stubbed. Run: python test_photos_picker.py"""
import io
import tempfile
from pathlib import Path

import photos_picker as pp


def main():
    calls = []
    responses = {
        ("POST", "sessions"): {"id": "s1", "pickerUri": "https://photos.google.com/picker/s1",
                               "pollingConfig": {"pollInterval": "0s", "timeoutIn": "60s"}},
        ("GET", "sessions/s1"): {"mediaItemsSet": True},
        ("DELETE", "sessions/s1"): {},
    }
    pages = [
        {"mediaItems": [{"id": "v1", "type": "VIDEO", "mediaFile": {"baseUrl": "https://x/v1", "filename": "clip.mp4"}}],
         "nextPageToken": "p2"},
        {"mediaItems": [{"id": "i1", "type": "PHOTO", "mediaFile": {"baseUrl": "https://x/i1", "filename": "pic.jpg"}}]},
    ]

    def fake_api(method, path, body=None, token=None):
        calls.append((method, path.split("?")[0]))
        return pages.pop(0) if path.startswith("mediaItems") else responses[(method, path)]

    fetched = []

    def fake_urlopen(req):
        fetched.append((req.full_url, req.headers.get("Authorization")))
        return io.BytesIO(b"media-bytes")

    pp.api = fake_api
    pp.access_token = lambda: "tok"
    pp.webbrowser.open = lambda url: None
    pp.urllib.request.urlopen = fake_urlopen

    with tempfile.TemporaryDirectory() as tmp:
        pp.PICKED_DIR = Path(tmp)
        folder = pp.pick(max_items=5)
        assert sorted(p.name for p in folder.iterdir()) == ["clip.mp4", "pic.jpg"]
        assert (folder / "clip.mp4").read_bytes() == b"media-bytes"

    assert ("https://x/v1=dv", "Bearer tok") in fetched  # original video
    assert ("https://x/i1=d", "Bearer tok") in fetched   # full-res photo
    assert calls[-1] == ("DELETE", "sessions/s1")        # session cleaned up
    assert calls.count(("GET", "mediaItems")) == 2       # paginated
    print("All picker checks passed.")


if __name__ == "__main__":
    main()
