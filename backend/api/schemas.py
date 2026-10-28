"""HTTP DTOs; domain/service remain independent of Pydantic."""
from typing import Literal
from pydantic import BaseModel, Field

class CourseRequest(BaseModel):
    name: str = Field(max_length=100)

class SourceRequest(BaseModel):
    document_id: str
    page_start: int = Field(ge=1)
    page_end: int | None = Field(default=None, ge=1)
    selected_text: str = Field(default="", max_length=5000)

class AnswerRequest(SourceRequest):
    action: Literal["translate", "explain", "ask", "summary"] = "ask"
    question: str = Field(default="", max_length=2000)

class DemoRequest(AnswerRequest):
    course_id: str

class TextSourceRequest(BaseModel):
    kind: Literal['document', 'message', 'note']
    id: str = Field(min_length=1, max_length=64)
    page_start: int = Field(default=1, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    text_field: Literal['body','selected_text','content'] = 'body'

class NoteRequest(BaseModel):
    run_id: str | None = Field(default=None,max_length=64)
    document_id: str | None = None
    page_start: int = Field(default=1, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    selected_text: str = Field(default='', max_length=5000)
    source: TextSourceRequest | None = None
    body: str = Field(default="", max_length=10000)
    demo: bool = False
