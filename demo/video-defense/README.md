# Видео защиты AutoSfera AI

Комплект для ролика **5–7 минут**: озвучка, слайды, субтитры, план монтажа и (если среда позволяет) итоговый MP4.

Публичное имя продукта: **AutoSfera AI**. Технический пакет `autonova` на экране не подписывать.

## Состав папки

| Файл | Назначение |
|---|---|
| `video_script.md` | Полный текст мужской озвучки |
| `storyboard.md` | Покадровый план |
| `demo_questions.md` | 6 живых запросов и ожидаемое поведение |
| `subtitles.srt` | Русские субтитры по фактическим таймингам VO |
| `recording_checklist.md` | Подготовка экрана и приложения |
| `editing_plan.md` | Громкость, переходы, музыка |
| `assets/dis-mascot.png` | Маскот ДИС |
| `vo/` | Мужская озвучка по сценам |
| `stills/` | Заставки 1920×1080 |
| `captures/` | Кадры живого чата (если API был доступен) |
| `AutoSfera_AI_Defense_Stepanov_DA.mp4` | Итоговый файл (не коммитить в Git, если большой) |

## Подтверждённые цифры (не подменять)

| Показатель | Источник | Значение |
|---|---|---|
| Агенты | `/health` | 4 (`SALES`, `SUPPORT`, `SERVICE`, `EMPLOYEE`) |
| Skills | `/health` | **17** |
| Документы KB | `/health` | **51** |
| pytest | `docs/PRE_RELEASE_ACCEPTANCE.md` | **150 passed, 2 skipped** |
| Stage 2 маршрутизации | `reports/stage-2/report.md` | **13/13 PASS** |
| RAG evaluation | `reports/rag-eval/report.md` | **GO** |
| Время ответа MVP | приёмка | требование **< 30 с**; факт макс. **3.166 с** |

**Не произносить:** «159 тестов», «покрытие 82%», «Stage 1 — 13/13» (`reports/stage-1/report.md` = 9/13).  
**Не подставлять суммы в рублях**, если их нет в ТЗ: на слайде экономики — структура затрат и B2B-подписка, без выдуманных ₽.

## Сборка озвучки и слайдов

```powershell
Set-Location "C:\Users\user\Desktop\AutoSfera AI"
python demo/video-defense/build_assets.py
```

Нужны: Python 3.11+, `edge-tts`, FFmpeg в PATH или стандартный WinGet-путь Gyan.FFmpeg.

## Живая демонстрация

1. Поднять API по `recording_checklist.md`.
2. Открыть только `http://127.0.0.1:8000/`.
3. Прогнать `demo_questions.md` (сценарий 2 — в той же сессии, что сценарий 1).
4. Не менять бизнес-логику ради кадра.

Если API недоступен, в ролик идут слайды с **фактическими** ответами из последнего прогона `demo/results/` и оговорка в титре «кадры интерфейса — из рабочей сессии / реконструкция по журналу приёмки». Не выдумывать реплики агента.

## CapCut / Clipchamp (если авторендер недоступен)

Порядок дорожек:

1. `stills/01_title.png` + `vo/01_intro.mp3`
2. `stills/02_problem.png` + `vo/02_problem.mp3`
3. `stills/03_solution.png` + `vo/03_solution.mp3`
4. `stills/04_architecture.png` + `vo/04_architecture.mp3`
5. `stills/05_kb.png` + `vo/05_kb.mp3`
6. Записи чата s1–s6 + `vo/06`–`vo/11`
7. `stills/12_results.png` + `vo/12_results.mp3`
8. `stills/13_economy.png` + `vo/13_economy.mp3`
9. `stills/14_roadmap.png` + `vo/14_roadmap.mp3`
10. `stills/15_finale.png` + `vo/15_finale.mp3`

Импортировать `subtitles.srt`. Фон: свой лицензированный трек, −18…−22 dB к голосу. **Не вставлять запись Ванессы Мэй**, если нет лицензии.

Экспорт: 1920×1080, 30 fps, H.264, AAC, имя `AutoSfera_AI_Defense_Stepanov_DA.mp4`.

## Готовый файл

Собран локально: `demo/video-defense/AutoSfera_AI_Defense_Stepanov_DA.mp4`  
Хронометраж: **5 мин 17 с** (паузы между слайдами сокращены втрое). Голос: `ru-RU-DmitryNeural`. Субтитры вшиты снизу (`subtitles.ass` / `subtitles.srt`).

Музыку Ванессы Мэй **не добавляли** как коммерческий трек. Фон — Вивальди «Времена года» (John Harrison, CC BY-SA), тише голоса; лицензия в `assets/BGM_LICENSE.txt`.

Крупный MP4 и папку `clips/` в Git лучше не коммитить.
