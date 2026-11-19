import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.ai import DemoAnswerer, OpenAIAnswerer
from backend.app.config import ROOT, Settings
from backend.app.main import create_app
from backend.app.repository import ServiceError, SQLiteRepository
from backend.app.summary import summarize
from scripts.generate_data import generate


@pytest.fixture
def client(tmp_path):
    settings = Settings(sqlite_path=tmp_path / "demo.sqlite3")
    with TestClient(create_app(settings)) as app:
        yield app


def observation(value=50):
    return {"date": "2026-11-15T00:00:00+09:00", "metric": "cpu", "value": value, "memo": "test", "host": "demo-01"}


def test_dataset_is_reproducible_and_matches_manifest():
    stored = json.loads((ROOT / "data/metrics.json").read_text(encoding="utf-8"))
    assert stored == generate()
    assert len({row["date"] for row in stored}) == 336
    assert len(stored) == 672
    assert all(0 <= row["value"] <= 100 for row in stored)
    assert len({row["id"] for row in stored}) == 672
    manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((ROOT / "data/metrics.json").read_bytes()).hexdigest() == manifest["sha256"]
    cpu_peak = max((row for row in stored if row["metric"] == "cpu"), key=lambda row: row["value"])
    assert cpu_peak["date"].startswith("2026-11-05")
    before = next(row["value"] for row in stored if row["date"] == "2026-11-10T07:00:00+09:00" and row["metric"] == "memory")
    after = next(row["value"] for row in stored if row["date"] == "2026-11-10T08:00:00+09:00" and row["metric"] == "memory")
    assert before - after > 40


def test_crud_refreshes_summary(client):
    original = client.get("/api/data/summary").json()
    assert original["count"] == 672
    added = client.post("/api/data", json=observation(100))
    assert added.status_code == 201
    identifier = added.json()["id"]
    updated_summary = client.get("/api/data/summary").json()
    assert updated_summary["count"] == 673
    assert updated_summary["metrics"]["cpu"]["max"] == 100
    assert updated_summary["metrics"]["cpu"]["max_at"] == observation()["date"]
    assert client.put(f"/api/data/{identifier}", json=observation(0)).status_code == 200
    assert client.get("/api/data/summary").json()["metrics"]["cpu"]["min"] == 0
    assert client.delete(f"/api/data/{identifier}").status_code == 204
    assert client.get("/api/data/summary").json() == original
    assert client.delete(f"/api/data/{identifier}").status_code == 404
    assert client.put(f"/api/data/{identifier}", json=observation()).status_code == 404


@pytest.mark.parametrize("change", [
    {"value": -1}, {"value": 101}, {"value": "NaN"}, {"value": "Infinity"},
    {"date": "2026-11-15T00:00:00"}, {"date": "not-a-date"}, {"metric": "disk"},
    {"host": "other-server"}, {"memo": "a" * 501}, {"unexpected": "field"},
])
def test_invalid_observations_rejected(client, change):
    assert client.post("/api/data", json=observation() | change).status_code == 422


def test_dates_normalize_to_kst(client):
    created = client.post("/api/data", json=observation() | {"date": "2026-11-14T15:00:00Z"}).json()
    assert created["date"] == observation()["date"]


def test_paginated_list_has_full_summary(client):
    page = client.get("/api/data?metric=memory&limit=2&offset=2").json()
    assert len(page["items"]) == 2 and page["total"] == 336
    assert all(row["metric"] == "memory" for row in page["items"])
    assert client.get("/api/data/summary").json()["count"] == 672


def test_summary_uses_timestamp_windows_and_percentage_points():
    rows = [
        {"id": "a", "date": "2026-11-01T23:00:00+09:00", "metric": "cpu", "value": 10},
        {"id": "b", "date": "2026-11-02T00:00:00+09:00", "metric": "cpu", "value": 20},
        {"id": "c", "date": "2026-11-02T23:00:00+09:00", "metric": "cpu", "value": 30},
        {"id": "d", "date": "2026-11-03T00:00:00+09:00", "metric": "cpu", "value": 50},
    ]
    stats = summarize(rows)["metrics"]["cpu"]
    # Recent (Nov 2 00:00, Nov 3 00:00] -> 30,50. Prior interval -> 10,20.
    assert stats["recent_24h_average"] == 40
    assert stats["previous_24h_average"] == 15
    assert stats["change_pp"] == 25 and stats["trend"] == "증가"
    assert stats["max_at"] == rows[-1]["date"]


def test_chat_autosaves_restores_and_continues(client):
    first = client.post("/api/chat", json={"message": "CPU 최고값은?"})
    assert first.status_code == 200
    assert first.json()["provider"] == "demo-rules"
    assert "GPT 미연결" in first.json()["message"]["content"]
    identifier = first.json()["conversation_id"]
    listing = client.get("/api/conversations").json()
    assert listing["messages_included"] is False
    assert "messages" not in listing["items"][0]
    assert listing["items"][0]["message_count"] == 2
    second = client.post("/api/chat", json={"message": "메모리는?", "conversation_id": identifier})
    assert second.json()["conversation_id"] == identifier
    loaded = client.get(f"/api/conversations/{identifier}").json()
    assert len(loaded["messages"]) == 4 and loaded["version"] == 2
    assert [item["role"] for item in loaded["messages"]] == ["user", "assistant", "user", "assistant"]
    copy = client.post("/api/conversations", json={"title": "사본", "messages": loaded["messages"]})
    assert copy.status_code == 201 and copy.json()["id"] != identifier
    assert client.delete(f"/api/conversations/{identifier}").status_code == 204
    assert client.get(f"/api/conversations/{identifier}").status_code == 404
    assert client.post("/api/chat", json={"message": "continue", "conversation_id": identifier}).status_code == 404


