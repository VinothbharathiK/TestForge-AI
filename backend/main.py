from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:
    from .agent import TestForgeAgent
except ImportError:  # Support `uvicorn main:app` from inside backend/.
    from agent import TestForgeAgent


app = FastAPI(title="TestForge AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CodePayload(BaseModel):
    code: str


@app.post("/generate-tests")
async def generate_tests(payload: CodePayload):
    """Run Meta generation and Docker verification for supplied FastAPI code."""
    agent = TestForgeAgent()
    try:
        result = await agent.generate_and_heal(payload.code)
    finally:
        await agent.aclose()

    # A completed defect/failure is a valid analysis response. Configuration and
    # infrastructure errors are service errors; clients must also inspect `status`.
    if result.get("status") == "error":
        return JSONResponse(status_code=503, content=result)
    return result
