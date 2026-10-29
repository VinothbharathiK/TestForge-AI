"""Deterministic unit tests for backend/eval_phase5.py.

These tests use only in-process fakes and do not require Meta credentials,
network access, or a Docker daemon.  They verify scenario registry integrity,
outcome evaluation logic, aggregate metric computation, and report generation.
"""

import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.eval_phase5 import (
    ALL_SCENARIO_NAMES,
    SCENARIO_META,
    _aggregate,
    _evaluate_outcome,
    _markdown_report,
    _run_eval_scenario,
    EvalFixtureInjectionAgent,
)
from backend.agent import MAX_REPAIR_ATTEMPTS, TestForgeAgent
from backend.sandbox import RESULT_MARKER


# ---------------------------------------------------------------------------
# Helpers mirroring the style used in test_agent.py
# ---------------------------------------------------------------------------

def model_response(content, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        model="muse-spark-1.3",
        _request_id="req_eval_test",
    )


def sandbox_output(metadata, output="pytest output"):
    return f"{output}\n{RESULT_MARKER}{json.dumps(metadata)}"


class FakeRecordingSandbox:
    """Minimal fake that matches the RecordingSandbox interface."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.runs = []
        self.calls = []

    async def run_test_in_docker(self, test_code, route_code):
        self.calls.append((test_code, route_code))
        passed, raw = self.outcomes.pop(0)
        output, metadata = TestForgeAgent._parse_sandbox_result(raw)
        self.runs.append(
            {
                "passed": passed,
                "test_code": test_code,
                "output": output,
                "metadata": metadata,
            }
        )
        return passed, raw


def _meta(
    exit_code=0, collected=1, passed=1, failures=0, errors=0,
    error_type=None, duration=1.0,
):
    return {
        "exit_code": exit_code,
        "collected": collected,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": 0,
        "error_type": error_type,
        "duration_seconds": duration,
    }


def fake_client(*responses):
    create = AsyncMock(side_effect=list(responses))
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )


MINIMAL_TEST = """\
from fastapi.testclient import TestClient

def test_ok():
    assert TestClient(app).get('/').status_code in (200, 404)
