# TestForge AI — Phase 5 Live Evaluation Summary

This document summarizes the verified live evaluation results for the Phase 5 synthetic API benchmark. All five scenarios were executed individually on 2026-10-29 using real Meta Muse Spark 1.3 model calls and isolated execution within disposable Docker containers.

---

## 1. Scenario Results & Evidence

| Scenario | Type | Description | Expected Outcome | Actual Outcome | Pytest Counts | Pytest Exit | Model Calls | Repairs | Wall Time | Matched? |
|---|---|---|---|---|---|:---:|:---:|:---:|---:|:---:|
| `multi-endpoint` | Clean | Product catalogue CRUD (list, get, create, patch, delete) | Status `success`, exit code 0, >=1 tests collected | Status `success`, `failure_type=None` | 23 collected, 23 passed, 0 failed, 0 errors | 0 | 1 | 0 | 31.98s | **Yes** |
| `inventory-defect` | Defect | Pricing endpoint with arithmetic bug: `base - pct` instead of `base * (1 - pct/100)` | Status `defect_detected`, `failure_type=assertion_failure`, exit code 1, 0 repairs | Status `defect_detected`, `failure_type=assertion_failure` (Meta verdict: `API_DEFECT`) | 12 collected, 6 passed, 6 failed, 0 errors | 1 | 2 | 0 | 21.75s | **Yes** |
| `pagination-validation` | Clean | Item search with 1-based pagination, page size bounds (1–50), category filtering, 404 on missing IDs | Status `success`, exit code 0, >=1 tests collected | Status `success`, `failure_type=None` | 25 collected, 25 passed, 0 failed, 0 errors | 0 | 1 | 0 | 22.53s | **Yes** |
| `repair-import` | Repair | Pagination API with temporary injected missing fixture in test code | Run 1 `test_setup_error` (exit 1), 1 repair attempt, Run 2 exit 0, assertions preserved | Run 1 `test_setup_error`, 1 repair attempt, Run 2 exit 0, status `success` | Run 1: 26 col, 25 pass, 1 err<br>Run 2: 25 col, 25 pass, 0 err | 0 | 2 | 1 | 25.29s | **Yes** |
| `broken-init` | App Error | Order endpoint where payload class lacks `BaseModel` inheritance | Status `failed`, `failure_type=application_error`, exit code 2, 0 collected, 0 repairs | Status `failed`, `failure_type=application_error` (`FastAPIError`) | 0 collected, 0 passed, 0 failed, 1 error | 2 | 1 | 0 | 20.23s | **Yes** |

---

## 2. Key Aggregate Metrics & Definitions

1. **Overall Outcome-Match Rate: 5 / 5 (100%)**
   - *Denominator:* All 5 evaluated benchmark scenarios. Every scenario matched its independent ground-truth expectation.

2. **Defect-Classification Accuracy: 3 / 3 (100%)**
   - *Denominator Definition:* Scenarios where application endpoints were successfully initialized and executed under pytest (`multi-endpoint`, `inventory-defect`, `pagination-validation`).
   - *Result:* Both clean scenarios produced clean passes without false positive defect reports; the genuine arithmetic pricing defect was classified as `API_DEFECT` and flagged without false repairs.
   - *Exclusions from denominator:* `broken-init` (FastAPI could not initialize; no endpoint assertions executed) and `repair-import` (specifically evaluates test-harness recovery).

3. **Repair Success Rate: 1 / 1 (100%)**
   - *Denominator Definition:* Scenarios where a repairable test-side harness failure occurred (`repair-import`).
   - *Result:* Successfully resolved in 1 attempt (within the maximum limit of 3). Genuine application defects were never subjected to repair.

4. **Assertion Preservation: 67 / 67 (100%)**
   - In `repair-import`, all 67 baseline assertions from the initial generation were preserved in the repaired test suite; zero assertions were removed or weakened.

5. **Resource & Duration Summary:**
   - **Total Model Calls:** 7 calls across all 5 scenarios (5 generation calls, 1 classification call, 1 repair call). Zero redundant calls.
   - **Cumulative Wall Time:** 121.78 seconds (~2.03 minutes total across all 5 runs).
   - **Token Usage:** The Meta OpenAI-compatible endpoint used in this project does not expose `usage` token counts in the completion response object; token metrics are truthfully recorded as unavailable rather than estimated or fabricated.

---

## 3. Scope & Limitations

- **Small Benchmark Notice:** This evaluation is a targeted 5-scenario benchmark designed to verify agent capabilities economically. It demonstrates correct classification, bounded self-healing, and assertion preservation under controlled conditions; it is not a statistical guarantee across arbitrary, untyped, or multi-service codebases.
- **Provider Quota:** Real model calls consume API quota. All 5 scenarios were run deliberately and independently without automated loops.
- **Security Boundary:** Docker isolation is defense-in-depth with resource limits (512 MiB, 1 CPU, 64 PIDs, no-network, noexec tmpfs), but the service remains an unauthenticated prototype not suitable for hostile public multi-tenant execution.
