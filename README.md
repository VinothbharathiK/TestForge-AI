# TestForge AI

TestForge AI accepts FastAPI source, asks Meta Muse Spark to generate a pytest
suite, runs that suite in an isolated Docker container, and makes up to three
test-repair attempts when pytest identifies a repairable test-harness failure.
The browser UI is in `frontend/`; the API and agent are in `backend/`.

## Windows setup

### Prerequisites

- **Python 3.11 or newer.** The backend suite has been verified with Python
  3.13.14; the disposable pytest runner uses Python 3.11.
- **Node.js 22.12 or newer** (Node 24 is also supported). Vite 8.3.5 accepts
  Node 20.19+ or 22.12+; the frontend has been verified with Node 24.21.0.
- **Docker Desktop for Windows**, using Linux containers. Docker Desktop's
  WSL 2 backend is the recommended default. Follow the [official Windows
  installation guide](https://docs.docker.com/desktop/setup/install/windows-install/).

From PowerShell at the repository root:

```powershell
py -3.11 --version
py -3.11 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install --upgrade pip
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

if (-not (Test-Path backend\.env)) {
    Copy-Item backend\.env.example backend\.env
}
notepad backend\.env

node --version
npm --version
Set-Location frontend
npm ci
Set-Location ..

wsl --version
docker version
```

If the Python launcher has no Python 3.11 installation, install Python 3.11+
and substitute its launcher selector (for example, `py -3.13`). The frontend
lockfile is installed with `npm ci`; do not use `npm install` for a clean-clone
setup unless you intend to update the lockfile.

Docker Desktop must be running and set to Linux containers. The first sandbox
run may need network access to pull the Python base image and install the
trusted runner packages. `docker version` must show both client and server.

### Credentials and configuration

Put the Meta credential in **`backend/.env` only**. `MODEL_API_KEY` is preferred;
`META_API_KEY` remains a backward-compatible fallback. Never add a Meta key to
the frontend, a `VITE_*` variable, source code, screenshots, or logs.

The checked-in `backend/.env.example` contains placeholders and safe defaults.
The agent reads it from `backend/.env` when that file exists, without overriding
environment variables already set by the process.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODEL_API_KEY` | empty | Preferred Meta API credential |
| `META_API_KEY` | empty | Compatibility credential fallback |
| `META_API_BASE_URL` | `https://api.meta.ai/v1` | Meta-compatible API endpoint; `META_BASE_URL` is also accepted |
| `META_MODEL` | `muse-spark-1.3` | Requested model ID |
| `META_API_TIMEOUT_SECONDS` | `60` | Model request timeout |
| `TESTFORGE_CORS_ORIGINS` | localhost ports 3000 and 5173 | Comma-separated explicit browser origins |
| `TESTFORGE_DOCKER_TIMEOUT_SECONDS` | `60` | Container test timeout |
| `TESTFORGE_DOCKER_MEMORY_LIMIT` | `512m` | Container memory limit |
| `TESTFORGE_DOCKER_NANO_CPUS` | `1000000000` | One CPU worth of Docker quota |
| `TESTFORGE_DOCKER_PIDS_LIMIT` | `64` | Maximum container processes |
| `TESTFORGE_MAX_SOURCE_BYTES` | `262144` | Maximum UTF-8 bytes for submitted FastAPI source |
| `TESTFORGE_MAX_TEST_BYTES` | `524288` | Maximum UTF-8 bytes for generated tests |

The default CORS list supports the current Vite port 3000 and the common Vite
port 5173 on `localhost` and `127.0.0.1`. Set `TESTFORGE_CORS_ORIGINS` to the
exact deployed frontend origins before deployment. Wildcard origins are
rejected, and browser credentials are not enabled.

### Start the application

Open two PowerShell terminals from the repository root.

Terminal 1 — FastAPI:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — Vite:

```powershell
Set-Location frontend
npm run dev
```

Open the Vite URL shown in the terminal (currently `http://localhost:3000`).
The browser client calls `http://localhost:8000/generate-tests`.

Activation is optional; commands above call the virtual environment directly.
If PowerShell blocks activation when you choose to activate it, allow scripts
for only the current terminal process, then activate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\backend\.venv\Scripts\Activate.ps1
```

## Verification commands

These commands are deterministic local checks and do not require Meta
credentials or a running Docker daemon; sandbox/API behavior is covered with
fakes in the unit suite.

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
.\backend\.venv\Scripts\python.exe -m py_compile backend\agent.py backend\sandbox.py backend\main.py backend\release_verify.py

Set-Location frontend
npm test
npm run build
Set-Location ..
```

### Optional live release checks

`backend.release_verify` is opt-in and uses the existing agent and real Docker
sandbox. It sends real Meta API requests and can consume API quota. The required
`--live` flag prevents accidental use from a normal test command. Run one case:

```powershell
.\backend\.venv\Scripts\python.exe -m backend.release_verify --live auth-clean
.\backend\.venv\Scripts\python.exe -m backend.release_verify --live checkout-defect
.\backend\.venv\Scripts\python.exe -m backend.release_verify --live invalid-user-register
.\backend\.venv\Scripts\python.exe -m backend.release_verify --live self-heal
```

Or run all four serially with `--live all`. The command prints sanitized model
IDs/request IDs, pytest counts and exit codes; it never prints credentials or
generated test source. The self-heal case saves the real initial suite in a
temporary verification folder, injects a missing fixture into a separate
temporary copy, passes that failure through the existing repair loop, checks
that the original assertions remain in the repaired suite, and removes the
verification files. No production source or preset is edited.

### Phase 5 API evaluation benchmark

`backend.eval_phase5` provides a 5-scenario evaluation benchmark to measure agent performance across realistic FastAPI application patterns:
1. `multi-endpoint`: Clean product catalogue CRUD API (verifies multi-route test synthesis).
2. `inventory-defect`: Pricing API with deliberate arithmetic calculation bug (verifies executed assertion failures and `API_DEFECT` classification without false repairs).
3. `pagination-validation`: Item search with 1-based pagination, page size bounds, category filtering, and 404s (verifies input validation and edge cases).
4. `repair-import`: Ground-truth clean API with a temporary injected missing fixture (verifies bounded self-healing and assertion preservation).
5. `broken-init`: Missing `BaseModel` inheritance (verifies FastAPI initialization error handling without false defect claims).

Run the deterministic evaluation unit tests (no credentials, network, or Docker required):

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_eval_phase5.py -q
```

To run an individual live scenario (requires Meta API credentials, network access, and running Docker; consumes quota):

```powershell
.\backend\.venv\Scripts\python.exe -m backend.eval_phase5 multi-endpoint --live
.\backend\.venv\Scripts\python.exe -m backend.eval_phase5 inventory-defect --live
.\backend\.venv\Scripts\python.exe -m backend.eval_phase5 pagination-validation --live
.\backend\.venv\Scripts\python.exe -m backend.eval_phase5 repair-import --live
.\backend\.venv\Scripts\python.exe -m backend.eval_phase5 broken-init --live
```

Reports are written to `backend/eval_reports/` as both JSON and Markdown summaries. An aggregate verified summary is maintained in `backend/eval_reports/PHASE5_LIVE_SUMMARY.md`.

## Hackathon demo

Run the UI with the commands above and demonstrate these cases:

1. **Auth Route (Clean):** choose `User Auth & Profile (Clean)` and generate.
   A verified pass has a nonzero collected and passed count, no failures or
   errors, pytest exit code 0, and a success status. Agent logs show the
   requested/returned model; technical output shows the pytest summary.
2. **Checkout (Defect):** choose `Payment Checkout (Defect Detected)` and
   generate. A genuine defect requires executed assertion failures, a nonzero
   pytest exit, and `failure_type=assertion_failure`; it should not be inferred
   from a collection or setup error.
3. **Invalid `UserRegister`:** in the Clean source, change
   `class UserRegister(BaseModel):` to `class UserRegister:` and run it. The
   result should be an application initialization error, pytest exit 2, zero
   collected endpoint tests, one collection error, and no repair attempt.
4. **Live self-heal:** run
   `python -m backend.release_verify --live self-heal`. The report should show
   the injected missing-fixture setup error and nonzero first pytest exit, one
   real `test_repair` Meta request, a subsequent Docker pytest pass, preserved
   assertions, and a final exit code 0.

The first three are also available as UI scenarios. The fourth intentionally
uses an isolated verification harness because the UI does not inject test
fixtures. Normal unit tests remain independent of network access, API
credentials, and Docker; only the explicitly selected release checks require
all three.

## Sandbox security boundary

The sandbox runs submitted app source and generated tests only inside a
disposable Docker container; it never falls back to host execution. The
container has networking disabled, runs as UID/GID 65534, drops all Linux
capabilities, enables `no-new-privileges`, uses a read-only root filesystem and
read-only workspace mount, and receives only an explicit minimal environment.
Its writable `/tmp` is a 64 MiB `noexec,nosuid,nodev` tmpfs. Docker limits each
run to 60 seconds, 512 MiB, one CPU, 64 processes, and a 4 MiB local log.
Source and test input limits are 256 KiB and 512 KiB by default. Temporary
workspaces and containers are removed on completion; cancellation waits for
the worker cleanup before deleting its mounted workspace.

These controls reduce exposure; **a Docker container is not an absolute
security guarantee**. A container-runtime or kernel vulnerability, Docker
daemon compromise, or host misconfiguration could cross the boundary. Do not
expose this unauthenticated hackathon service to arbitrary public users or run
hostile multi-tenant workloads without stronger isolation (such as a dedicated
VM/microVM), authentication, rate limits, monitoring, and operational review.
Tests run with no network, so test suites that require external services are
expected to fail or be classified as inconclusive.

## Troubleshooting

- **Docker unavailable / daemon connection error:** start Docker Desktop, use
  Linux containers, check `docker version`, and retry. The backend returns a
  sandbox error; it never executes the suite on the host.
- **PowerShell activation policy:** use the direct virtual-environment Python
  commands above, or the process-scoped policy command; do not change machine
  policy for this project.
- **Missing API credential:** add `MODEL_API_KEY` or `META_API_KEY` to
  `backend/.env`, restart FastAPI, and keep its value out of terminal output.
- **Meta 401/403:** check the credential and configured base URL. **429:**
  check provider quota/rate limits. **Timeout/connection/5xx:** check network,
  provider availability, model access, and `META_API_TIMEOUT_SECONDS`.
- **Runner image build or pull failure:** allow Docker Desktop outbound access
  to Docker Hub and package indexes for the trusted image build. Test
  containers themselves remain network-disabled.
- **Generated test exceeds a size limit:** reduce the submitted source or
  configure a carefully chosen `TESTFORGE_MAX_SOURCE_BYTES` /
  `TESTFORGE_MAX_TEST_BYTES`; larger limits increase memory and prompt costs.
