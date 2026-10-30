"""Test reel.py on generated clips (live Nemotron call for the hook). Run: python test_reel.py"""
import tempfile
from pathlib import Path

from moviepy import ColorClip, VideoFileClip
from PIL import Image

import reel


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ColorClip((1920, 1080), color=(200, 80, 40)).with_duration(5).write_videofile(
            str(tmp / "a_landscape.mp4"), fps=24, logger=None)
        ColorClip((720, 1280), color=(40, 120, 200)).with_duration(1.5).write_videofile(
            str(tmp / "b_short.mp4"), fps=24, logger=None)
        Image.new("RGB", (1200, 1200), (30, 160, 90)).save(tmp / "c_photo.jpg")

        out = reel.build(reel.media_in(tmp), out=tmp / "reel.mp4", clip_seconds=2, hook="a Bali yoga retreat")
        result = VideoFileClip(str(out))
        print(f"reel: {result.size} {result.duration:.2f}s")
        assert tuple(result.size) == reel.SIZE
        assert abs(result.duration - 5.5) < 0.2  # 2 + 1.5 (shorter than clip) + 2
        result.close()
    print("All reel checks passed.")


if __name__ == "__main__":
    main()
