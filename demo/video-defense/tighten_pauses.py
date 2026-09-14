#!/usr/bin/env python3
"""Cut inter-slide holds to 1/3 and rebuild the defense MP4."""
from __future__ import annotations

import json
from pathlib import Path

import build_assets as ba
import reburn
import update_look as look

ROOT = Path(__file__).resolve().parent


def tighten(data: dict) -> dict:
    t = 0.0
    new_cues: list[dict] = []
    for scene in data["scenes"]:
        hold = max(0.0, float(scene["_hold"]) / 3.0)
        scene_cues = [c for c in data["cues"] if c["scene"] == scene["id"]]
        if scene_cues:
            origin = float(scene_cues[0]["start"])
            for cue in scene_cues:
                dur = float(cue["end"]) - float(cue["start"])
                rel = float(cue["start"]) - origin
                new_cues.append(
                    {
                        "start": t + rel,
                        "end": t + rel + dur,
                        "text": cue["text"],
                        "scene": scene["id"],
                    }
                )
        scene["_hold"] = hold
        scene["_start"] = t
        scene["_duration"] = float(scene["_vo"]) + hold
        t += scene["_duration"]
    data["cues"] = new_cues
    return data


def mix_bgm(raw: Path, dur: float) -> Path:
    fade_out_start = max(0.0, dur - 6.0)
    inputs: list[str] = []
    for track in look.TRACKS:
        inputs.extend(["-i", str(track)])
    n = len(look.TRACKS)
    concat = "".join(f"[{i}:a]" for i in range(1, n + 1)) + f"concat=n={n}:v=0:a=1[bed]"
    filt = (
        f"{concat};"
        f"[bed]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start:.3f}:d=6,volume=0.10[bg];"
        f"[0:a]asplit=2[vo][sc];"
        f"[bg][sc]sidechaincompress=threshold=0.03:ratio=10:attack=40:release=420:makeup=1[duck];"
        f"[vo][duck]amix=inputs=2:duration=first:dropout_transition=2[a]"
    )
    final = ROOT / "AutoSfera_AI_Defense_Stepanov_DA.mp4"
    cmd = [ba.FFMPEG, "-y", "-i", str(raw)] + inputs + [
        "-filter_complex", filt,
        "-map", "0:v", "-map", "[a]",
        "-vf", "ass=subtitles.ass",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart",
        str(final),
    ]
    proc = __import__("subprocess").run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr[-2000:])
    return final


def main() -> None:
    path = ba.VO / "timings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data = tighten(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    ba.write_srt(data["cues"])
    reburn.write_ass(data["cues"])
    total = sum(float(s["_duration"]) for s in data["scenes"])
    print(f"new duration {total:.1f}s")
    ba.assemble_mp4(data["scenes"])
    raw = ROOT / "clips" / "raw.mp4"
    out = mix_bgm(raw, total)
    print("wrote", out, out.stat().st_size, f"{total:.1f}s")


if __name__ == "__main__":
    main()
