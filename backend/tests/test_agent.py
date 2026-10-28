import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.agent import TestForgeAgent
from backend.sandbox import RESULT_MARKER


VALID_TEST = """from fastapi.testclient import TestClient

def test_health():
    assert TestClient(app).get('/health').status_code == 200
"""


def model_response(content, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        model="muse-spark-1.3",
        _request_id="req_testforge_sample",
    )


def sandbox_output(metadata, output="pytest output"):
    return f"{output}\n{RESULT_MARKER}{json.dumps(metadata)}"


class FakeSandbox:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def run_test_in_docker(self, test_code, route_code):
        self.calls.append((test_code, route_code))
        return self.outcomes.pop(0)


def fake_client(*responses):
    create = AsyncMock(side_effect=list(responses))
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )


def meta(exit_code=0, collected=1, passed=1, failures=0, errors=0, error_type=None):
    return {
        "exit_code": exit_code,
        "collected": collected,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": 0,
        "error_type": error_type,
        "duration_seconds": 0.1,
    }


def test_missing_credentials_returns_error_without_calling_model():
    agent = TestForgeAgent(sandbox=FakeSandbox([]), environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "error"
    assert result["defect_detected"] is False
    assert agent.client is None


def test_model_timeout_returns_error_not_success():
    client = fake_client(TimeoutError("request timed out"))
    agent = TestForgeAgent(client=client, sandbox=FakeSandbox([]), environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "error"
    assert any("category=timed_out" in entry for entry in result["logs"])


def test_api_failure_logs_category_without_exception_text_or_credentials():
    client = fake_client(TimeoutError("secret-value-must-not-be-logged"))
    agent = TestForgeAgent(client=client, sandbox=FakeSandbox([]), environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "error"
    all_logs = "\n".join(result["logs"])
    assert "category=timed_out" in all_logs
    assert "secret-value-must-not-be-logged" not in all_logs


def test_zero_collected_tests_is_never_reported_as_success():
    client = fake_client(
        model_response(VALID_TEST),
        *(model_response("not valid Python") for _ in range(3)),
    )
    sandbox = FakeSandbox(
        [
            (
                False,
                sandbox_output(
                    meta(exit_code=5, collected=0, passed=0, error_type="no_tests_collected"),
                    "no tests collected",
                ),
            )
        ]
    )
    agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "failed"
    assert result["defect_detected"] is False
    assert result["metrics"]["testsCollected"] == 0
    assert client.chat.completions.create.await_count == 4


def test_even_reported_exit_zero_with_zero_tests_is_never_green():
    client = fake_client(
        model_response(VALID_TEST),
        *(model_response("not valid Python") for _ in range(3)),
    )
    sandbox = FakeSandbox(
        [
            (
                True,
                sandbox_output(
                    meta(
                        exit_code=0,
                        collected=0,
                        passed=0,
                        error_type="no_tests_collected",
                    ),
                    "no tests collected",
                ),
            )
        ]
    )
    agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "failed"
    assert result["defect_detected"] is False


def test_all_skipped_tests_are_never_reported_as_passed():
    client = fake_client(model_response(VALID_TEST), model_response("UNCERTAIN"))
    sandbox = FakeSandbox(
        [
            (
                True,
                sandbox_output(
                    {
                        **meta(exit_code=0, collected=1, passed=0),
                        "skipped": 1,
                    },
                    "1 skipped in 0.02s",
                ),
            )
        ]
    )
    agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "failed"
    assert result["defect_detected"] is False


def test_docker_and_sandbox_errors_never_return_green():
    for error_type in ("docker_unavailable", "sandbox_error"):
        client = fake_client(model_response(VALID_TEST))
        sandbox = FakeSandbox(
            [(False, sandbox_output({"error_type": error_type, "exit_code": None}))]
        )
        agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

        result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

        assert result["status"] == "error"
        assert result["defect_detected"] is False


def test_application_initialization_error_is_reported_without_test_repair():
    client = fake_client(model_response(VALID_TEST), model_response("API_DEFECT"))
    diagnosis = {
        "category": "application_error",
        "title": "Application Initialization Error",
        "message": "FastAPI rejected the route definition; no endpoint assertions ran.",
        "endpoint_assertions_ran": False,
        "suggestion": "class UserRegister(BaseModel):",
    }
    sandbox = FakeSandbox(
        [
            (
                False,
                sandbox_output(
                    {
                        **meta(exit_code=2, collected=0, passed=0, errors=1, error_type="application_error"),
                        "diagnosis": diagnosis,
                    },
                    "FastAPIError: Invalid args for response field",
                ),
            )
        ]
    )
    agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

    result = asyncio.run(agent.generate_and_heal("class UserRegister(): ..."))

    assert result["status"] == "failed"
    assert result["defect_detected"] is False
    assert result["failure_type"] == "application_error"
    assert result["metrics"]["pytestExitCode"] == 2
    assert result["metrics"]["testsErrored"] == 1
    assert result["diagnosis"]["endpoint_assertions_ran"] is False
    assert "BaseModel" in result["diagnosis"]["suggestion"]
    assert len(sandbox.calls) == 1
    assert client.chat.completions.create.await_count == 1


def test_collection_error_cannot_be_overridden_by_meta_defect_verdict():
    client = fake_client(model_response(VALID_TEST), model_response("API_DEFECT"))
    diagnosis = {
        "category": "test_collection_error",
        "title": "Test Collection Error",
        "message": "Pytest failed to import the generated test module; no endpoint assertions ran.",
        "endpoint_assertions_ran": False,
        "exception_type": "ImportError",
        "exception_message": "cannot import name app",
    }
    sandbox = FakeSandbox(
        [
            (
                False,
                sandbox_output(
                    {
                        **meta(exit_code=2, collected=0, passed=0, errors=1, error_type="test_collection_error"),
                        "diagnosis": diagnosis,
                    },
                    "ERROR collecting test_app.py\nImportError while importing test module",
                ),
            )
        ]
    )
    agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "failed"
    assert result["defect_detected"] is False
    assert result["failure_type"] == "test_collection_error"
    assert result["metrics"]["testsCollected"] == 0
    assert result["metrics"]["testsErrored"] == 1
    assert result["metrics"]["pytestExitCode"] == 2
    assert client.chat.completions.create.await_count == 1


def test_fixture_error_is_repaired_and_then_real_pass_is_reported():
    client = fake_client(
        model_response(VALID_TEST),
        model_response(VALID_TEST),
    )
    sandbox = FakeSandbox(
        [
            (
                False,
                sandbox_output(
                    meta(exit_code=1, collected=1, passed=0, errors=1, error_type="test_setup_error"),
                    "fixture setup error",
                ),
            ),
            (True, sandbox_output(meta())),
        ]
    )
    agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "success"
    assert result["metrics"]["testsPassed"] == 1
    assert any(
        "provider=meta_model_api" in entry
        and "requested_model=muse-spark-1.3" in entry
        and "returned_model=muse-spark-1.3" in entry
        and "request_id=req_testforge_sample" in entry
        for entry in result["logs"]
    )
    assert client.chat.completions.create.await_count == 2
    repair_prompt = client.chat.completions.create.await_args_list[1].kwargs["messages"][-1]["content"]
    assert "Previous test code" in repair_prompt
    assert VALID_TEST in repair_prompt
    assert "Do not classify the API as defective" in repair_prompt


def test_assertion_failure_is_classified_as_defect_without_rewriting_test():
    client = fake_client(model_response(VALID_TEST), model_response("API_DEFECT"))
    sandbox = FakeSandbox(
        [
            (
                False,
                sandbox_output(
                    meta(exit_code=1, collected=1, passed=0, failures=1, error_type="assertion_failure"),
                    "AssertionError: expected 400, got 500",
                ),
            )
        ]
    )
    agent = TestForgeAgent(client=client, sandbox=sandbox, environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "defect_detected"
    assert result["defect_detected"] is True
    assert result["code"] == VALID_TEST.strip()
    assert client.chat.completions.create.await_count == 2


def test_repair_attempts_are_limited_to_three():
    client = fake_client(*(model_response("not valid Python") for _ in range(4)))
    agent = TestForgeAgent(client=client, sandbox=FakeSandbox([]), environ={})

    result = asyncio.run(agent.generate_and_heal("from fastapi import FastAPI"))

    assert result["status"] == "failed"
    assert client.chat.completions.create.await_count == 4  # initial + 3 repairs
