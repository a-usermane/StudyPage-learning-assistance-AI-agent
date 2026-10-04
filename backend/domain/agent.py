"""Framework-neutral learning runtime contracts."""
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, TypedDict

class Citation(TypedDict):
    id: str
    document_id: str | None
    name: str
    page_start: int
    page_end: int
    line_start: int | None
    line_end: int | None

class SearchChunk(Citation):
    course_id: str
    text: str

class AgentResult(TypedDict):
    run_id: str
    mode: str
    content: str
    citations: list[Citation]

@dataclass(frozen=True)
class AgentRequest:
    course_id: str
    action: str = "ask"
    question: str = ""
    document_id: str | None = None
    page_start: int = 1
    page_end: int | None = None
    selected_text: str = ""
    session_id: str | None = None
    persist: bool = True
    mode: str | None = None

@dataclass(frozen=True)
class RunEvent:
    type: str
    data: dict = field(default_factory=dict)

@dataclass
class RunContext:
    run_id: str
    thread_id: str
    request: AgentRequest
    snapshot: Any
    profile: dict
    mode: str
    tools: Any
    history: list = field(default_factory=list)
    source: dict | None = None
    prompt: str = ""
    metadata: dict = field(default_factory=dict)

class AgentRunner(Protocol):
    def stream(self, request: AgentRequest, context: RunContext) -> AsyncIterator[RunEvent]: ...

class ModelGateway(Protocol):
    def create(self, model: dict): ...

class Retriever(Protocol):
    def search(self, course_id: str, query: str, document_id: str | None = None, limit: int = 6) -> list[dict]: ...
    def read(self, course_id: str, document_id: str, start: int, end: int) -> list[dict]: ...

class SessionStore(Protocol):
    def load(self, thread_id: str) -> dict: ...
    def save(self, thread_id: str, course_id: str, action: str, messages: list, summary: str, artifacts: dict | None = None): ...
    def run(self, run_id: str, course_id: str, thread_id: str, status: str, version: str): ...

class ProfileRegistry(Protocol):
    def snapshot(self): ...
    def reload(self): ...
