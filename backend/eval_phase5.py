"""Phase 5 evaluation: advanced API scenarios and quality metrics.

Opt-in live evaluation for TestForge AI.  Requires real Meta API credentials
and a running Docker daemon.  Pass --live to confirm intentional quota usage.

Reuses RecordingSandbox, FixtureInjectionAgent, _assertions, _model_events,
_agent_steps, and _run_summary from release_verify to avoid duplicating the
Docker execution pipeline.

Usage (from repository root):
    .\\backend\\venv\\Scripts\\python.exe -m backend.eval_phase5 --live all
    .\\backend\\venv\\Scripts\\python.exe -m backend.eval_phase5 --live multi-endpoint
    .\\backend\\venv\\Scripts\\python.exe -m backend.eval_phase5 --live inventory-defect
    .\\backend\\venv\\Scripts\\python.exe -m backend.eval_phase5 --live pagination-validation
    .\\backend\\venv\\Scripts\\python.exe -m backend.eval_phase5 --live repair-import

Reports are written to backend/eval_reports/.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import textwrap
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from backend.agent import MAX_REPAIR_ATTEMPTS, TestForgeAgent
from backend.release_verify import (
    FixtureInjectionAgent,
    RecordingSandbox,
    _assertions,
    _agent_steps,
    _model_events,
    _run_summary,
)


# ---------------------------------------------------------------------------
# Scenario sources
# ---------------------------------------------------------------------------

# Scenario 1: Multiple clean endpoints covering CRUD-like surface.
# Expected: success, >=1 tests collected and all passing, pytest exit 0.
MULTI_ENDPOINT_SOURCE = '''
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Product Catalogue API")

_db: dict[int, dict] = {
    1: {"id": 1, "name": "Widget A", "price": 9.99, "stock": 100},
    2: {"id": 2, "name": "Gadget B", "price": 24.99, "stock": 0},
}
_next_id = 3


class ProductCreate(BaseModel):
    name: str
    price: float
    stock: int = 0


class ProductUpdate(BaseModel):
    price: Optional[float] = None
    stock: Optional[int] = None


@app.get("/products", response_model=list[dict])
def list_products():
    return list(_db.values())


@app.get("/products/{product_id}")
def get_product(product_id: int):
    if product_id not in _db:
        raise HTTPException(status_code=404, detail="Product not found")
    return _db[product_id]


@app.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(product: ProductCreate):
    global _next_id
    item = {"id": _next_id, "name": product.name,
            "price": product.price, "stock": product.stock}
    _db[_next_id] = item
    _next_id += 1
    return item


@app.patch("/products/{product_id}")
def update_product(product_id: int, update: ProductUpdate):
    if product_id not in _db:
        raise HTTPException(status_code=404, detail="Product not found")
    if update.price is not None:
        _db[product_id]["price"] = update.price
    if update.stock is not None:
        _db[product_id]["stock"] = update.stock
    return _db[product_id]


@app.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int):
    if product_id not in _db:
        raise HTTPException(status_code=404, detail="Product not found")
    del _db[product_id]
'''.strip()

# Scenario 2: API with a deliberate, reproducible behavioral defect.
# Bug: discount is applied by subtraction instead of multiplication;
#      a 10% discount on 100.00 produces 90.00 correctly by subtraction
#      only when factor=0.10, but apply_discount(200.00, 0.10) returns
#      199.90 instead of 180.00, so the contract is violated for non-unit
#      inputs.  A well-generated test checking e.g. 200 * (1-0.10) == 180.0
#      should fail and be classified as an API_DEFECT.
# Expected: defect_detected, failure_type=assertion_failure, pytest exit 1,
#           >=1 assertion failures, 0 repair attempts.
INVENTORY_DEFECT_SOURCE = '''
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Inventory Pricing API")


class PriceRequest(BaseModel):
    base_price: float
    discount_pct: float   # 0-100


@app.post("/price/discounted")
def discounted_price(req: PriceRequest):
    # BUG: subtracts pct directly instead of applying it as a fraction.
    # Correct formula: base_price * (1 - discount_pct / 100)
    # Actual result:   base_price - discount_pct
    final = req.base_price - req.discount_pct
    return {"base_price": req.base_price,
            "discount_pct": req.discount_pct,
            "final_price": final}


@app.get("/price/markup")
def markup_price(base: float, factor: float):
    """Return base * factor. This endpoint is correct."""
    return {"result": round(base * factor, 4)}
'''.strip()

# Scenario 3: Pagination + filtering + boundary/invalid-parameter validation.
# All logic is correct.  Expected: success, pytest exit 0.
PAGINATION_VALIDATION_SOURCE = '''
from fastapi import FastAPI, HTTPException, Query
from typing import Optional

app = FastAPI(title="Item Search API")

_items = [{"id": i, "category": "A" if i % 2 == 0 else "B", "value": i * 10}
          for i in range(1, 21)]


@app.get("/items")
def search_items(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(5, ge=1, le=50, description="Items per page"),
    category: Optional[str] = None,
):
    """Return a paginated, optionally filtered slice of items."""
    filtered = _items if category is None else [
        it for it in _items if it["category"] == category
    ]
    start = (page - 1) * size
    end = start + size
    return {
        "page": page,
        "size": size,
        "total": len(filtered),
        "items": filtered[start:end],
    }


@app.get("/items/{item_id}")
def get_item(item_id: int):
    matches = [it for it in _items if it["id"] == item_id]
    if not matches:
        raise HTTPException(status_code=404, detail="Item not found")
    return matches[0]
'''.strip()

# Scenario 4: Repairable test-harness failure via missing-fixture injection.
# Same mechanism as the existing self-heal release check, applied to the
# pagination API.  Expected: test_setup_error on first run, one repair
# attempt, success on rerun, all original assertions preserved.
REPAIR_INJECT_SOURCE = PAGINATION_VALIDATION_SOURCE  # inject into clean API

# Scenario 5: Application initialization error (non-Pydantic request body).
# Expected: application_error, pytest exit 2, 0 collected, 0 assertions ran.
BROKEN_INIT_SOURCE = '''
from fastapi import FastAPI, status

app = FastAPI(title="Bad Init API")


class Order:          # Missing BaseModel — FastAPI cannot use as request body
    item_id: int
    quantity: int


@app.post("/orders", status_code=status.HTTP_201_CREATED)
def create_order(order: Order):
    return {"item_id": order.item_id, "quantity": order.quantity, "status": "created"}
'''.strip()


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

# Each entry: source, expected_kind, description of the known intended behavior
# and, for defect scenarios, what the bug is.
SCENARIO_META: dict[str, dict[str, Any]] = {
    "multi-endpoint": {
        "source": MULTI_ENDPOINT_SOURCE,
        "kind": "clean",
        "description": (
            "Product catalogue with list, get, create, patch, delete endpoints. "
            "All logic is correct.  Expect: status=success, exit 0, >=1 collected."
        ),
        "known_bug": None,
    },
    "inventory-defect": {
        "source": INVENTORY_DEFECT_SOURCE,
        "kind": "defect",
        "description": (
            "Pricing API where /price/discounted subtracts the pct integer directly "
            "(base - pct) instead of applying it as a fraction (base*(1-pct/100)). "
            "A correct test checking e.g. 200*(1-0.10)==180 will fail. "
            "Expect: status=defect_detected, failure_type=assertion_failure, exit 1."
        ),
        "known_bug": (
            "discounted_price returns base_price - discount_pct instead of "
            "base_price * (1 - discount_pct / 100)"
        ),
    },
    "pagination-validation": {
        "source": PAGINATION_VALIDATION_SOURCE,
        "kind": "clean",
        "description": (
            "Item search API with 1-based pagination, size limits, category filter, "
            "and 404 for unknown IDs. All logic is correct. "
            "Expect: status=success, exit 0, >=1 collected."
        ),
        "known_bug": None,
    },
    "repair-import": {
        "source": REPAIR_INJECT_SOURCE,
        "kind": "repair",
        "description": (
            "Pagination API (correct source) with a missing-fixture injected into the "
            "generated test after real model generation.  Expect: test_setup_error on "
            "first run, >=1 repair attempt, success on rerun, all assertions preserved."
        ),
        "known_bug": None,
    },
    "broken-init": {
        "source": BROKEN_INIT_SOURCE,
        "kind": "app_error",
        "description": (
            "Order API where Order does not inherit BaseModel, so FastAPI cannot "
            "mount it as a request-body type. "
            "Expect: status=failed, failure_type=application_error, exit 2, 0 collected."
        ),
        "known_bug": "Order class missing BaseModel inheritance",
    },
}

ALL_SCENARIO_NAMES = list(SCENARIO_META.keys())

# Fixture name injected for the repair scenario (must not shadow the real constant).
_EVAL_INJECTED_FIXTURE = "testforge_eval_missing_fixture"


# ---------------------------------------------------------------------------
# Repair injection agent for the eval scenarios
# ---------------------------------------------------------------------------

class EvalFixtureInjectionAgent(TestForgeAgent):
    """Inject a missing fixture into the first generated suite, then repair normally."""

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
            + f"\n\n\ndef test_eval_injected_setup_error({_EVAL_INJECTED_FIXTURE}):\n"
            + f"    assert {_EVAL_INJECTED_FIXTURE} is not None\n"
        )
        (self.verification_dir / "baseline_test_app.py").write_text(
            self.baseline_code, encoding="utf-8"
        )
        (self.verification_dir / "injected_test_app.py").write_text(
            self.injected_code, encoding="utf-8"
        )
        return self.injected_code


# ---------------------------------------------------------------------------
# Outcome evaluation
# ---------------------------------------------------------------------------

def _evaluate_outcome(
    name: str,
    result: dict[str, Any],
    sandbox: RecordingSandbox,
    agent: TestForgeAgent,
    meta: dict[str, Any],
) -> tuple[bool, str]:
    """Return (expected_matched, explanation)."""
    kind = meta["kind"]
    status = result.get("status")
    metrics = result.get("metrics", {})
    failure_type = result.get("failure_type")
    steps = _agent_steps(result.get("logs", []))
    attempts = sum(s.startswith("[HEAL] Repair attempt ") for s in steps)

    if kind == "clean":
        ok = (
            status == "success"
            and metrics.get("testsCollected", 0) > 0
            and metrics.get("testsPassed", 0) > 0
            and metrics.get("testsFailed", 0) == 0
            and metrics.get("testsErrored", 0) == 0
            and metrics.get("pytestExitCode") == 0
        )
        reason = (
            "pass" if ok else
            f"expected success/exit0/collected>0 but got status={status!r} "
            f"exit={metrics.get('pytestExitCode')} "
            f"collected={metrics.get('testsCollected')} "
            f"failed={metrics.get('testsFailed')} "
            f"errors={metrics.get('testsErrored')}"
        )
        return ok, reason

    if kind == "defect":
        ok = (
            status == "defect_detected"
            and failure_type == "assertion_failure"
            and metrics.get("testsFailed", 0) > 0
            and metrics.get("pytestExitCode") != 0
            and attempts == 0
        )
        reason = (
            "pass" if ok else
            f"expected defect_detected/assertion_failure/failures>0 but got "
            f"status={status!r} failure_type={failure_type!r} "
            f"failed={metrics.get('testsFailed')} attempts={attempts}"
        )
        return ok, reason

    if kind == "app_error":
        ok = (
            status == "failed"
            and failure_type == "application_error"
            and metrics.get("testsCollected", -1) == 0
            and metrics.get("testsFailed", -1) == 0
            and metrics.get("testsErrored", 0) > 0
            and metrics.get("pytestExitCode") == 2
            and attempts == 0
        )
        reason = (
            "pass" if ok else
            f"expected failed/application_error/exit2/0collected but got "
            f"status={status!r} failure_type={failure_type!r} "
            f"collected={metrics.get('testsCollected')} "
            f"exit={metrics.get('pytestExitCode')}"
        )
        return ok, reason

    if kind == "repair":
        is_injector = isinstance(agent, EvalFixtureInjectionAgent)
        baseline = agent.baseline_code if is_injector else ""
        repaired = result.get("code", "")
        before = _assertions(baseline) if baseline else []
        after = _assertions(repaired) if repaired else []
        missing = list((Counter(before) - Counter(after)).elements())
        ok = (
            is_injector
            and agent.did_inject
            and bool(before)
            and not missing
            and status == "success"
            and attempts in range(1, MAX_REPAIR_ATTEMPTS + 1)
            and len(sandbox.runs) >= 2
            and sandbox.runs[0]["metadata"].get("error_type") == "test_setup_error"
            and sandbox.runs[0]["metadata"].get("exit_code") not in (None, 0)
            and sandbox.runs[-1]["passed"]
            and sandbox.runs[-1]["metadata"].get("collected", 0) > 0
            and sandbox.runs[-1]["metadata"].get("passed", 0) > 0
            and sandbox.runs[-1]["metadata"].get("failures", 0) == 0
            and sandbox.runs[-1]["metadata"].get("errors", 0) == 0
            and any(e["purpose"] == "test_repair" for e in _model_events(result.get("logs", [])))
        )
        reason = (
            "pass" if ok else
            f"repair check failed: injected={is_injector and agent.did_inject} "
            f"baseline_asserts={len(before)} missing={missing} "
            f"status={status!r} attempts={attempts} runs={len(sandbox.runs)} "
            f"first_error_type="
            f"{sandbox.runs[0]['metadata'].get('error_type') if sandbox.runs else 'n/a'}"
        )
        return ok, reason

    return False, f"unknown kind={kind!r}"


# ---------------------------------------------------------------------------
# Single scenario runner
# ---------------------------------------------------------------------------

async def _run_eval_scenario(name: str) -> dict[str, Any]:
    meta = SCENARIO_META[name]
    source = meta["source"]
    sandbox = RecordingSandbox()
    tmp_dir = None
    agent: TestForgeAgent | None = None
    report: dict[str, Any] | None = None
    t0 = time.monotonic()

    try:
        if meta["kind"] == "repair":
            tmp_dir = tempfile.TemporaryDirectory(prefix="testforge-eval5-")
            verification_dir = Path(tmp_dir.name)
            agent = EvalFixtureInjectionAgent(
                verification_dir=verification_dir, sandbox=sandbox
            )
        else:
            agent = TestForgeAgent(sandbox=sandbox)

        result = await agent.generate_and_heal(source)
        elapsed_ms = round((time.monotonic() - t0) * 1000)

        logs = result.get("logs", [])
        steps = _agent_steps(logs)
        attempts = sum(s.startswith("[HEAL] Repair attempt ") for s in steps)
        events = _model_events(logs)
        runs = [_run_summary(run) for run in sandbox.runs]
        metrics = result.get("metrics", {})

        # Assertion preservation for repair scenarios
        baseline_assertions: list[str] = []
        repaired_assertions: list[str] = []
        missing_assertions: list[str] = []
        if meta["kind"] == "repair" and isinstance(agent, EvalFixtureInjectionAgent):
            baseline_assertions = _assertions(agent.baseline_code) if agent.baseline_code else []
            repaired_assertions = _assertions(result.get("code", ""))
            missing_assertions = list(
                (Counter(baseline_assertions) - Counter(repaired_assertions)).elements()
            )

        matched, outcome_reason = _evaluate_outcome(name, result, sandbox, agent, meta)

        model_call_count = len(events)

        report = {
            "scenario": name,
            "kind": meta["kind"],
            "description": meta["description"],
            "known_bug": meta["known_bug"],
            "expected_outcome_matched": matched,
            "outcome_reason": outcome_reason,
            "status": result.get("status"),
            "failure_type": result.get("failure_type"),
            "diagnosis": result.get("diagnosis"),
            "metrics": metrics,
            "wall_time_ms": elapsed_ms,
            "model_call_count": model_call_count,
            "repair_attempts": attempts,
            "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
            "model_events": events,
            "agent_steps": steps,
            "docker_runs": runs,
        }

        if meta["kind"] == "repair":
            report.update(
                baseline_assertion_count=len(baseline_assertions),
                repaired_assertion_count=len(repaired_assertions),
                missing_original_assertions=missing_assertions,
                all_original_assertions_preserved=bool(baseline_assertions) and not missing_assertions,
                temporary_workspace_removed=False,
            )

        return report

    finally:
        try:
            if agent is not None:
                await agent.aclose()
        finally:
            if tmp_dir is not None:
                tmp_dir.cleanup()
                if report is not None:
                    report["temporary_workspace_removed"] = not Path(tmp_dir.name).exists()


# ---------------------------------------------------------------------------
# Aggregate metrics and report generation
# ---------------------------------------------------------------------------

def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate metrics across all evaluated scenarios."""
    total = len(results)
    matched = sum(1 for r in results if r.get("expected_outcome_matched"))

    # Defect classification: scenarios where kind is "defect" or "clean" (non-app-error)
    # Denominator: scenarios where kind ∈ {clean, defect} (actual pytest ran).
    # application_error and repair scenarios test different capabilities.
    classifiable = [r for r in results if r["kind"] in ("clean", "defect")]
    defect_correct = sum(1 for r in classifiable if r.get("expected_outcome_matched"))

    # Repair: scenarios of kind "repair"
    repair_scenarios = [r for r in results if r["kind"] == "repair"]
    repair_success = sum(1 for r in repair_scenarios if r.get("expected_outcome_matched"))

    # Assertion preservation: only repair scenarios that attempted repair
    repair_attempted = [
        r for r in repair_scenarios if r.get("repair_attempts", 0) > 0
    ]
    preservation_ok = sum(
        1 for r in repair_attempted
        if r.get("all_original_assertions_preserved", False)
    )

    total_model_calls = sum(r.get("model_call_count", 0) for r in results)
    total_wall_ms = sum(r.get("wall_time_ms", 0) for r in results)

    failed_or_inconclusive = [
        {"scenario": r["scenario"], "reason": r.get("outcome_reason", "")}
        for r in results
        if not r.get("expected_outcome_matched")
    ]

    return {
        "total_scenarios": total,
        "expected_outcome_matched": matched,
        "overall_success_rate": f"{matched}/{total}",
        "defect_classification_correct": f"{defect_correct}/{len(classifiable)}",
        "repair_success_rate": f"{repair_success}/{len(repair_scenarios)}",
        "assertion_preservation_rate": (
            f"{preservation_ok}/{len(repair_attempted)}"
            if repair_attempted else "n/a (no repair attempted)"
        ),
        "total_model_calls": total_model_calls,
        "total_wall_time_ms": total_wall_ms,
        "failed_or_inconclusive": failed_or_inconclusive,
    }


