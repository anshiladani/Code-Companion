from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.sandbox.executor import execute_python_code

router = APIRouter(prefix="/execution", tags=["Code Sandbox"])


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=20_000)
    language: Literal["python"]


@router.post("/run")
def run_code(payload: ExecutionRequest):
    if not settings.ENABLE_LOCAL_CODE_EXECUTION:
        raise HTTPException(
            status_code=503,
            detail=(
                "Code execution is disabled. Enable it only for trusted, local development; "
                "this runner is not an isolated sandbox."
            ),
        )
    return execute_python_code(payload.code, settings.CODE_EXECUTION_TIMEOUT_SECONDS)
