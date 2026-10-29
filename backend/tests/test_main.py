from fastapi.testclient import TestClient
import pytest

from backend import main


def test_cors_defaults_are_explicit_local_origins(monkeypatch):
    monkeypatch.delenv("TESTFORGE_CORS_ORIGINS", raising=False)

    assert main.configured_cors_origins() == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_cors_configuration_rejects_wildcard_and_applies_explicit_origins():
    with pytest.raises(ValueError, match="explicit origins"):
        main.configured_cors_origins("https://frontend.example,*")

    middleware = next(
        item for item in main.app.user_middleware if item.cls.__name__ == "CORSMiddleware"
    )
    assert middleware.kwargs["allow_origins"] == main.CORS_ORIGINS
    assert middleware.kwargs["allow_credentials"] is False
    assert middleware.kwargs["allow_methods"] == ["POST"]
    assert middleware.kwargs["allow_headers"] == ["content-type"]


class FakeAgent:
    result = {}

    def __init__(self):
        self.closed = False

    async def generate_and_heal(self, code, mode="standard"):
        return {**self.result, "received_code": code, "received_mode": mode}

    async def aclose(self):
        self.closed = True


def test_endpoint_calls_agent_and_returns_actual_success_result(monkeypatch):
    FakeAgent.result = {
        "status": "success",
        "defect_detected": False,
        "logs": ["pytest: 1 passed"],
        "code": "def test_api(): pass",
    }
    monkeypatch.setattr(main, "TestForgeAgent", FakeAgent)

    response = TestClient(main.app).post(
        "/generate-tests", json={"code": "app = FastAPI()"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["received_code"] == "app = FastAPI()"
    assert response.json()["received_mode"] == "standard"


def test_endpoint_forwards_adversarial_mode(monkeypatch):
    FakeAgent.result = {
        "status": "success",
        "defect_detected": False,
        "logs": ["pytest: 1 passed"],
        "code": "def test_adversarial(): pass",
    }
    monkeypatch.setattr(main, "TestForgeAgent", FakeAgent)

    response = TestClient(main.app).post(
        "/generate-tests", json={"code": "app = FastAPI()", "mode": "adversarial"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["received_mode"] == "adversarial"


def test_endpoint_rejects_unsupported_mode():
    response = TestClient(main.app).post(
        "/generate-tests", json={"code": "app = FastAPI()", "mode": "unsupported_fuzz"}
    )

    assert response.status_code == 422


def test_endpoint_returns_service_error_status_for_configuration_failure(monkeypatch):
    FakeAgent.result = {
        "status": "error",
        "defect_detected": False,
        "logs": ["Missing MODEL_API_KEY"],
        "code": "",
    }
    monkeypatch.setattr(main, "TestForgeAgent", FakeAgent)

    response = TestClient(main.app).post(
        "/generate-tests", json={"code": "app = FastAPI()"}
    )

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["defect_detected"] is False
