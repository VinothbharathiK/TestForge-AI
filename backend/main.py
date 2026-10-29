import os

from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    from .agent import VALID_TESTING_MODES, TestForgeAgent
except ImportError:  # Support `uvicorn main:app` from inside backend/.
    from agent import VALID_TESTING_MODES, TestForgeAgent


DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def configured_cors_origins(value: str | None = None) -> list[str]:
    """Read explicit browser origins and reject wildcard policy."""
    configured = os.environ.get("TESTFORGE_CORS_ORIGINS") if value is None else value
    if configured is None:
        return list(DEFAULT_CORS_ORIGINS)
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if "*" in origins:
        raise ValueError("TESTFORGE_CORS_ORIGINS must list explicit origins, not '*'.")
    return origins


CORS_ORIGINS = configured_cors_origins()
app = FastAPI(title="TestForge AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST"],
    allow_headers=["content-type"],
)


TestingMode = Literal["standard", "adversarial"]


class CodePayload(BaseModel):
    code: str
    mode: TestingMode = "standard"


@app.post("/generate-tests")
async def generate_tests(payload: CodePayload):
    """Run Meta generation and Docker verification for supplied FastAPI code."""
    agent = TestForgeAgent()
    try:
        result = await agent.generate_and_heal(payload.code, mode=payload.mode)
    finally:
        await agent.aclose()

    # A completed defect/failure is a valid analysis response. Configuration and
    # infrastructure errors are service errors; clients must also inspect `status`.
    if result.get("status") == "error":
        return JSONResponse(status_code=503, content=result)
    return result
