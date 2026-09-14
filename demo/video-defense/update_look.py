#!/usr/bin/env python3
"""Refresh DIS mascot stills and mix quiet Four Seasons BGM under the VO."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import build_assets as ba

ROOT = Path(__file__).resolve().parent
FFMPEG = ba.FFMPEG
BGM_DIR = ROOT / "assets" / "bgm"
TRACKS = [
    BGM_DIR / "John_Harrison_with_the_Wichita_State_University_Chamber_Players_-_01_-_Spring_Mvt_1_Allegro.mp3",
    BGM_DIR / "John_Harrison_with_the_Wichita_State_University_Chamber_Players_-_06_-_Summer_Mvt_3_Presto.mp3",
    BGM_DIR / "John_Harrison_with_the_Wichita_State_University_Chamber_Players_-_07_-_Autumn_Mvt_1_Allegro.mp3",
]


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
    ba.render_stills()
    data = json.loads((ba.VO / "timings.json").read_text(encoding="utf-8"))
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
    dur = sum(float(s["_duration"]) for s in data["scenes"])
    fade_out_start = max(0.0, dur - 6.0)
    inputs: list[str] = []
    for track in TRACKS:
        inputs.extend(["-i", str(track)])
    n = len(TRACKS)
    concat = "".join(f"[{i}:a]" for i in range(1, n + 1)) + f"concat=n={n}:v=0:a=1[bed]"
    filt = (
        f"{concat};"
        f"[bed]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start:.3f}:d=6,volume=0.10[bg];"
        f"[0:a]asplit=2[vo][sc];"
        f"[bg][sc]sidechaincompress=threshold=0.03:ratio=10:attack=40:release=420:makeup=1[duck];"
        f"[vo][duck]amix=inputs=2:duration=first:dropout_transition=2[a]"
    )
    cmd = [FFMPEG, "-y", "-i", str(raw)] + inputs + [
        "-filter_complex", filt,
        "-map", "0:v", "-map", "[a]",
        "-vf", "ass=subtitles.ass",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart",
        str(ROOT / "AutoSfera_AI_Defense_Stepanov_DA.mp4"),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-2000:])
    out = ROOT / "AutoSfera_AI_Defense_Stepanov_DA.mp4"
    print("wrote", out, out.stat().st_size)


if __name__ == "__main__":
    main()
