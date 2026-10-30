"""Live smoke test for router.py: one call per tier. Run: python test_router.py"""
import tempfile
from pathlib import Path

import router


def make_test_image() -> Path:
    from PIL import Image, ImageDraw  # installed with moviepy

    img = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(img).text((20, 50), "Namastays retreat in Bali", fill="black")
    path = Path(tempfile.gettempdir()) / "sha_i_router_test.png"
    img.save(path)
    return path


def main():
    for tier in router.TIERS:
        print(f"{tier:7} -> {router.model_for(tier)}")

    reply = router.ask("Reply with exactly: pong", tier="nano")
    print("nano   :", reply)
    assert "pong" in reply.lower()

    data = router.ask_json('Return only JSON: {"ok": true, "n": 3}', tier="super")
    print("super  :", data)
    assert data.get("ok") is True

    seen = router.see(make_test_image(), "What text is in this image? Reply with the text only.")
    print("vision :", seen)
    assert "bali" in seen.lower()

    print("All router checks passed.")


if __name__ == "__main__":
    main()
