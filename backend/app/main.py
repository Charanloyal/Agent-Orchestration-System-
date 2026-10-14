from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


app = FastAPI(title="Agent Orchestration System API", version="0.1.0")


# Liveness only: reports that the API process is serving requests. It does not check
# dependencies yet because none exist in this milestone.
@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")
