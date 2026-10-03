"""Framework-independent entities, rules and source positions."""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

DEMO = "演示模式，未连接 AI"
CATEGORIES = {"slides": "课件", "exercises": "练习", "assignments": "作业", "code": "代码", "other": "其他"}
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sql", ".json", ".yaml", ".yml", ".html", ".css", ".ipynb", ".r", ".m"}
CODE_EXTENSIONS = TEXT_EXTENSIONS - {".txt", ".md"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".pptx"}

class StudyError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def new_id():
    return uuid4().hex

def now():
    return datetime.now(timezone.utc).isoformat()

def default_category(extension):
    return "code" if extension in CODE_EXTENSIONS else "slides" if extension == ".pptx" else "other"

@dataclass(frozen=True)
class Course:
    id: str
    name: str
    status: str
    created_at: str

    @classmethod
    def create(cls, name):
        name = name.strip()
        if not name or len(name) > 100:
            raise StudyError("课程名称不能为空，且最多 100 个字符。")
        return cls(new_id(), name, "pending", now())

@dataclass(frozen=True)
class Document:
    id: str
    course_id: str
    name: str
    extension: str
    category: str
    size: int
    sha256: str
    pages: int
    warning: str
    created_at: str

@dataclass(frozen=True)
class ParsedDocument:
    pages: list[str]
    warning: str = ""

@dataclass(frozen=True)
class Source:
    document_id: str
    page_start: int
    page_end: int

    def validate(self, document, course_id):
        if document["course_id"] != course_id:
            raise StudyError("资料不属于当前课程。")
        if not 1 <= self.page_start <= self.page_end <= document["pages"]:
            raise StudyError("来源页码超出范围。")

    def snapshot(self, document):
        return {"document_id": self.document_id, "name": document["name"],
                "page_start": self.page_start, "page_end": self.page_end}

@dataclass(frozen=True)
class Message:
    id: str
    course_id: str
    document_id: str | None
    name: str
    role: str
    content: str
    page_start: int
    page_end: int
    selected_text: str
    action: str
    created_at: str

@dataclass(frozen=True)
class Note:
    id: str
    course_id: str
    document_id: str | None
    name: str
    page_start: int
    page_end: int
    selected_text: str
    body: str
    demo: bool
    created_at: str