def test_chat_uses_changes_to_data(client):
    client.post("/api/data", json=observation(100))
    result = client.post("/api/chat", json={"message": "CPU 최고값은?"}).json()
    assert "100.00%" in result["message"]["content"]
    assert result["summary_count"] == 673


def test_empty_summary_and_deleted_data_do_not_return_on_restart(tmp_path):
    path = tmp_path / "demo.sqlite3"
    repo = SQLiteRepository(path)
    for row in repo.list("data"):
        repo.delete("data", row["id"])
    restarted = SQLiteRepository(path)
    assert not restarted.list("data")
    summary = summarize([])
    assert summary["period"] is None and summary["metrics"] == {"cpu": None, "memory": None}
    assert "저장된 데이터가 없습니다" in DemoAnswerer().answer("CPU?", [], summary)


def test_conversation_concurrent_update_does_not_lose_messages(tmp_path):
    repo = SQLiteRepository(tmp_path / "empty.sqlite3", seed=False)
    created = repo.create("conversations", {"version": 1, "messages": []})
    repo.replace("conversations", created["id"], {"version": 2, "messages": [{"role": "user", "content": "kept"}]}, expected_version=1)
    with pytest.raises(ServiceError) as exc:
        repo.replace("conversations", created["id"], {"version": 2, "messages": []}, expected_version=1)
    assert exc.value.status == 409
    assert repo.get("conversations", created["id"])["messages"][0]["content"] == "kept"


def test_failed_ai_call_does_not_save_conversation(tmp_path):
    class BrokenAnswerer:
        provider = "fake-failure"
        def answer(self, *args):
            raise ServiceError(502, "AI unavailable")

    with TestClient(create_app(Settings(sqlite_path=tmp_path / "db.sqlite3"), answerer=BrokenAnswerer())) as app:
        assert app.post("/api/chat", json={"message": "test"}).status_code == 502
        assert app.get("/api/conversations").json()["total"] == 0


def test_openai_request_has_fresh_context_and_bounded_output():
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", output_text="테스트 답변")
    provider = OpenAIAnswerer.__new__(OpenAIAnswerer)
    provider.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    provider.model = "configured-model"
    provider.max_tokens = 1000
    assert provider.answer("latest question", [{"role": "user", "content": "previous"}], {"count": 673}) == "테스트 답변"
    assert '"count": 673' in captured["instructions"]
    assert captured["input"][0]["content"] == "previous"
    assert captured["input"][-1]["content"] == "latest question"
    assert captured["store"] is False and captured["max_output_tokens"] == 1000


def test_production_never_silently_uses_demo(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_PATH", "")
    with pytest.raises(ValueError, match="credentials"):
        Settings.from_env()


def test_local_mode_requires_key_without_requiring_firestore(monkeypatch):
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_PATH", "")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings.from_env()
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder-not-a-real-key")
    settings = Settings.from_env()
    assert settings.mode == "local"
    assert not settings.firebase_json and not settings.firebase_path


def test_local_mode_uses_openai_and_persists_locally(tmp_path, monkeypatch):
    import backend.app.main as main_module

    class FakeOpenAI:
        provider = "openai"
        def __init__(self, settings):
            assert settings.openai_key == "test-placeholder-not-a-real-key"
        def answer(self, question, history, summary):
            assert summary["count"] == 672
            return "GPT adapter selected with local data"

    def forbidden_firestore(settings):
        raise AssertionError("Local mode must not initialize Firestore")

    monkeypatch.setattr(main_module, "OpenAIAnswerer", FakeOpenAI)
    monkeypatch.setattr(main_module, "FirestoreRepository", forbidden_firestore)
    settings = Settings(mode="local", sqlite_path=tmp_path / "local.sqlite3", openai_key="test-placeholder-not-a-real-key")
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/health").json()
        assert status["mode"] == "local" and status["ai_provider"] == "openai"
        assert status["storage"] == "sqlite" and status["ai_model"] == settings.openai_model
        result = client.post("/api/chat", json={"message": "CPU 최고값은?"})
        assert result.status_code == 200
        assert result.json()["provider"] == "openai"
        assert "로컬 데모" not in result.json()["message"]["content"]
        identifier = result.json()["conversation_id"]
        assert len(client.get(f"/api/conversations/{identifier}").json()["messages"]) == 2
    restored = SQLiteRepository(settings.sqlite_path)
    assert len(restored.get("conversations", identifier)["messages"]) == 2


def test_cors_and_swagger(client):
    response = client.options("/api/data", headers={"Origin": "http://localhost:8000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8000"
    denied = client.options("/api/data", headers={"Origin": "https://unlisted.example", "Access-Control-Request-Method": "POST"})
    assert denied.status_code == 400
    assert client.get("/docs").status_code == 200
    assert "/api/data/summary" in client.get("/openapi.json").json()["paths"]


def test_chat_rate_limit_and_blank_input(client):
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 2001}).status_code == 422
    for _ in range(12):
        assert client.post("/api/chat", json={"message": "CPU"}).status_code == 200
    assert client.post("/api/chat", json={"message": "CPU"}).status_code == 429
