from __future__ import annotations

from fastapi.testclient import TestClient

import autonova.api.main as api_main
from autonova.api.main import create_app
from autonova.config import Settings, get_settings
from autonova.storage import PlatformStore, build_store


def test_settings_select_storage_backend() -> None:
    assert Settings(DATABASE_URL="").storage_backend == "sqlite"
    assert Settings(DATABASE_URL="postgresql://user:pass@db/app").storage_backend == "postgresql"


def test_store_factory_keeps_sqlite_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fallback.db"))
    get_settings.cache_clear()
    store = build_store()
    assert isinstance(store, PlatformStore)
    assert store.healthcheck() == {"ok": True, "backend": "sqlite"}
    get_settings.cache_clear()


def test_readiness_reports_database_failure(monkeypatch) -> None:
    class BrokenStore:
        def healthcheck(self):
            return {"ok": False, "backend": "postgresql", "error": "OperationalError"}

    monkeypatch.setattr(api_main, "get_store", lambda: BrokenStore())
    client = TestClient(create_app())
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "not_ready"
