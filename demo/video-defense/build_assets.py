#!/usr/bin/env python3
"""Generate VO, stills, SRT and optional MP4 for the AutoSfera AI defense video."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
VO = ROOT / "vo"
STILLS = ROOT / "stills"
CAPTURES = ROOT / "captures"
NAVY = (11, 27, 58)
ULTRA = (30, 79, 216)
ORANGE = (240, 122, 26)
WHITE = (244, 247, 255)
MUTED = (176, 190, 220)
CARD = (18, 38, 78)
W, H = 1920, 1080

FFMPEG = shutil.which("ffmpeg") or str(
    Path.home()
    / "AppData/Local/Microsoft/WinGet/Packages/"
    / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    / "ffmpeg-9.0.1-full_build/bin/ffmpeg.exe"
)
FFPROBE = str(Path(FFMPEG).with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe"))

SCENES: list[dict] = [
    {
        "id": "01_intro",
        "min_sec": 25,
        "still": "01_title.png",
        "lines": [
            "Здравствуйте. Меня зовут Дмитрий Степанов.",
            "Представляю итоговый проект AutoSfera AI — интеллектуального ассистента для автоматизации продаж, поддержки, сервисного обслуживания и внутренних процессов автодилера.",
        ],
    },
    {
        "id": "02_problem",
        "min_sec": 40,
        "still": "02_problem.png",
        "lines": [
            "Клиенты автосалона задают много повторяющихся вопросов: про автомобили, документы, гарантию, статус заказа и запись на сервис.",
            "Сотрудникам приходится искать информацию в разных источниках. Это увеличивает время ответа и создаёт риск ошибок.",
            "AutoSfera AI принимает обращение, определяет его тему, находит подтверждённую информацию и подключает нужного специалиста.",
        ],
    },
    {
        "id": "03_solution",
        "min_sec": 40,
        "still": "03_solution.png",
        "lines": [
            "Ассистент предназначен для клиентов и сотрудников автосалона.",
            "Он помогает подобрать автомобиль, объясняет условия покупки, сообщает требования к документам, консультирует по гарантии и сервису, а также формирует обращение менеджеру.",
            "Важные решения всегда подтверждает сотрудник.",
        ],
    },
    {
        "id": "04_architecture",
        "min_sec": 50,
        "still": "04_architecture.png",
        "lines": [
            "Система построена на FastAPI и LangGraph.",
            "Главный оркестратор анализирует запрос и выбирает одного из четырёх специализированных агентов.",
            "Фактическая информация извлекается из базы знаний через RAG.",
            "Простые вопросы может обрабатывать экономичная модель, а сложные и составные запросы — более мощная.",
            "Если требуется действие во внешней системе, оно сначала формируется, затем подтверждается человеком и только после этого выполняется через Action Gateway и n8n.",
        ],
    },
    {
        "id": "05_kb",
        "min_sec": 30,
        "still": "05_kb.png",
        "lines": [
            "База знаний содержит пятьдесят один логический документ. Материалы разделены по темам и уровням доступа.",
            "Ассистент должен отвечать только на основании разрешённого контекста.",
            "Если подтверждённых сведений нет, он не выдумывает ответ, а задаёт уточняющий вопрос или передаёт обращение сотруднику.",
        ],
    },
    {
        "id": "06_demo_s1",
        "min_sec": 20,
        "still": "06_demo_s1.png",
        "capture": "s1.png",
        "lines": [
            "Первый запрос относится к продажам.",
            "Оркестратор подключает агента продаж, который использует сведения каталога и уточняет необходимые характеристики.",
        ],
    },
    {
        "id": "07_demo_s2",
        "min_sec": 20,
        "still": "07_demo_s2.png",
        "capture": "s2.png",
        "lines": [
            "Пользователь меняет тему.",
            "Система заново классифицирует запрос и выдаёт ответ по документам, не оставаясь ошибочно в предыдущем сценарии.",
        ],
    },
    {
        "id": "08_demo_s3",
        "min_sec": 20,
        "still": "08_demo_s3.png",
        "capture": "s3.png",
        "lines": [
            "Вопрос по гарантии передаётся сервисному агенту.",
            "Ответ формируется на основании соответствующего раздела базы знаний.",
        ],
    },
    {
        "id": "09_demo_s4",
        "min_sec": 30,
        "still": "09_demo_s4.png",
        "capture": "s4.png",
        "lines": [
            "Для записи ассистент последовательно собирает только необходимые сведения.",
            "Внешнее действие не выполняется без проверки и подтверждения.",
        ],
    },
    {
        "id": "10_demo_s5",
        "min_sec": 20,
        "still": "10_demo_s5.png",
        "capture": "s5.png",
        "lines": [
            "Финансовые и юридически значимые решения ассистент самостоятельно не принимает.",
            "Такой запрос передаётся ответственному менеджеру.",
        ],
    },
    {
        "id": "11_demo_s6",
        "min_sec": 20,
        "still": "11_demo_s6.png",
        "capture": "s6.png",
        "lines": [
            "На вопрос вне области проекта ассистент отвечает корректно и предлагает помощь по услугам автосалона.",
        ],
    },
    {
        "id": "12_results",
        "min_sec": 35,
        "still": "12_results.png",
        "lines": [
            "В проекте работают четыре специализированных агента, семнадцать навыков и база знаний из пятидесяти одного логического документа.",
            "Локально успешно пройдено сто пятьдесят тестов, два теста пропущены из-за внешней инфраструктуры.",
            "Приёмочные сценарии оркестратора — тринадцать из тринадцати.",
            "Проверка RAG завершена с решением GO. Время ответа MVP меньше тридцати секунд.",
        ],
    },
    {
        "id": "13_economy",
        "min_sec": 30,
        "still": "13_economy.png",
        "lines": [
            "Для проекта рассчитаны затраты на API, инфраструктуру, разработку и сопровождение.",
            "В бюджет заложен резерв на непредвиденные расходы.",
            "Для коммерческого применения предлагается B2B-модель подписки с отдельной настройкой под каждого дилера.",
            "Точные значения приведены в финансовом расчёте проекта.",
        ],
    },
    {
        "id": "14_roadmap",
        "min_sec": 25,
        "still": "14_roadmap.png",
        "lines": [
            "Следующий этап — эксплуатационное укрепление проекта: подключение рабочей модели, векторного поиска и одной реальной интеграции.",
            "После закрытого пилота и подтверждения качества систему можно масштабировать на другие автосалоны.",
        ],
    },
    {
        "id": "15_finale",
        "min_sec": 15,
        "still": "15_finale.png",
        "lines": [
            "AutoSfera AI показывает полный путь от постановки задачи и подготовки базы знаний до работающего ассистента, оценки качества и расчёта экономики.",
            "Спасибо за внимание.",
        ],
    },
]


def fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont, ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    segoe = Path(r"C:\Windows\Fonts\segoeui.ttf")
    segoeb = Path(r"C:\Windows\Fonts\segoeuib.ttf")
    if not segoe.exists():
        raise SystemExit("Segoe UI font not found")
    return (
        ImageFont.truetype(str(segoeb), 54),
        ImageFont.truetype(str(segoeb), 36),
        ImageFont.truetype(str(segoe), 28),
        ImageFont.truetype(str(segoe), 22),
    )


def paste_mascot(img: Image.Image, size: int = 520, xy: tuple[int, int] | None = None) -> None:
    path = ASSETS / "dis-mascot.png"
    if not path.exists():
        return
    fox = Image.open(path).convert("RGBA")
    fox.thumbnail((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", fox.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fox.width - 1, fox.height - 1), 28, fill=255)
    fox.putalpha(mask)
    x, y = xy or (W - fox.width - 70, (H - fox.height) // 2)
    img.alpha_composite(fox, (x, y))


def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def base_canvas() -> Image.Image:
    img = Image.new("RGBA", (W, H), NAVY + (255,))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 18, H), fill=ORANGE)
    draw.rectangle((0, H - 10, W, H), fill=ULTRA)
    return img


def save_still(name: str, img: Image.Image) -> None:
    STILLS.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(STILLS / name, quality=95)


def render_stills() -> None:
    title, h2, body, small = fonts()
    STILLS.mkdir(exist_ok=True)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    paste_mascot(img, 620, (1240, 200))
    d.text((80, 160), "AutoSfera AI", font=title, fill=WHITE)
    d.text((80, 240), "единый интеллект автодилера", font=h2, fill=ORANGE)
    d.text((80, 360), "Итоговый проект курса", font=body, fill=MUTED)
    d.text((80, 430), "Автор: Степанов Д.А.", font=h2, fill=WHITE)
    d.text((80, 980), "Защита MVP  ·  5–7 минут", font=small, fill=MUTED)
    save_still("01_title.png", img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    d.text((80, 70), "Проблема автосалона", font=title, fill=WHITE)
    problems = [
        "Повторяющиеся обращения клиентов",
        "Длительное ожидание ответа",
        "Информация в разных документах и системах",
        "Запросы попадают не тому специалисту",
        "Сотрудники тратят время на ручной поиск",
        "Риск ошибочного или неподтверждённого ответа",
    ]
    for i, item in enumerate(problems):
        y = 180 + i * 120
        d.rounded_rectangle((80, y, 1840, y + 100), 18, fill=CARD)
        d.ellipse((110, y + 28, 154, y + 72), fill=ORANGE)
        d.text((180, y + 28), item, font=h2, fill=WHITE)
    save_still("02_problem.png", img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    d.text((80, 70), "Кому помогает и что умеет", font=title, fill=WHITE)
    users = ["Потенциальные покупатели", "Действующие клиенты", "Менеджеры по продажам", "Сотрудники сервиса", "Внутренние сотрудники"]
    feats = ["Подбор автомобиля", "Условия покупки", "Документы сделки", "Статус заказа", "Гарантия", "Запись на тест-драйв или сервис", "Передача человеку"]
    d.text((80, 160), "Пользователи", font=h2, fill=ORANGE)
    for i, item in enumerate(users):
        y = 220 + i * 70
        d.rounded_rectangle((80, y, 900, y + 58), 12, fill=CARD)
        d.text((110, y + 12), item, font=body, fill=WHITE)
    d.text((980, 160), "Функции MVP", font=h2, fill=ORANGE)
    for i, item in enumerate(feats):
        y = 220 + i * 70
        d.rounded_rectangle((980, y, 1840, y + 58), 12, fill=CARD)
        d.text((1010, y + 12), item, font=body, fill=WHITE)
    save_still("03_solution.png", img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    d.text((80, 60), "Архитектура", font=title, fill=WHITE)
    flow = ["Пользователь", "Веб-интерфейс", "AI-оркестратор", "Агент", "RAG и база знаний", "Ответ"]
    for i, label in enumerate(flow):
        x = 70 + i * 310
        d.rounded_rectangle((x, 160, x + 280, 250), 16, fill=CARD)
        d.text((x + 20, 188), label, font=small, fill=WHITE)
        if i < len(flow) - 1:
            d.polygon([(x + 286, 205), (x + 304, 195), (x + 304, 215)], fill=ORANGE)
    d.rounded_rectangle((70, 280, 1850, 360), 16, fill=(24, 48, 96))
    d.text((100, 304), "При необходимости: Action Gateway  →  подтверждение человеком  →  n8n", font=body, fill=WHITE)
    agents = [
        ("Sales Agent", "продажи и подбор"),
        ("Support Agent", "заказы и поддержка"),
        ("Service Agent", "сервис и гарантия"),
        ("Employee Agent", "внутренние процессы"),
    ]
    for i, (name, desc) in enumerate(agents):
        x = 70 + (i % 4) * 460
        y = 420
        d.rounded_rectangle((x, y, x + 430, y + 220), 18, fill=CARD)
        d.rectangle((x, y, x + 12, y + 220), fill=ORANGE if i == 0 else ULTRA)
        d.text((x + 36, y + 40), name, font=h2, fill=WHITE)
        for j, line in enumerate(wrap(d, desc, body, 360)):
            d.text((x + 36, y + 110 + j * 36), line, font=body, fill=MUTED)
    d.text((80, 720), "Стек: FastAPI  ·  LangGraph  ·  17 skills  ·  TF-IDF RAG  ·  PostgreSQL / SQLite", font=body, fill=MUTED)
    d.text((80, 790), "Простые запросы — экономичная модель; сложные — более мощная.", font=body, fill=MUTED)
    save_still("04_architecture.png", img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    d.text((80, 80), "База знаний и отказ от выдумки", font=title, fill=WHITE)
    facts = [
        "51 логический документ",
        "Разделение по темам и доступу",
        "Фильтр: роль, агент, dealer_id",
        "Указание источника в ответе",
        "Нет подтверждённых данных — нет ответа",
        "Уточнение или передача сотруднику",
    ]
    for i, item in enumerate(facts):
        x = 80 + (i % 2) * 920
        y = 220 + (i // 2) * 220
        d.rounded_rectangle((x, y, x + 860, y + 180), 18, fill=CARD)
        d.text((x + 40, y + 60), item, font=h2, fill=WHITE)
    save_still("05_kb.png", img)

    demo_titles = [
        ("06_demo_s1.png", "Сценарий 1", "Подбор автомобиля", "Sales Agent  ·  vehicle_selection"),
        ("07_demo_s2.png", "Сценарий 2", "Смена темы: документы сделки", "Support Agent  ·  documentation_support"),
        ("08_demo_s3.png", "Сценарий 3", "Гарантия и неисправность", "Service Agent  ·  warranty_consultation"),
        ("09_demo_s4.png", "Сценарий 4", "Запись на тест-драйв", "Sales Agent  ·  test_drive_booking"),
        ("10_demo_s5.png", "Сценарий 5", "Скидка и условия договора", "Эскалация менеджеру"),
        ("11_demo_s6.png", "Сценарий 6", "Вопрос вне области", "Оркестратор  ·  корректное ограничение"),
    ]
    for fname, kicker, heading, meta in demo_titles:
        img = base_canvas()
        d = ImageDraw.Draw(img)
        paste_mascot(img, 280, (1560, 740))
        d.text((80, 80), kicker, font=h2, fill=ORANGE)
        d.text((80, 170), heading, font=title, fill=WHITE)
        d.text((80, 280), meta, font=body, fill=MUTED)
        d.text((80, 980), "Живой интерфейс  ·  без изменения бизнес-логики", font=small, fill=MUTED)
        save_still(fname, img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    d.text((80, 70), "Подтверждённые результаты", font=title, fill=WHITE)
    metrics = [
        ("4", "специализированных агента"),
        ("17", "зарегистрированных skills"),
        ("51", "логический документ KB"),
        ("150", "успешных pytest"),
        ("2", "пропущены (внешняя инфр.)"),
        ("13/13", "оркестратор, Stage 2"),
        ("GO", "RAG evaluation"),
        ("< 30 с", "требование времени ответа"),
    ]
    for i, (num, label) in enumerate(metrics):
        x = 80 + (i % 4) * 460
        y = 200 + (i // 4) * 340
        d.rounded_rectangle((x, y, x + 430, y + 280), 18, fill=CARD)
        d.text((x + 36, y + 50), num, font=title, fill=ORANGE)
        for j, line in enumerate(wrap(d, label, body, 350)):
            d.text((x + 36, y + 150 + j * 36), line, font=body, fill=WHITE)
    save_still("12_results.png", img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    d.text((80, 70), "Экономика проекта", font=title, fill=WHITE)
    d.text((80, 150), "Структура затрат из ТЗ. Суммы в ролике не подставляются.", font=body, fill=MUTED)
    rows = [
        "Расходы на API языковых моделей",
        "Инфраструктура (хостинг, БД, мониторинг)",
        "Разработка MVP и сопровождение",
        "Резерв 20–30% на непредвиденные расходы",
        "Месячная стоимость и бюджет первого года — в финансовом расчёте",
        "Монетизация: B2B-подписка с настройкой под дилера",
        "Точка безубыточности — по финансовому расчёту проекта",
    ]
    for i, row in enumerate(rows):
        y = 230 + i * 100
        d.rounded_rectangle((80, y, 1840, y + 84), 14, fill=CARD)
        d.text((120, y + 24), row, font=body, fill=WHITE)
    save_still("13_economy.png", img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    d.text((80, 70), "Дальнейшее развитие", font=title, fill=WHITE)
    steps = [
        "Исправление оставшихся ошибок маршрутизации",
        "Внешний staging",
        "Подключение live LLM и pgvector",
        "Одна реальная CRM или система записи",
        "Закрытый пилот в одном автосалоне",
        "Масштабирование на сеть после подтверждения метрик",
    ]
    for i, step in enumerate(steps):
        y = 180 + i * 130
        d.ellipse((90, y + 8, 150, y + 68), fill=ORANGE)
        d.text((104, y + 16), str(i + 1), font=h2, fill=NAVY)
        d.rounded_rectangle((180, y, 1840, y + 90), 16, fill=CARD)
        d.text((220, y + 24), step, font=h2, fill=WHITE)
    save_still("14_roadmap.png", img)

    img = base_canvas()
    d = ImageDraw.Draw(img)
    paste_mascot(img, 620, (1240, 200))
    d.text((80, 220), "AutoSfera AI", font=title, fill=WHITE)
    d.text((80, 320), "От работающего MVP —", font=h2, fill=ORANGE)
    d.text((80, 380), "к закрытому пилоту", font=h2, fill=ORANGE)
    d.text((80, 520), "Автор: Степанов Д.А.", font=body, fill=WHITE)
    d.text((80, 980), "Спасибо за внимание", font=small, fill=MUTED)
    save_still("15_finale.png", img)


def duration_sec(path: Path) -> float:
    out = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    ).strip()
    return float(out)


def srt_stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def synthesize() -> list[dict]:
    import edge_tts

    VO.mkdir(parents=True, exist_ok=True)
    voice = "ru-RU-DmitryNeural"
    cues: list[dict] = []
    t0 = 0.0
    for scene in SCENES:
        parts: list[Path] = []
        for i, line in enumerate(scene["lines"], 1):
            part = VO / f"{scene['id']}_{i:02d}.mp3"
            if not part.exists() or part.stat().st_size < 1000:
                communicate = edge_tts.Communicate(line, voice, rate="-6%")
                await communicate.save(str(part))
            dur = duration_sec(part)
            cues.append({"start": t0, "end": t0 + dur, "text": line, "scene": scene["id"]})
            t0 += dur
            parts.append(part)
        concat = VO / f"{scene['id']}.mp3"
        lst = VO / f"{scene['id']}.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        subprocess.check_call(
            [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(concat)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        vo_dur = duration_sec(concat)
        scene["_vo"] = vo_dur
        scene["_start"] = t0 - vo_dur
        hold = max(0.0, scene["min_sec"] - vo_dur)
        scene["_hold"] = hold
        t0 += hold
        scene["_duration"] = vo_dur + hold
    (VO / "timings.json").write_text(json.dumps({"scenes": SCENES, "cues": cues}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_srt(cues, SCENES)
    return SCENES


def wrap_caption(text: str) -> str:
    if len(text) <= 82:
        return text
    cut = text.rfind(" ", 0, 82)
    if cut < 28:
        cut = 82
    return text[:cut] + "\n" + text[cut + 1 :]


def write_srt(cues: list[dict], scenes: list[dict] | None = None) -> None:
    # Cue timestamps already include per-scene holds from synthesize().
    lines = []
    for i, cue in enumerate(cues, 1):
        a, b, text = float(cue["start"]), float(cue["end"]), cue["text"]
        lines.append(str(i))
        lines.append(f"{srt_stamp(a)} --> {srt_stamp(b)}")
        lines.append(wrap_caption(text))
        lines.append("")
    (ROOT / "subtitles.srt").write_text("\n".join(lines), encoding="utf-8")


def still_for(scene: dict) -> Path:
    cap = scene.get("capture")
    if cap:
        p = CAPTURES / cap
        if p.exists():
            return p
    return STILLS / scene["still"]


def assemble_mp4(scenes: list[dict]) -> Path:
    clips = ROOT / "clips"
    clips.mkdir(exist_ok=True)
    concat_list = clips / "list.txt"
    rows = []
    for scene in scenes:
        src = still_for(scene)
        vo = VO / f"{scene['id']}.mp3"
        out = clips / f"{scene['id']}.mp4"
        dur = scene["_duration"]
        # Pad audio with silence so video hold matches storyboard.
        padded = clips / f"{scene['id']}_audio.m4a"
        subprocess.check_call(
            [
                FFMPEG, "-y",
                "-i", str(vo),
                "-af", f"apad=pad_dur={scene['_hold']:.3f}",
                "-t", f"{dur:.3f}",
                "-c:a", "aac", "-b:a", "192k",
                str(padded),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.check_call(
            [
                FFMPEG, "-y",
                "-loop", "1", "-framerate", "30", "-i", str(src),
                "-i", str(padded),
                "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                "-crf", "18",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                "-c:a", "copy", "-shortest", "-t", f"{dur:.3f}",
                str(out),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        rows.append(f"file '{out.name}'")
    concat_list.write_text("\n".join(rows) + "\n", encoding="utf-8")
    raw = clips / "raw.mp4"
    subprocess.check_call(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(raw)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(clips),
    )
    final = ROOT / "AutoSfera_AI_Defense_Stepanov_DA.mp4"
    srt_name = "subtitles.srt"
    style = "FontName=Segoe UI,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00110B1B,Outline=2,MarginV=72,Alignment=2"
    cmd = [
        FFMPEG, "-y", "-i", str(raw),
        "-vf", f"subtitles={srt_name}:force_style='{style}'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(final),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        print("subtitle burn failed:", proc.stderr[-1200:])
        subprocess.check_call(
            [FFMPEG, "-y", "-i", str(raw), "-c", "copy", str(final)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return final


def load_scenes() -> list[dict]:
    data = json.loads((VO / "timings.json").read_text(encoding="utf-8"))
    return data["scenes"]


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    skip_video = "--skip-video" in args
    video_only = "--video-only" in args
    if not video_only:
        render_stills()
        scenes = asyncio.run(synthesize())
    else:
        scenes = load_scenes()
    total = sum(float(s["_duration"]) for s in scenes)
    print(f"stills/VO ready; duration {total:.1f}s")
    if total < 300 or total > 420:
        print("WARN: duration outside 5–7 min window", file=sys.stderr)
    if skip_video:
        return
    out = assemble_mp4(scenes)
    print("wrote", out, "size", out.stat().st_size)


if __name__ == "__main__":
    main()
