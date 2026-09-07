FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system autosfera && adduser --system --ingroup autosfera autosfera

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY frontend ./frontend
COPY knowledge_base ./knowledge_base
COPY prompts ./prompts

RUN python -m pip install --upgrade pip && python -m pip install .

RUN mkdir -p /app/data /app/logs && chown -R autosfera:autosfera /app
USER autosfera

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn autonova.api.main:app --host 0.0.0.0 --port 8000"]
