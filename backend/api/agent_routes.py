"""Unified learning HTTP/SSE transport."""
import json
from typing import Literal
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr
from backend.domain.agent import AgentRequest
import asyncio

router = APIRouter(prefix="/api")

class RunRequest(BaseModel):
    action: Literal["ask","translate","explain","summary"] = "ask"
    question: str = Field(default="",max_length=2000)
    document_id: str | None = None
    page_start: int = Field(default=1,ge=1)
    page_end: int | None = Field(default=None,ge=1)
    selected_text: str = Field(default="",max_length=5000)
    session_id: str | None = Field(default=None,max_length=64)
    persist: bool = True
    mode: Literal["demo","live"] | None = None

@router.get("/agent/status")
def status(request: Request):
    return request.app.state.learning.status()

@router.post("/agent/config/reload")
def reload_config(request: Request):
    request.app.state.learning.registry.reload()
    return request.app.state.learning.status()

class CredentialRequest(BaseModel):
    model_id: str
    api_key: SecretStr

@router.post("/agent/credentials")
def save_credentials(payload: CredentialRequest, request: Request):
    return request.app.state.learning.save_api_key(payload.model_id, payload.api_key.get_secret_value())

@router.post("/agent/diagnose")
async def diagnose(request: Request):
    """Explicit user-triggered paid API diagnostic, never run during startup."""
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool
    from backend.dp.agent_runtime import text_of
    learning = request.app.state.learning
    snapshot = learning.registry.snapshot()
    config = snapshot.models[snapshot.profiles["ask"]["model"]]
    model = learning.runner.gateway.create(config)
    @tool
    def diagnostic_ping(value: str) -> str:
        """Echo a test value. Call this tool once for connectivity testing."""
        return value
    result = {}
    async with asyncio.timeout(90):
        for name in ("reply","tools","stream"):
            try:
                if name == "reply":
                    response = await model.ainvoke([HumanMessage(content="Reply with OK.")])
                    result[name] = {"ok":bool(text_of(response))}
                elif name == "tools":
                    response = await model.bind_tools([diagnostic_ping],tool_choice="diagnostic_ping").ainvoke([HumanMessage(content="Call diagnostic_ping with value OK.")])
                    result[name] = {"ok":bool(response.tool_calls)}
                else:
                    count = 0
                    async for chunk in model.astream([HumanMessage(content="Reply with OK.")]):
                        if text_of(chunk): count += 1
                    result[name] = {"ok":count>0,"chunks":count}
            except Exception:
                result[name] = {"ok":False,"detail":"检查接口、模型能力、密钥和网络。"}
    return result

@router.post("/courses/{course_id}/agent/runs")
async def run(course_id: str, payload: RunRequest, request: Request):
    learning = request.app.state.learning
    context = learning.prepare(AgentRequest(course_id=course_id,**payload.model_dump()))
    queue,task = learning.start(context)
    async def stream():
        async for event in learning.events(context,queue,task):
            yield f"event: {event.type}\ndata: {json.dumps(event.data,ensure_ascii=False)}\n\n"
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

@router.post("/courses/{course_id}/agent/runs/{run_id}/cancel")
async def cancel(course_id: str, run_id: str, request: Request):
    return request.app.state.learning.cancel(course_id,run_id)

@router.post("/courses/{course_id}/agent/runs/{run_id}/transfer")
async def transfer(course_id: str, run_id: str, request: Request):
    return await request.app.state.learning.transfer(course_id,run_id)
