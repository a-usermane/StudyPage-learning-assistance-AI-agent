"""Framework-neutral text source contracts."""
from dataclasses import dataclass
from typing import Literal, Protocol

@dataclass(frozen=True)
class TextOperationSource:
    kind: Literal['document', 'message', 'note']
    id: str
    page_start: int = 1
    page_end: int | None = None
    start: int | None = None
    end: int | None = None
    text_field: str = 'body'

class OverviewStore(Protocol):
    def load(self, course_id: str) -> dict | None: ...
    def save(self, course_id: str, value: dict, expected_version: str) -> dict: ...
    def run(self, course_id: str, run_id: str, value: dict | None = None) -> dict | None: ...
    def latest(self, course_id: str) -> dict | None: ...
    def cached(self, course_id: str, key: str, value: dict | None = None) -> dict | None: ...

class OverviewGenerator(Protocol):
    async def generate(self, snapshot, course_id, course_name, supplement, pages, manifest, progress) -> dict: ...
