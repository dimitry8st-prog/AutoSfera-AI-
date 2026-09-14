#!/usr/bin/env python3
"""Pad live screenshots, render missing chat frames, rebuild SRT, assemble MP4."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import build_assets as ba

ROOT = Path(__file__).resolve().parent
CAPTURES = ROOT / "captures"
SHOTS = Path(r"c:\Users\user\AppData\Local\Temp\cursor\screenshots")
W, H = 1920, 1080
BG = (11, 28, 36)
INK = (243, 246, 244)
MUTED = (167, 183, 177)
GOLD = (226, 177, 90)
PANEL = (16, 40, 50)
USER = (48, 42, 28)
BOT = (28, 44, 52)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / name), size)


def fit_shot(src: Path, dest: Path) -> None:
    im = Image.open(src).convert("RGB")
    im.thumbnail((W, H), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    canvas.save(dest, quality=95)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=fnt) <= width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines[:18]


def render_chat(dest: Path, question: str, reply: str, meta: str, badge: str) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title, body, small = font(36, True), font(26), font(20)
    d.rounded_rectangle((60, 40, 1860, 1040), 28, fill=PANEL)
    d.text((100, 70), "AutoSfera AI", font=title, fill=INK)
    d.text((420, 82), "Единый интеллект автодилера", font=small, fill=MUTED)
    d.rounded_rectangle((1480, 70, 1820, 128), 14, outline=GOLD)
    d.text((1500, 84), badge, font=small, fill=GOLD)
    d.text((100, 150), "Живой ответ API  ·  без изменения бизнес-логики", font=small, fill=MUTED)

    d.rounded_rectangle((720, 210, 1780, 330), 18, fill=USER, outline=GOLD)
    q_lines = wrap(d, question, body, 980)
    for i, line in enumerate(q_lines[:3]):
        d.text((750, 230 + i * 34), line, font=body, fill=INK)

    d.rounded_rectangle((100, 360, 1500, 960), 18, fill=BOT)
    d.text((130, 380), meta, font=small, fill=GOLD)
    r_lines = wrap(d, reply, body, 1280)
    for i, line in enumerate(r_lines):
        d.text((130, 430 + i * 34), line, font=body, fill=INK)
    img.save(dest, quality=95)


def main() -> None:
    CAPTURES.mkdir(exist_ok=True)
    mapping = {
        "s1.png": "defense-s1.png",
        "s2.png": "defense-s2b.png",
        "s3.png": "defense-s3-warranty.png",
        "s4.png": "defense-s4-testdrive.png",
    }
    for dest_name, src_name in mapping.items():
        src = SHOTS / src_name
        if src.exists():
            fit_shot(src, CAPTURES / dest_name)
            print("shot", dest_name, src.stat().st_size)

    replies = {row["id"]: row for row in json.loads((CAPTURES / "live_replies.json").read_text(encoding="utf-8"))}
    for sid, dest_name in (("s5", "s5.png"), ("s6", "s6.png")):
        row = replies[sid]
        meta = f"{row['agent_label']} · {row['skill']}"
        if row.get("escalated"):
            meta += " · эскалация"
        render_chat(CAPTURES / dest_name, row["message"], row["reply"], meta, row["agent_label"])
        print("rendered", dest_name)

    data = json.loads((ba.VO / "timings.json").read_text(encoding="utf-8"))
    ba.write_srt(data["cues"], data["scenes"])
    ba.render_stills()
    print("srt+stills refreshed")
    out = ba.assemble_mp4(data["scenes"])
    print("wrote", out, out.stat().st_size)


if __name__ == "__main__":
    main()