def _markdown_report(
    results: list[dict[str, Any]],
    agg: dict[str, Any],
    run_ts: str,
) -> str:
    lines: list[str] = []

    lines.append("# TestForge AI — Phase 5 Evaluation Report")
    lines.append(f"\n**Run timestamp:** {run_ts}  ")
    lines.append("**Label:** Live evaluation — real Meta API and Docker sandbox.\n")

    lines.append("## Aggregate Results\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Overall scenario success | `{agg['overall_success_rate']}` |")
    lines.append(f"| Defect/clean classification | `{agg['defect_classification_correct']}` |")
    lines.append(f"| Repair success | `{agg['repair_success_rate']}` |")
    lines.append(f"| Assertion preservation | `{agg['assertion_preservation_rate']}` |")
    lines.append(f"| Total model calls | `{agg['total_model_calls']}` |")
    lines.append(f"| Total wall time | `{agg['total_wall_time_ms']} ms` |")

    lines.append("\n## Scenario Details\n")
    for r in results:
        icon = "✅" if r.get("expected_outcome_matched") else "❌"
        lines.append(f"### {icon} `{r['scenario']}` ({r['kind']})\n")
        lines.append(f"**Description:** {r['description']}\n")
        if r.get("known_bug"):
            lines.append(f"**Known bug:** {r['known_bug']}\n")
        lines.append(f"**Outcome matched:** `{r.get('expected_outcome_matched')}`  ")
        lines.append(f"**Reason:** {r.get('outcome_reason', 'n/a')}\n")

        m = r.get("metrics", {})
        lines.append(
            f"| Status | Failure type | Collected | Passed | Failed | Errors | Exit | Wall ms | Model calls | Repairs |"
        )
        lines.append(f"|---|---|---|---|---|---|---|---|---|---|")
        lines.append(
            f"| `{r.get('status')}` | `{r.get('failure_type')}` "
            f"| {m.get('testsCollected', '?')} | {m.get('testsPassed', '?')} "
            f"| {m.get('testsFailed', '?')} | {m.get('testsErrored', '?')} "
            f"| {m.get('pytestExitCode', '?')} "
            f"| {r.get('wall_time_ms', '?')} "
            f"| {r.get('model_call_count', '?')} "
            f"| {r.get('repair_attempts', 0)} |"
        )

        if r["kind"] == "repair":
            lines.append(
                f"\n**Baseline assertions:** {r.get('baseline_assertion_count', '?')}  "
            )
            lines.append(
                f"**Repaired assertions:** {r.get('repaired_assertion_count', '?')}  "
            )
            lines.append(
                f"**All preserved:** `{r.get('all_original_assertions_preserved', False)}`  "
            )
            lines.append(
                f"**Workspace removed:** `{r.get('temporary_workspace_removed', False)}`"
            )

        events = r.get("model_events", [])
        if events:
            lines.append("\n**Model events:**")
            for e in events:
                lines.append(
                    f"- purpose=`{e['purpose']}` returned=`{e['returned_model']}` "
                    f"request_id=`{e['request_id']}` outcome=`{e['outcome']}`"
                )

        docker_runs = r.get("docker_runs", [])
        if docker_runs:
            lines.append("\n**Docker runs:**")
            for i, dr in enumerate(docker_runs, 1):
                ev = "  ".join(dr.get("evidence", []))
                lines.append(
                    f"- Run {i}: passed=`{dr['passed']}` "
                    f"exit=`{dr.get('pytest_exit_code')}` "
                    f"collected={dr.get('collected')} "
                    f"passed={dr.get('passed_count')} "
                    f"failed={dr.get('failed_count')} "
                    f"errors={dr.get('errors')}  "
                    f"evidence: _{ev}_"
                )
        lines.append("")

    if agg["failed_or_inconclusive"]:
        lines.append("## Failed or Inconclusive Scenarios\n")
        for f in agg["failed_or_inconclusive"]:
            lines.append(f"- **{f['scenario']}:** {f['reason']}")
        lines.append("")

    lines.append("## Notes\n")
    lines.append(
        "- Defect classification denominator: scenarios of kind `clean` or `defect` only "
        "(excludes `app_error` and `repair` which test different capabilities).\n"
        "- Repair success denominator: scenarios of kind `repair` only.\n"
        "- Assertion preservation denominator: repair scenarios where at least one repair "
        "attempt was made.\n"
        "- Token usage is not reported; the Meta provider does not expose token counts in "
        "the response object used by this SDK.\n"
        "- Wall time includes both model API latency and Docker execution time."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run_selected(names: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    results = []
    for name in names:
        results.append(await _run_eval_scenario(name))
    agg = _aggregate(results)
    run_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return results, agg, run_ts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 5 live evaluation for TestForge AI. "
            "Makes real Meta API requests and runs Docker containers."
        )
    )
    parser.add_argument(
        "scenario",
        choices=ALL_SCENARIO_NAMES + ["all"],
        help="Scenario to run, or 'all' to run every scenario in sequence.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Required: confirms intentional quota usage for real API calls.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Directory for JSON and Markdown report files (default: backend/eval_reports/).",
    )
    args = parser.parse_args()

    if not args.live:
        parser.error(
            "Real Meta API requests and Docker runs are required. Pass --live to confirm."
        )

    names = ALL_SCENARIO_NAMES if args.scenario == "all" else [args.scenario]

    try:
        results, agg, run_ts = asyncio.run(_run_selected(names))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "eval_phase5_failed",
                    "exception_type": type(exc).__name__,
                    "detail": str(exc)[:400],
                }
            )
        )
        return 1

    # Write reports
    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).parent / "eval_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_safe = run_ts.replace(":", "-")
    scenario_slug = args.scenario.replace(" ", "_")

    json_path = out_dir / f"eval_phase5_{scenario_slug}_{ts_safe}.json"
    md_path = out_dir / f"eval_phase5_{scenario_slug}_{ts_safe}.md"

    payload = {
        "run_timestamp": run_ts,
        "scenarios_run": names,
        "aggregate": agg,
        "results": results,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(
        _markdown_report(results, agg, run_ts), encoding="utf-8"
    )

    # Always print aggregate + JSON to stdout
    print(json.dumps(payload, indent=2))

    success = all(r["expected_outcome_matched"] for r in results)
    print(f"\n{'✅' if success else '❌'} Overall: {agg['overall_success_rate']} scenarios matched expected outcomes.")
    print(f"Reports written to: {json_path}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
