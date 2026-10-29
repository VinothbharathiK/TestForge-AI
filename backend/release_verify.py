"""Opt-in live Meta API and Docker release checks; never runs in pytest."""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from backend.agent import MAX_REPAIR_ATTEMPTS, TestForgeAgent
from backend.sandbox import ExecutionSandbox


AUTH_SOURCE = '''from fastapi import FastAPI, status
from pydantic import BaseModel, EmailStr

app = FastAPI(title="User Auth Service")

class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str

@app.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(user: UserRegister):
    return {"message": f"User {user.username} created successfully", "id": 1}
'''

CHECKOUT_SOURCE = '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class CheckoutPayload(BaseModel):
    cart_total: float
    discount_factor: float

@app.post("/api/v1/checkout")
def process_checkout(payload: CheckoutPayload):
    final_price = payload.cart_total / (1.0 - payload.discount_factor)
    return {"amount_charged": final_price}
'''

INVALID_USER_REGISTER_SOURCE = '''from fastapi import FastAPI, status
from pydantic import EmailStr

app = FastAPI(title="User Auth Service")

class UserRegister:
    username: str
    email: EmailStr
    password: str

@app.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(user: UserRegister):
    return {"message": f"User {user.username} created successfully", "id": 1}
'''

INJECTED_FIXTURE = "testforge_release_missing_fixture"
SCENARIOS = {
    "auth-clean": AUTH_SOURCE,
    "checkout-defect": CHECKOUT_SOURCE,
    "invalid-user-register": INVALID_USER_REGISTER_SOURCE,
}


class RecordingSandbox(ExecutionSandbox):
    """Capture summaries while delegating every run to the real Docker sandbox."""

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[dict[str, Any]] = []

    async def run_test_in_docker(self, test_code: str, route_code: str):
        passed, raw_logs = await super().run_test_in_docker(test_code, route_code)
        output, metadata = TestForgeAgent._parse_sandbox_result(raw_logs)
        self.runs.append(
            {
                "passed": passed,
                "test_code": test_code,
                "output": output,
                "metadata": metadata,
            }
        )
        return passed, raw_logs


class FixtureInjectionAgent(TestForgeAgent):
    """Inject one test-only fixture failure after real initial generation."""

    def __init__(self, *, verification_dir: Path, **kwargs: Any) -> None:
        self.verification_dir = verification_dir
        self.did_inject = False
        self.baseline_code = ""
        self.injected_code = ""
        super().__init__(**kwargs)

    def _strip_markdown(self, content: str) -> str:
        generated = TestForgeAgent._strip_markdown(content)
        if self.did_inject:
            return generated

        self.did_inject = True
        self.baseline_code = generated
        self.injected_code = (
            generated.rstrip()
            + f"\n\n\ndef test_testforge_injected_setup_error({INJECTED_FIXTURE}):\n"
            + f"    assert {INJECTED_FIXTURE} is not None\n"
        )
        (self.verification_dir / "baseline_test_app.py").write_text(
            self.baseline_code, encoding="utf-8"
        )
        (self.verification_dir / "injected_test_app.py").write_text(
            self.injected_code, encoding="utf-8"
        )
        return self.injected_code


def _assertions(code: str) -> list[str]:
    return [
        ast.unparse(node.test).strip()
        for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.Assert)
    ]


def _model_events(logs: list[str]) -> list[dict[str, str]]:
    events = []
    pattern = re.compile(
        r"purpose=([^ ]+).*requested_model=([^ ]+).*returned_model=([^ ]+)"
        r".*request_id=([^ ]+).*outcome=([^ ]+)"
    )
    for entry in logs:
        for line in str(entry).splitlines():
            if not line.startswith("[MODEL]"):
                continue
            match = pattern.search(line)
            if match:
                events.append(
                    {
                        "purpose": match.group(1),
                        "requested_model": match.group(2),
                        "returned_model": match.group(3),
                        "request_id": match.group(4),
                        "outcome": match.group(5),
                    }
                )
    return events


def _agent_steps(logs: list[str]) -> list[str]:
    prefixes = ("[AGENT]", "[HEAL]", "[SUCCESS]", "[DEFECT]", "[ERROR]", "[WARN]")
    return [
        line[:500]
        for entry in logs
        for line in str(entry).splitlines()
        if line.startswith(prefixes)
    ]


def _pytest_evidence(run: dict[str, Any]) -> list[str]:
    evidence = []
    for line in run["output"].splitlines():
        if line.lstrip().startswith("<"):
            continue
        if (
            "ERROR at setup" in line
            or INJECTED_FIXTURE in line
            or re.search(r"\d+ (?:passed|failed|error|errors|skipped)", line)
            or "__TESTFORGE_PYTEST_EXIT_CODE__" in line
        ):
            evidence.append(line[:350])
    return evidence[:8]


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    metadata = run["metadata"]
    return {
        "passed": run["passed"],
        "failure_type": metadata.get("error_type"),
        "pytest_exit_code": metadata.get("exit_code"),
        "collected": metadata.get("collected"),
        "passed_count": metadata.get("passed"),
        "failed_count": metadata.get("failures"),
        "errors": metadata.get("errors"),
        "injected_fixture_present": INJECTED_FIXTURE in run["test_code"],
        "evidence": _pytest_evidence(run),
    }


async def _run_scenario(name: str) -> dict[str, Any]:
    sandbox = RecordingSandbox()
    temporary_workspace = None
    verification_dir = None
    agent: TestForgeAgent | None = None
    report: dict[str, Any] | None = None
    try:
        if name == "self-heal":
            temporary_workspace = tempfile.TemporaryDirectory(
                prefix="testforge-release-verify-"
            )
            verification_dir = Path(temporary_workspace.name)
            agent = FixtureInjectionAgent(
                verification_dir=verification_dir, sandbox=sandbox
            )
            source = AUTH_SOURCE
        else:
            agent = TestForgeAgent(sandbox=sandbox)
            source = SCENARIOS[name]

        key_configured = bool(agent.api_key)
        requested_model = agent.model
        result = await agent.generate_and_heal(source)
        if name == "self-heal" and verification_dir is not None:
            (verification_dir / "repaired_test_app.py").write_text(
                result.get("code", ""), encoding="utf-8"
            )
        logs = result.get("logs", [])
        steps = _agent_steps(logs)
        attempts = sum(step.startswith("[HEAL] Repair attempt ") for step in steps)
        events = _model_events(logs)
        runs = [_run_summary(run) for run in sandbox.runs]
        metrics = result.get("metrics", {})
        before: list[str] = []
        after: list[str] = []
        missing: list[str] = []

        if name == "auth-clean":
            expected = (
                result.get("status") == "success"
                and metrics.get("testsCollected", 0) > 0
                and metrics.get("testsPassed", 0) > 0
                and metrics.get("testsFailed", 0) == 0
                and metrics.get("testsErrored", 0) == 0
                and metrics.get("pytestExitCode") == 0
            )
        elif name == "checkout-defect":
            expected = (
                result.get("status") == "defect_detected"
                and result.get("failure_type") == "assertion_failure"
                and metrics.get("testsFailed", 0) > 0
                and metrics.get("pytestExitCode") != 0
                and attempts == 0
            )
        elif name == "invalid-user-register":
            expected = (
                result.get("status") == "failed"
                and result.get("failure_type") == "application_error"
                and metrics.get("testsCollected") == 0
                and metrics.get("testsFailed") == 0
                and metrics.get("testsErrored") > 0
                and metrics.get("pytestExitCode") == 2
                and attempts == 0
            )
        else:
            verifier = agent
            baseline = (
                verifier.baseline_code
                if isinstance(verifier, FixtureInjectionAgent)
                else ""
            )
            repaired = result.get("code", "")
            before = _assertions(baseline) if baseline else []
            after = _assertions(repaired) if repaired else []
            missing = list((Counter(before) - Counter(after)).elements())
            expected = (
                isinstance(verifier, FixtureInjectionAgent)
                and verifier.did_inject
                and bool(before)
                and not missing
                and result.get("status") == "success"
                and attempts in range(1, MAX_REPAIR_ATTEMPTS + 1)
                and len(sandbox.runs) >= 2
                and sandbox.runs[0]["metadata"].get("error_type") == "test_setup_error"
                and sandbox.runs[0]["metadata"].get("exit_code") not in (None, 0)
                and sandbox.runs[-1]["passed"]
                and sandbox.runs[-1]["metadata"].get("collected", 0) > 0
                and sandbox.runs[-1]["metadata"].get("passed", 0) > 0
                and sandbox.runs[-1]["metadata"].get("failures", 0) == 0
                and sandbox.runs[-1]["metadata"].get("errors", 0) == 0
                and any(event["purpose"] == "test_repair" for event in events)
            )

        report = {
            "scenario": name,
            "expected_outcome_matched": expected,
            "key_configured": key_configured,
            "requested_model_config": requested_model,
            "status": result.get("status"),
            "failure_type": result.get("failure_type"),
            "diagnosis": result.get("diagnosis"),
            "metrics": metrics,
            "repair_attempts": attempts,
            "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
            "model_events": events,
            "agent_steps": steps,
            "docker_runs": runs,
        }

        if name == "self-heal":
            report.update(
                baseline_assertions=before,
                repaired_assertions=after,
                missing_original_assertions=missing,
                all_original_assertions_preserved=bool(before) and not missing,
                temporary_workspace_removed=False,
            )
        return report
    finally:
        try:
            if agent is not None:
                await agent.aclose()
        finally:
            if temporary_workspace is not None:
                temporary_workspace.cleanup()
                if report is not None:
                    report["temporary_workspace_removed"] = (
                        verification_dir is not None and not verification_dir.exists()
                    )


async def _run_selected(scenarios: list[str]) -> list[dict[str, Any]]:
    results = []
    for scenario in scenarios:
        results.append(await _run_scenario(scenario))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run opt-in live TestForge release checks. This makes real Meta API "
            "requests and executes tests in Docker."
        )
    )
    parser.add_argument(
        "scenario",
        choices=["auth-clean", "checkout-defect", "invalid-user-register", "self-heal", "all"],
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Confirm that real Meta API requests and Docker runs are intended.",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("live credentials and Docker are required; pass --live to continue")

    scenario_names = (
        ["auth-clean", "checkout-defect", "invalid-user-register", "self-heal"]
        if args.scenario == "all"
        else [args.scenario]
    )
    try:
        results = asyncio.run(_run_selected(scenario_names))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "release_verification_failed",
                    "exception_type": type(exc).__name__,
                }
            )
        )
        return 1
    print(json.dumps({"scenarios": results}, indent=2))
    return 0 if all(result["expected_outcome_matched"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
