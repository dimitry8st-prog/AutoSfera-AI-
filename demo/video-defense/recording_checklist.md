# Чеклист записи экрана — защита AutoSfera AI

## Запуск

Из корня репозитория:

```powershell
Set-Location "C:\Users\user\Desktop\AutoSfera AI"
$env:BUILD_SHA = (git rev-parse --short HEAD)
docker compose up -d
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Depth 6
Invoke-RestMethod http://127.0.0.1:8000/ready | ConvertTo-Json -Depth 6
```

Альтернатива без Docker (SQLite fallback):

```powershell
uvicorn autonova.api.main:app --app-dir src --host 127.0.0.1 --port 8000
```

Ожидание `/health`: версия `3.1.0-beta.1`, 4 агента, `"skills": 17`, `kb_documents: 51`.

## Экран

- Масштаб страницы **100%**.
- Только вкладка `http://127.0.0.1:8000/`.
- Закрыть `.env`, DevTools Headers, уведомление активации Windows, личные вкладки.
- Движение курсора плавное.

## Съёмка

1. Заставка (титул + маскот ДИС) — не из браузера.
2. Проблема / решение / архитектура / KB — слайды.
3. Живой чат: сценарии из `demo_questions.md`.
4. Результаты / экономика / развитие / финал — слайды.

Не ускорять ответы ассистента. Можно вырезать только ожидание контейнеров.

Готовый файл: `demo/video-defense/AutoSfera_AI_Defense_Stepanov_DA.mp4` (в Git не добавлять, если файл большой).
