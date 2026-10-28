from fastapi.testclient import TestClient

from backend import main


class FakeAgent:
    result = {}

    def __init__(self):
        self.closed = False

    async def generate_and_heal(self, code):
        return {**self.result, "received_code": code}

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
