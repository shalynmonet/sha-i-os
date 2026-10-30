"""Turn picked clips and photos into a short vertical reel with MoviePy.

    python reel.py data/picked/<session>                 # every clip/photo in a folder
    python reel.py a.mp4 b.mov c.jpg --clip-seconds 2.5  # specific files
    python reel.py <folder> --hook "Bali retreat launch" # Nemotron writes the caption
    python reel.py <folder> --caption "Uluwatu, but slower" --music song.mp3
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from moviepy import (AudioFileClip, ColorClip, CompositeAudioClip, CompositeVideoClip, ImageClip,
                     TextClip, VideoFileClip, concatenate_videoclips)

import router

ROOT = Path(__file__).parent
REELS_DIR = ROOT / "data" / "reels"
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
SIZE = (1080, 1920)  # vertical 9:16
FONT_CANDIDATES = [Path("C:/Windows/Fonts/arialbd.ttf"), Path("C:/Windows/Fonts/arial.ttf")]


def media_in(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in VIDEO_EXTS | PHOTO_EXTS)


def fill_frame(clip, size=SIZE):
    """Scale to cover the frame, then center-crop, so nothing is letterboxed."""
    w, h = size
    scaled = clip.resized(max(w / clip.w, h / clip.h))
    return scaled.cropped(x_center=scaled.w / 2, y_center=scaled.h / 2, width=w, height=h)


def to_segment(path: Path, seconds: float):
    if path.suffix.lower() in VIDEO_EXTS:
        clip = VideoFileClip(str(path))
        if clip.duration > seconds:  # take the middle, usually the best part
            start = (clip.duration - seconds) / 2
            clip = clip.subclipped(start, start + seconds)
    else:
        clip = ImageClip(str(path)).with_duration(seconds)
    return fill_frame(clip)


def write_hook(topic: str) -> str:
    text = router.ask(
        f"Write one on-screen hook caption for a short vertical reel about: {topic}. "
        "Max 8 words, no hashtags, no quotes, no emoji.",
        tier="nano",
    )
    return text.splitlines()[0].strip().strip('"')


def caption_layer(text: str, duration: float):
    font = next((str(f) for f in FONT_CANDIDATES if f.exists()), None)
    txt = TextClip(font=font, text=text, font_size=78, color="white", stroke_color="black",
                   stroke_width=4, method="caption", size=(SIZE[0] - 160, None), text_align="center",
                   margin=(10, 30))  # without bottom margin MoviePy clips descenders (g, y, p)
    return txt.with_duration(duration).with_position(("center", int(SIZE[1] * 0.12)))


def build(paths: list[Path], out: Path | None = None, clip_seconds: float = 3.0, max_seconds: float = 30.0,
          caption: str | None = None, hook: str | None = None, music: Path | None = None, fps: int = 30) -> Path:
    if not paths:
        raise ValueError("No clips or photos to build a reel from.")
    paths = paths[: max(1, int(max_seconds // clip_seconds))]
    segments = [to_segment(Path(p), clip_seconds) for p in paths]
    video = concatenate_videoclips(segments, method="compose")
    layers = [ColorClip(SIZE, color=(0, 0, 0)).with_duration(video.duration), video]

    if hook and not caption:
        caption = write_hook(hook)
        print(f"Caption from Nemotron: {caption}")
    if caption:
        layers.append(caption_layer(caption, video.duration))
    final = CompositeVideoClip(layers, size=SIZE).with_duration(video.duration)

    if music:
        track = AudioFileClip(str(music))
        track = track.subclipped(0, min(video.duration, track.duration))
        final = final.with_audio(CompositeAudioClip([track.with_volume_scaled(0.6)] +
                                                    ([video.audio] if video.audio else [])))

    REELS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(out or REELS_DIR / f"reel_{datetime.now():%Y%m%d_%H%M%S}.mp4")
    final.write_videofile(str(out), fps=fps, codec="libx264", audio_codec="aac", logger=None)
    for clip in [final, video, *segments]:
        clip.close()
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="+", type=Path, help="a folder, or clip/photo files")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--clip-seconds", type=float, default=3.0)
    parser.add_argument("--max-seconds", type=float, default=30.0)
    parser.add_argument("--caption", help="exact on-screen caption")
    parser.add_argument("--hook", help="topic; Nemotron Nano writes the caption")
    parser.add_argument("--music", type=Path, help="background audio file")
    parser.add_argument("--queue-post", metavar="VENTURE", help="queue a post of this reel for approval")
    args = parser.parse_args()
    files = media_in(args.inputs[0]) if len(args.inputs) == 1 and args.inputs[0].is_dir() else args.inputs
    if args.hook and not args.caption:  # write it here so the queued post gets the same caption
        args.caption = write_hook(args.hook)
        print(f"Caption from Nemotron: {args.caption}")
    out = build(files, args.out, args.clip_seconds, args.max_seconds, args.caption, music=args.music)
    print(f"Reel saved to {out}")
    if args.queue_post:
        import approvals
        action_id = approvals.request("post", f"Post reel {out.name}", {"file": str(out), "caption": args.caption or ""},
                                      venture=args.queue_post, requested_by="reel.py")
        print(f"Queued for approval as #{action_id}: python approvals.py show {action_id}")
