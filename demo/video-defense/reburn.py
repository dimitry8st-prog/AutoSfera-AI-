#!/usr/bin/env python3
"""Crop mascot, rewrite captions as ASS, rebuild title clips and burn bottom subtitles."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image

import build_assets as ba

ROOT = Path(__file__).resolve().parent
FFMPEG = ba.FFMPEG


def crop_mascot() -> None:
    path = ROOT / "assets" / "dis-mascot.png"
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    cropped = im.crop((int(w * 0.40), int(h * 0.02), w, h))
    cropped.save(path)


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(cues: list[dict]) -> Path:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Segoe UI,22,&H00FFFFFF,&H000000FF,&H00140B08,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,70,70,48,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        text = ba.wrap_caption(cue["text"]).replace("\n", r"\N")
        text = text.replace("{", r"\{").replace("}", r"\}")
        events.append(
            f"Dialogue: 0,{ass_time(float(cue['start']))},{ass_time(float(cue['end']))},Default,,0,0,0,,{text}"
        )
    path = ROOT / "subtitles.ass"
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def remake_clip(scene: dict) -> None:
    clips = ROOT / "clips"
    src = ba.still_for(scene)
    padded = clips / f"{scene['id']}_audio.m4a"
    out = clips / f"{scene['id']}.mp4"
    dur = float(scene["_duration"])
    subprocess.check_call(
        [
            FFMPEG, "-y",
            "-loop", "1", "-framerate", "30", "-i", str(src),
            "-i", str(padded),
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-crf", "18",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            "-c:a", "copy", "-shortest", "-t", f"{dur:.3f}",
            str(out),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    crop_mascot()
    ba.render_stills()
    data = json.loads((ba.VO / "timings.json").read_text(encoding="utf-8"))
    ba.write_srt(data["cues"])
    write_ass(data["cues"])
    scenes = {s["id"]: s for s in data["scenes"]}
    remake_clip(scenes["01_intro"])
    remake_clip(scenes["15_finale"])
    clips = ROOT / "clips"
    rows = [f"file '{s['id']}.mp4'" for s in data["scenes"]]
    (clips / "list.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    raw = clips / "raw.mp4"
    subprocess.check_call(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(clips / "list.txt"), "-c", "copy", str(raw)],
        cwd=str(clips),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    final = ROOT / "AutoSfera_AI_Defense_Stepanov_DA.mp4"
    proc = subprocess.run(
        [
            FFMPEG, "-y", "-i", str(raw), "-vf", "ass=subtitles.ass",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(final),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-1500:])
    print("ok", final, final.stat().st_size)


if __name__ == "__main__":
    main()
