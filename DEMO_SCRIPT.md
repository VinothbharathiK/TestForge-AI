# TestForge AI — Demo Script & Interview Technical Notes

This guide provides a comprehensive 3–5 minute demonstration sequence and interview-ready technical explanations for **TestForge AI**, an autonomous API test-generation, verification, and self-healing engine.

Every metric, log format, and architectural detail in this document reflects the actual codebase (`backend/agent.py`, `backend/sandbox.py`, `backend/eval_phase5.py`, `frontend/src/`) and verified evaluation reports in `backend/eval_reports/`.

---

## Part 1: Quick-Start Prerequisites & Verified Baseline

### System Status & Baseline Checks
All deterministic local checks pass without requiring network or credentials:
* **Backend Unit Suite**: 64 passed (`pytest backend/tests -q`)
* **Frontend Test Suite**: 10 passed (`npm test` in `frontend/`)
* **Production Build**: Succeeded (`npm run build` in `frontend/`)
* **Evaluation Benchmark**: 7/7 scenarios matched their expected outcomes (`backend/eval_reports/PHASE5_LIVE_SUMMARY.md`)

### Starting Local Services (Windows PowerShell from Repository Root)

1. **Docker Engine**: Docker Desktop running Linux containers (`docker ps` returns 0).
2. **Backend Server** (FastAPI on port 8000):
   ```powershell
   .\backend\venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
   ```
   *(Or activate the virtualenv and run `uvicorn backend.main:app --reload --port 8000`)*
3. **Frontend Server** (Vite on port 3000):
   ```powershell
   Push-Location "frontend"
   npm run dev
   Pop-Location
   ```
4. **Environment Variables**: `backend/.env` configured with `META_API_KEY` (or `MODEL_API_KEY`). No secrets are stored in the frontend or source repository.

---

## Part 2: 3–5 Minute Live Demo Sequence

```
  0:00 ─── Clean Route Generation (auth-clean)
  1:00 ─── Defect Detection & Isolation (checkout-defect)
  2:15 ─── Application Initialization Failure (contract integrity)
  3:15 ─── Autonomous Self-Healing & Assertion Preservation
  4:15 ─── Benchmark Evaluation & Architecture Summary
```

### Step 1: Clean API Route — Synthesis & Docker Verification (0:00 – 1:00)

* **Objective**: Show how the agent parses FastAPI endpoints, prompts Meta Muse Spark 1.3, executes the synthesized suite inside Docker, and truthfully reports a passing outcome.
* **UI Action**:
  1. Click the **"Auth Route (Clean)"** pill in the top navbar (or select `User Auth & Profile (Clean)` from the preset dropdown).
  2. Review the code editor: a standard FastAPI registration endpoint with `UserRegister(BaseModel)` and HTTP 201 status code.
  3. Click **"Generate & Test"** (or press `Ctrl+Enter`).
* **What the Audience Observes**:
  * Status indicator transitions: `Idle` &rarr; `Synthesizing` (purple spinner) &rarr; `Passed` (emerald badge).
  * The terminal log streams in real-time with categorized tags (`[AGENT]`, `[MODEL]`, `[EXEC]`, `[SUCCESS]`).
  * The summary banner reports: `"Pytest exited with code 0 after 13 passing tests."` *(Previously verified release check: 13 passed, exit 0; live counts may vary slightly with model generation).*
  * Switch to the **"Generated Suite"** tab (`test_app.py`): Show syntax-highlighted pytest tests using `TestClient` covering valid registrations, missing fields, invalid email types, and duplicate checks.
  * Demonstrate the **"Copy Code"** and **"Download"** buttons in `TestViewer`.
* **Presenter Talking Points**:
  > *"TestForge AI doesn't just generate text; it verifies executable code. It sent this route to Meta Muse Spark, generated a complete pytest suite, created an ephemeral Linux container with Docker, installed dependencies, and executed pytest. Because pytest reported exit code 0 with all collected tests passing, the UI reports a verified pass."*

---

### Step 2: Real Defect Detection Without Assertion Weakening (1:00 – 2:15)

* **Objective**: Show how the agent handles genuine application bugs. Emphasize that TestForge AI isolates defects rather than modifying tests to force a pass.
* **UI Action**:
  1. Click the **"Checkout (Defect)"** pill in the top navbar.
  2. Point out line 14 in the editor:
     ```python
     final_price = payload.cart_total / (1.0 - payload.discount_factor)
     ```
     Explain that when `discount_factor == 1.0` (100% discount promotion), this triggers an unhandled `ZeroDivisionError` (HTTP 500) rather than a valid price calculation.
  3. Click **"Generate & Test"**.