"""


# ---------------------------------------------------------------------------
# 1. Scenario registry
# ---------------------------------------------------------------------------

def test_all_scenario_names_match_meta_keys():
    assert set(ALL_SCENARIO_NAMES) == set(SCENARIO_META.keys())


def test_every_scenario_has_required_fields():
    for name, meta in SCENARIO_META.items():
        assert "source" in meta, f"{name}: missing source"
        assert "kind" in meta, f"{name}: missing kind"
        assert "description" in meta, f"{name}: missing description"
        assert meta["kind"] in ("clean", "defect", "repair", "app_error"), \
            f"{name}: unexpected kind {meta['kind']!r}"
        assert isinstance(meta["source"], str) and meta["source"].strip(), \
            f"{name}: source is empty"


def test_defect_scenarios_have_known_bug():
    for name, meta in SCENARIO_META.items():
        if meta["kind"] == "defect":
            assert meta.get("known_bug"), f"{name}: defect scenario missing known_bug"


def test_clean_scenarios_have_no_known_bug():
    for name, meta in SCENARIO_META.items():
        if meta["kind"] == "clean":
            assert not meta.get("known_bug"), \
                f"{name}: clean scenario should not document a bug"


# ---------------------------------------------------------------------------
# 2. _evaluate_outcome — clean scenario
# ---------------------------------------------------------------------------

def _fake_result(status, failure_type=None, metrics=None, logs=None, code=""):
    r = {"status": status, "failure_type": failure_type,
         "metrics": metrics or {}, "logs": logs or [], "code": code}
    return r


class _FakeAgent:
    """Minimal stand-in for outcome evaluation tests."""
    baseline_code = ""
    did_inject = False


def test_evaluate_clean_passes():
    result = _fake_result(
        "success",
        metrics={
            "testsCollected": 5, "testsPassed": 5,
            "testsFailed": 0, "testsErrored": 0, "pytestExitCode": 0,
        },
    )
    matched, reason = _evaluate_outcome(
        "multi-endpoint", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["multi-endpoint"]
    )
    assert matched, reason


def test_evaluate_clean_fails_on_error():
    result = _fake_result(
        "error",
        metrics={
            "testsCollected": 0, "testsPassed": 0,
            "testsFailed": 0, "testsErrored": 1, "pytestExitCode": 2,
        },
    )
    matched, reason = _evaluate_outcome(
        "multi-endpoint", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["multi-endpoint"]
    )
    assert not matched
    assert "status=" in reason


def test_evaluate_clean_fails_on_zero_collected():
    result = _fake_result(
        "success",
        metrics={
            "testsCollected": 0, "testsPassed": 0,
            "testsFailed": 0, "testsErrored": 0, "pytestExitCode": 0,
        },
    )
    matched, _ = _evaluate_outcome(
        "multi-endpoint", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["multi-endpoint"]
    )
    assert not matched


# ---------------------------------------------------------------------------
# 3. _evaluate_outcome — defect scenario
# ---------------------------------------------------------------------------

def test_evaluate_defect_passes():
    result = _fake_result(
        "defect_detected", "assertion_failure",
        metrics={
            "testsCollected": 4, "testsPassed": 1,
            "testsFailed": 3, "testsErrored": 0, "pytestExitCode": 1,
        },
    )
    matched, reason = _evaluate_outcome(
        "inventory-defect", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["inventory-defect"]
    )
    assert matched, reason


def test_evaluate_defect_fails_if_repaired():
    # If repair attempts > 0, a defect scenario should not pass evaluation.
    logs = ["[HEAL] Repair attempt 1/3: sending the generated test..."]
    result = _fake_result(
        "defect_detected", "assertion_failure",
        metrics={
            "testsCollected": 4, "testsPassed": 1,
            "testsFailed": 3, "testsErrored": 0, "pytestExitCode": 1,
        },
        logs=logs,
    )
    matched, reason = _evaluate_outcome(
        "inventory-defect", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["inventory-defect"]
    )
    assert not matched
    assert "attempts=1" in reason


def test_evaluate_defect_fails_when_no_assertion_failures():
    result = _fake_result(
        "defect_detected", "assertion_failure",
        metrics={
            "testsCollected": 4, "testsPassed": 4,
            "testsFailed": 0, "testsErrored": 0, "pytestExitCode": 0,
        },
    )
    matched, _ = _evaluate_outcome(
        "inventory-defect", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["inventory-defect"]
    )
    assert not matched


# ---------------------------------------------------------------------------
# 4. _evaluate_outcome — app_error scenario
# ---------------------------------------------------------------------------

def test_evaluate_app_error_passes():
    result = _fake_result(
        "failed", "application_error",
        metrics={
            "testsCollected": 0, "testsPassed": 0,
            "testsFailed": 0, "testsErrored": 1, "pytestExitCode": 2,
        },
    )
    matched, reason = _evaluate_outcome(
        "broken-init", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["broken-init"]
    )
    assert matched, reason


def test_evaluate_app_error_fails_on_wrong_exit_code():
    result = _fake_result(
        "failed", "application_error",
        metrics={
            "testsCollected": 0, "testsPassed": 0,
            "testsFailed": 0, "testsErrored": 1, "pytestExitCode": 1,
        },
    )
    matched, _ = _evaluate_outcome(
        "broken-init", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["broken-init"]
    )
    assert not matched


# ---------------------------------------------------------------------------
# 5. _aggregate metrics
# ---------------------------------------------------------------------------

def _make_result(kind, matched, repair_attempts=0, baseline_asserts=0, missing=None):
    r = {
        "scenario": f"test-{kind}",
        "kind": kind,
        "expected_outcome_matched": matched,
        "model_call_count": 2,
        "wall_time_ms": 5000,
        "repair_attempts": repair_attempts,
        "outcome_reason": "pass" if matched else "failed: some reason",
    }
    if kind == "repair":
        r["all_original_assertions_preserved"] = not missing
        r["baseline_assertion_count"] = baseline_asserts
    return r


def test_aggregate_all_pass():
    results = [
        _make_result("clean", True),
        _make_result("defect", True),
        _make_result("app_error", True),
        _make_result("repair", True, repair_attempts=1, baseline_asserts=5, missing=[]),
    ]
    agg = _aggregate(results)
    assert agg["overall_success_rate"] == "4/4"
    assert agg["overall_outcome_match"] == "4/4"
    assert agg["api_classification_accuracy"] == "2/2"
    assert agg["defect_classification_correct"] == "2/2"
    assert agg["known_defect_detection_rate"] == "1/1"
    assert agg["false_positive_count"] == "0/1"
    assert agg["repair_success_rate"] == "1/1"
    assert agg["assertion_preservation_rate"] == "1/1"
    assert agg["total_model_calls"] == 8
    assert agg["failed_or_inconclusive"] == []


def test_aggregate_partial_failure():
    results = [
        _make_result("clean", True),
        _make_result("defect", False),   # wrong defect classification
        _make_result("repair", False, repair_attempts=1, baseline_asserts=3, missing=["x == 1"]),
    ]
    agg = _aggregate(results)
    assert agg["overall_success_rate"] == "1/3"
    assert agg["overall_outcome_match"] == "1/3"
    assert agg["defect_classification_correct"] == "1/2"
    assert agg["api_classification_accuracy"] == "1/2"
    assert agg["known_defect_detection_rate"] == "0/1"
    assert agg["false_positive_count"] == "0/1"
    assert agg["repair_success_rate"] == "0/1"
    assert agg["assertion_preservation_rate"] == "0/1"
    assert len(agg["failed_or_inconclusive"]) == 2


def test_aggregate_no_repair_scenarios():
    results = [_make_result("clean", True), _make_result("defect", True)]
    agg = _aggregate(results)
    assert "n/a" in agg["assertion_preservation_rate"]
    assert agg["repair_success_rate"] == "0/0"


def test_aggregate_app_error_excluded_from_defect_classification():
    # app_error scenarios should not count toward defect_classification_correct
    results = [
        _make_result("app_error", True),
        _make_result("app_error", False),
    ]
    agg = _aggregate(results)
    assert agg["defect_classification_correct"] == "0/0"


# ---------------------------------------------------------------------------
# 6. _markdown_report sanity
# ---------------------------------------------------------------------------

def test_markdown_report_contains_all_scenarios():
    results = [
        {
            "scenario": "multi-endpoint",
            "kind": "clean",
            "description": "desc",
            "known_bug": None,
            "expected_outcome_matched": True,
            "outcome_reason": "pass",
            "status": "success",
            "failure_type": None,
            "diagnosis": None,
            "metrics": {
                "testsCollected": 5, "testsPassed": 5,
                "testsFailed": 0, "testsErrored": 0,
                "pytestExitCode": 0,
            },
            "wall_time_ms": 8000,
            "model_call_count": 1,
            "repair_attempts": 0,
            "model_events": [],
            "docker_runs": [],
            "agent_steps": [],
        }
    ]
    agg = _aggregate(results)
    md = _markdown_report(results, agg, "2026-10-29T15:00:00Z")
    assert "multi-endpoint" in md
    assert "Phase 5 Evaluation" in md
    assert "1/1" in md
    assert "Live evaluation" in md


def test_markdown_report_flags_failure():
    results = [
        {
            "scenario": "inventory-defect",
            "kind": "defect",
            "description": "defect desc",
            "known_bug": "a bug",
            "expected_outcome_matched": False,
            "outcome_reason": "failed: status=success",
            "status": "success",
            "failure_type": None,
            "diagnosis": None,
            "metrics": {},
            "wall_time_ms": 3000,
            "model_call_count": 1,
            "repair_attempts": 0,
            "model_events": [],
            "docker_runs": [],
            "agent_steps": [],
        }
    ]
    agg = _aggregate(results)
    md = _markdown_report(results, agg, "2026-10-29T15:00:00Z")
    assert "❌" in md
    assert "Failed or Inconclusive" in md
    assert "inventory-defect" in md


# ---------------------------------------------------------------------------
# 7. Integration: _run_eval_scenario with fakes (no network/Docker)
# Run via asyncio.run() — pytest-asyncio is not in this project's dependencies.
# ---------------------------------------------------------------------------

def test_run_eval_scenario_clean_success():
    """Fake a passing Docker run for the multi-endpoint clean scenario."""
    import asyncio
    import unittest.mock as mock
    from backend import eval_phase5

    passing_meta = _meta(exit_code=0, collected=8, passed=8)
    raw = sandbox_output(passing_meta, "8 passed in 1.5s")

    sandbox = FakeRecordingSandbox([(True, raw)])
    client = fake_client(model_response(MINIMAL_TEST))
    agent = TestForgeAgent(sandbox=sandbox, client=client)

    with mock.patch.object(eval_phase5, "TestForgeAgent", lambda **kw: agent), \
         mock.patch.object(eval_phase5, "RecordingSandbox", lambda: sandbox):
        result = asyncio.run(eval_phase5._run_eval_scenario("multi-endpoint"))

    assert result["status"] == "success"
    assert result["expected_outcome_matched"] is True
    assert result["kind"] == "clean"
    assert result["model_call_count"] == 1
    assert result["repair_attempts"] == 0


def test_run_eval_scenario_app_error():
    """Fake an application_error result for the broken-init scenario."""
    import asyncio
    import unittest.mock as mock
    from backend import eval_phase5

    error_meta = _meta(
        exit_code=2, collected=0, passed=0, failures=0, errors=1,
        error_type="application_error",
    )
    error_meta["diagnosis"] = {
        "category": "application_error",
        "title": "Application Initialization Error",
        "message": "FastAPI could not initialize.",
        "endpoint_assertions_ran": False,
    }
    raw = sandbox_output(error_meta, "1 error in 0.8s")

    sandbox = FakeRecordingSandbox([(False, raw)])
    client = fake_client(model_response(MINIMAL_TEST))
    agent = TestForgeAgent(sandbox=sandbox, client=client)

    with mock.patch.object(eval_phase5, "TestForgeAgent", lambda **kw: agent), \
         mock.patch.object(eval_phase5, "RecordingSandbox", lambda: sandbox):
        result = asyncio.run(eval_phase5._run_eval_scenario("broken-init"))

    assert result["status"] == "failed"
    assert result["failure_type"] == "application_error"
    assert result["expected_outcome_matched"] is True


# ---------------------------------------------------------------------------
# 8. Phase 6 Expansion: Pagination Boundary & Input Validation Defect Tests
# ---------------------------------------------------------------------------

def test_pagination_boundary_defect_metadata():
    meta = SCENARIO_META.get("pagination-boundary-defect")
    assert meta is not None, "pagination-boundary-defect must be registered"
    assert meta["kind"] == "defect"
    assert meta["known_bug"]
    assert "start = page * size" in meta["source"]
    assert "page: int = Query(1, ge=1" in meta["source"]


def test_input_validation_defect_metadata():
    meta = SCENARIO_META.get("input-validation-defect")
    assert meta is not None, "input-validation-defect must be registered"
    assert meta["kind"] == "defect"
    assert meta["known_bug"]
    assert "quantity: int" in meta["source"]
    assert "quantity <= 0" in meta["description"]


def test_evaluate_pagination_boundary_defect_success():
    result = _fake_result(
        "defect_detected", "assertion_failure",
        metrics={
            "testsCollected": 10, "testsPassed": 6,
            "testsFailed": 4, "testsErrored": 0, "pytestExitCode": 1,
        },
    )
    matched, reason = _evaluate_outcome(
        "pagination-boundary-defect", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["pagination-boundary-defect"]
    )
    assert matched, reason


def test_evaluate_pagination_boundary_defect_fails_on_clean_verdict():
    result = _fake_result(
        "success", None,
        metrics={
            "testsCollected": 10, "testsPassed": 10,
            "testsFailed": 0, "testsErrored": 0, "pytestExitCode": 0,
        },
    )
    matched, reason = _evaluate_outcome(
        "pagination-boundary-defect", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["pagination-boundary-defect"]
    )
    assert not matched
    assert "expected defect_detected" in reason

def test_evaluate_input_validation_defect_success():
    result = _fake_result(
        "defect_detected", "assertion_failure",
        metrics={
            "testsCollected": 8, "testsPassed": 5,
            "testsFailed": 3, "testsErrored": 0, "pytestExitCode": 1,
        },
    )
    matched, reason = _evaluate_outcome(
        "input-validation-defect", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["input-validation-defect"]
    )
    assert matched, reason


def test_evaluate_input_validation_defect_fails_on_clean_verdict():
    result = _fake_result(
        "success", None,
        metrics={
            "testsCollected": 8, "testsPassed": 8,
            "testsFailed": 0, "testsErrored": 0, "pytestExitCode": 0,
        },
    )
    matched, reason = _evaluate_outcome(
        "input-validation-defect", result, FakeRecordingSandbox([]), _FakeAgent(),
        SCENARIO_META["input-validation-defect"]
    )
    assert not matched
    assert "expected defect_detected" in reason
