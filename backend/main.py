from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI()

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
async def generate_tests(payload: CodePayload) -> dict:
    return {
        "status": "success",
        "defect_detected": False,
        "logs": ["Backend connected!"],
        "code": "# Test code will go here",
    }