* **What the Audience Observes**:
  * Status updates to **"Defect Flagged"** (rose pulse badge).
  * Defect Banner displays: `"Defect Detected: API behavior did not satisfy a valid test assertion."`
  * Diagnostic metadata card highlights:
    * `DEFECT TYPE: ZeroDivisionError / HTTP 500`
    * `LOCATION: POST /api/v1/checkout`
    * `AI Recommendation: Guard discount_factor == 1.0 or return HTTP 400 Bad Request`
  * Expand the **"View raw output / traceback"** drawer at the bottom of the log viewer: show how raw pytest stack traces are preserved for technical debugging without cluttering the clean agent activity stream.
  * Click **"Inspect Repro Test"**: Jump directly to `test_app.py` to see the exact failing test assertion that caught the division by zero.
* **Presenter Talking Points**:
  > *"Notice what the agent did NOT do: it did NOT remove the failing test. A naive LLM test generator often modifies or deletes failing assertions until the suite turns green, creating false confidence. TestForge AI compares the executed assertion failure against the source code; when it detects an application bug, it halts, flags the defect, and provides a root-cause recommendation."*

---

### Step 3: Application Initialization Errors vs. API Defects (2:15 – 3:15)

* **Objective**: Demonstrate classification precision. When code cannot even start, the engine does not falsely report an "API Defect" or attempt test repairs.
* **UI Action**:
  1. Select the editor and modify the `UserRegister` class by removing `(BaseModel)` inheritance:
     ```python
     # Invalid: raw Python class, not a Pydantic model
     class UserRegister:
         username: str
         email: EmailStr
         password: str
     ```
  2. Click **"Generate & Test"**.
* **What the Audience Observes**:
  * Status updates to **"Run Incomplete"** (amber banner).
  * Banner headline: **"Application Initialization Error"**.
  * Detailed summary:
    > *"FastAPI could not initialize because the UserRegister declaration is not a valid Pydantic request model. Pytest could not collect the tests, so no endpoint assertions were executed."*
  * Pytest metrics: `Collected: 0`, `Passed: 0`, `Failed assertions: 0`, `Errors: 1`, `Exit code: 2`.
  * Repair attempts: `0 / 3`.
* **Presenter Talking Points**:
  > *"Here, the application failed during module import before any endpoint tests could run. Many test tools would label this an 'API Defect' or enter an endless retry loop trying to fix the test harness. TestForge AI checks whether endpoint assertions actually executed. Since zero endpoint assertions ran, it classifies this as an initialization failure and stops immediately."*

---

### Step 4: Autonomous Self-Healing & Assertion Preservation (3:15 – 4:15)

* **Objective**: Explain how the autonomous repair loop operates when the test harness itself has a defect (e.g., broken fixture, missing import), and verify that repairs never weaken assertions.
* **Presenter Walkthrough**:
  1. Explain the repair loop design:
     * When pytest encounters a `test_setup_error` (fixture failure, invalid import in test code), the agent enters the repair loop (up to 3 attempts).
     * The prompt provides the model with: the original source, previous test code, pytest error output, and explicit instructions to fix the harness while strictly preserving expected-behavior assertions.
  2. Refer to previously verified evaluation evidence (`backend/eval_reports/PHASE5_LIVE_SUMMARY.md`):
     * In the verified `repair-import` scenario, a synthetic missing fixture (`testforge_release_missing_fixture`) caused pytest setup to fail.
     * The agent sent the error to Meta Muse Spark.
     * **Previously Verified Result**: Repaired in **1 attempt**, pytest rerun in Docker achieved **25/25 passed (exit 0)**, and AST verification confirmed **67/67 (100%) original assertions were preserved**.

---

### Step 5: Benchmark Evaluation & Portfolio Summary (4:15 – 5:00)

