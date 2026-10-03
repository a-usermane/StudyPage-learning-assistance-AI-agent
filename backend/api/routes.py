"""HTTP transport and serialization only; all use cases delegate to the service."""
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from backend.config import ROOT
from .schemas import AnswerRequest, CourseRequest, DemoRequest, NoteRequest

router = APIRouter(prefix="/api")

def library(request):
    return request.app.state.library

@router.get("/health")
def health(request: Request):
    settings = request.app.state.settings
    return {"app": "study-local", "mode": "demo", "data_dir": str(settings.data_dir),
            "schema_version": 1, "upload_limit": settings.upload_limit}

@router.get("/courses")
def courses(request: Request):
    return library(request).list_courses()

@router.post("/courses", status_code=201)
def create_course(payload: CourseRequest, request: Request):
    return library(request).create_course(payload.name)

@router.get("/courses/{course_id}")
def course(course_id: str, request: Request):
    return library(request).get_course(course_id)

@router.delete("/courses/{course_id}/pending")
def cancel_course(course_id: str, request: Request):
    library(request).cancel_course(course_id)
    return {"ok": True}

@router.get("/courses/{course_id}/documents")
def documents(course_id: str, request: Request):
    return library(request).list_documents(course_id)

@router.post("/courses/{course_id}/documents", status_code=201)
async def upload(course_id: str, request: Request, file: UploadFile = File(...), category: str = Form("other")):
    try:
        return await run_in_threadpool(library(request).import_document, course_id,
                                      file.filename, category, file.file)
    finally:
        await file.close()

@router.get("/documents/{document_id}/pages/{number}")
def page(document_id: str, number: int, request: Request):
    return library(request).read_page(document_id, number)

@router.get("/documents/{document_id}/original")
def original(document_id: str, request: Request):
    doc, path = library(request).original(document_id)
    pdf = doc["extension"] == ".pdf"
    return FileResponse(path, media_type="application/pdf" if pdf else "application/octet-stream",
                        filename=doc["name"], content_disposition_type="inline" if pdf else "attachment")

@router.delete("/documents/{document_id}")
def delete_document(document_id: str, request: Request):
    library(request).delete_document(document_id)
    return {"ok": True}

@router.post("/demo")
def demo(payload: DemoRequest, request: Request):
    return library(request).answer(**payload.model_dump())

@router.get("/courses/{course_id}/messages")
def messages(course_id: str, request: Request):
    return library(request).history(course_id)

@router.post("/courses/{course_id}/messages", status_code=201)
def send_message(course_id: str, payload: AnswerRequest, request: Request):
    return library(request).answer(course_id=course_id, persist=True, **payload.model_dump())

@router.get("/courses/{course_id}/notes")
def notes(course_id: str, request: Request, document_id: str | None = None):
    return library(request).notes(course_id, document_id)

@router.post("/courses/{course_id}/notes", status_code=201)
def save_note(course_id: str, payload: NoteRequest, request: Request):
    return library(request).save_note(course_id=course_id, **payload.model_dump())

@router.delete("/notes/{note_id}")
def delete_note(note_id: str, request: Request):
    library(request).remove_note(note_id)
    return {"ok": True}

@router.get("/samples")
def samples():
    return [{"name": path.name, "url": "/samples/" + path.name}
            for path in sorted((ROOT / "samples").glob("*")) if path.is_file()]