* **Objective**: Show the reproducible evaluation benchmark and summarize the project.
* **UI / CLI Action**:
  * Point to the repository file: [`backend/eval_reports/PHASE5_LIVE_SUMMARY.md`](file:///backend/eval_reports/PHASE5_LIVE_SUMMARY.md).
  * Show how any reviewer can reproduce the full 7-scenario evaluation benchmark using:
    ```powershell
    .\backend\venv\Scripts\python.exe -m backend.eval_phase5 all --live
    ```
* **Previously Verified Benchmark Results (2026-10-29)**:

| Scenario | Category | Expected Outcome | Actual Recorded Outcome | Status |
| :--- | :--- | :--- | :--- | :--- |
| `multi-endpoint` | Clean API | Clean pass (20+ tests) | 23 passed, exit 0 | Matched |
| `inventory-defect` | Defect | API defect detected | 6 passed, 6 failed, exit 1 | Matched |
| `pagination-validation` | Clean API | Clean pass (20+ tests) | 25 passed, exit 0 | Matched |
| `repair-import` | Setup error | Self-healed in &le;3 tries | Repaired in 1 attempt (25/25 passed) | Matched |
| `broken-init` | App init error | App initialization error | Exit 2, 0 endpoint tests, 0 repairs | Matched |
| `pagination-boundary-defect` | Defect | API defect detected | 6 passed, 7 failed, exit 1 | Matched |
| `input-validation-defect` | Defect | API defect detected | 4 passed, 3 failed, exit 1 | Matched |

*Note: The results above record previously verified live benchmark runs. While new runs with dynamic LLMs will produce slightly varying test counts, the classification verdicts and contract boundaries remain reproducible.*

* **Presenter Concluding Statement**:
  > *"Across 7 live benchmark scenarios, TestForge achieved a 7/7 outcome match rate, 100% defect classification accuracy across executed endpoint suites, 0 false positives, and 100% assertion preservation across repairs. It provides a complete, evidence-based autonomous QA workflow."*

---

## Part 3: Security & Sandboxing Limitations

When discussing TestForge AI in technical interviews or demos, be direct and honest about current prototype boundaries:

1. **Host-Level Container Boundaries**:
   * The Docker sandbox enforces resource constraints: `512 MiB RAM`, `1.0 CPU`, `64 PIDs`, a `60-second execution timeout`, and a `64 MiB noexec tmpfs` mount for `/tmp`.
   * However, running Docker on a shared developer machine or single VM is **not** an air-gapped security boundary. Kernel vulnerabilities or Docker daemon exploits could theoretically compromise the host.
2. **Network Access**:
   * In the current prototype, the container requires outbound internet access at runtime because it runs `pip install` for pytest and FastAPI inside `python:3.11-slim`.
   * **Production Fix**: Build a pre-baked Docker image (`testforge-runner:latest`) with all testing packages pre-installed, and execute containers with `--network none`.
3. **Multi-Tenancy & Abuse**:
   * The FastAPI backend has no authentication, rate limiting, or per-user token quotas. It is designed for single-user local developer workflows and should not be exposed directly to the public internet without an API gateway.

---

## Part 4: Interview-Ready Technical Deep-Dive

Use these structured answers to explain design decisions and trade-offs during technical interviews.

### 1. End-to-End System Architecture

```
[ Developer / Browser UI ]
           │
           │  1. HTTP POST /generate-tests (FastAPI Source)
           ▼
[ FastAPI Backend (backend/main.py) ]
           │
           │  2. TestForgeAgent.generate_and_heal()
           ▼
[ Meta Model API (muse-spark-1.3) ] ── 3. Generated pytest suite ──┐
           ▲                                                        │
           │  4. Repair Prompt (if test setup fails)                ▼
[ Autonomous Decision Engine ] ◄── 5. Pytest XML/Logs ── [ Docker Sandbox ]
           │                                                (ExecutionSandbox)
           │  6. Structured JSON Result
           ▼
[ React 19 Frontend (App.jsx) ]
```

* **Frontend**: React 19 with Vite, Tailwind CSS, Lucide icons, responsive split-screen workbench. Communicates with backend via Axios.
* **Backend**: FastAPI with strict CORS origins, Pydantic request models, payload size limits (256 KiB source, 512 KiB test code).
* **AI Orchestrator**: `TestForgeAgent` wraps the official `AsyncOpenAI` client targeting Meta's API (`muse-spark-1.3`).
* **Sandbox**: `ExecutionSandbox` manages temporary directories, Docker Python SDK containers, timeout monitors, and automatic volume cleanup.

---

### 2. Evidence-Based Failure Classification

#### *Why do we classify failures instead of treating all non-zero exit codes as defects?*

In automated testing, **why** a test failed is as important as the failure itself. Pytest can fail for fundamentally different reasons:

1. **Genuine API Defect** (`failure_type: "assertion_failure"`):
   * *Evidence*: Pytest collected tests (`collected > 0`), executed them, and reported one or more assertion failures (`failures > 0`). Status code was 4xx/5xx or response body failed contract checks.
   * *Action*: Do **not** repair test code. Send failure to Meta for defect review; flag defect in UI.
2. **Application Initialization Error** (`failure_type: "application_error"`):
   * *Evidence*: Pytest exit code 2, `collected == 0`, traceback indicates module import or FastAPI route registration failure (e.g. invalid Pydantic model).
   * *Action*: Refuse to label as API defect because zero endpoint assertions ran. Report application error; do not attempt test repairs.
3. **Test Setup / Harness Error** (`failure_type: "test_setup_error"`):
   * *Evidence*: Pytest collected tests, but failed during fixture resolution, mock setup, or imported a non-existent package.
   * *Action*: Eligible for autonomous repair. Send error traceback back to Meta to fix the test harness.
4. **Inconclusive / Skipped**:
   * *Evidence*: Pytest exit code 5 (no tests collected) or all tests skipped.
   * *Action*: Do not claim success. Report run as inconclusive.

---

### 3. The Self-Healing Loop & Anti-Weakening Guardrails

#### *How does self-healing work, and how do you prevent the AI from cheating?*

* **Bounded Attempts**: Capped at `MAX_REPAIR_ATTEMPTS = 3` to prevent infinite token consumption.
* **Targeted Context**: Unlike naive prompts that only say "fix this", TestForge provides:
  1. The user's original FastAPI route code.
  2. The exact test suite that failed.
  3. The parsed failure category (`test_setup_error` vs `invalid_generated_tests`).
  4. The exact pytest failure log/traceback.
* **Assertion Preservation Guardrail**:
  * The system prompt explicitly instructs: *"Do not weaken or remove meaningful expected-behavior assertions to make a broken application pass."*
  * In verification (`backend/eval_phase5.py`), the test harness parses the Python AST (`ast.walk`) to count and compare `assert` statements before and after repair. If a repair achieves exit code 0 by deleting assertions, the evaluation flags it as a failure.

---

### 4. Benchmark Denominators & Statistical Honesty

#### *Why does the benchmark distinguish between 7/7 overall matches and 5/5 classification accuracy?*

In software evaluation, **denominators matter**. Inflating metrics creates false confidence. TestForge reports distinct, statistically honest metrics:

* **Overall Expected-Outcome Match (7/7, 100%)**:
  * *Denominator*: All 7 benchmark scenarios.
  * *Meaning*: Every scenario behaved exactly as its independently defined ground truth specified (whether that ground truth was a pass, defect, init error, or self-heal).
* **API Classification Accuracy (5/5, 100%)**:
  * *Denominator*: Strictly the 5 scenarios where endpoints actually initialized and ran test assertions (`multi-endpoint`, `inventory-defect`, `pagination-validation`, `pagination-boundary-defect`, `input-validation-defect`).
  * *Why excluded*: `broken-init` and `repair-import` test initialization crashes and harness recovery, not endpoint assertion verdicts.
* **Known-Defect Detection Rate (3/3, 100%)**:
  * *Denominator*: Strictly the 3 intentional defect scenarios.
* **False-Positive Defect Count (0/2, 0%)**:
  * *Denominator*: Strictly the 2 clean API scenarios.
* **Scope Disclosure**: 7 scenarios represent a targeted synthetic benchmark demonstrating system behavior under controlled conditions. It does not establish a universal accuracy claim across all possible arbitrary real-world APIs.

---

### 5. Key Engineering Trade-offs & Future Improvements

| Current Approach | Trade-off / Limitation | Future Production Improvement |
| :--- | :--- | :--- |
| **Real Docker Execution** | Slower (~10–30s per run) due to container startup and `pip install`. | Use pre-baked runner images with warm container pools (e.g., Firecracker microVMs) to achieve sub-second execution. |
| **Synchronous HTTP Request** | Client connection remains open during generation and Docker runs. | Transition to an asynchronous task pattern: `POST /jobs` returns a `job_id`, updates stream over WebSockets/SSE. |
| **Single-File Route Analysis** | Routes must be contained in a single code snippet. | Add multi-file AST repository ingestion to resolve dependencies, database models, and shared routers. |
| **AST Assertion Counting** | Counts number and structure of assertions, but doesn't prove semantic coverage. | Integrate mutation testing (e.g. `mutmut`) to measure whether tests catch deliberate mutations in the API body. |
| **Local SQLite / In-Memory** | Routes cannot easily test persistent state across multiple containers. | Provide containerized database fixtures (Postgres / Redis) via Docker Compose or ephemeral testcontainers. |

---

## Part 5: Demo Quick-Reference Card

Keep this summary visible during a live demo or presentation:

* **Clean Demo**: Click `Auth Route (Clean)` &rarr; `Generate & Test` &rarr; 13 passed, exit 0, view `test_app.py`.
* **Defect Demo**: Click `Checkout (Defect)` &rarr; `Generate & Test` &rarr; `ZeroDivisionError` detected, assertion failure isolated, no repair attempt.
* **Init Error Demo**: Remove `(BaseModel)` from `UserRegister` &rarr; `Generate & Test` &rarr; Application initialization error, exit 2, 0 endpoint assertions executed.
* **Self-Healing Proof**: Reference `repair-import` in `PHASE5_LIVE_SUMMARY.md` &rarr; 1 repair attempt, 25/25 passed, 67/67 assertions preserved.
* **Core Philosophy**: *"Generate executable tests, run them in isolation, trust only real execution evidence, and never weaken assertions to fake a passing result."*
