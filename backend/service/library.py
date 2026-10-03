"""Application use cases. No HTTP, SQL, PDF.js or concrete adapter imports."""
from dataclasses import asdict
import logging
from pathlib import PurePosixPath
from backend.domain.models import (CATEGORIES, SUPPORTED_EXTENSIONS, Course, Document,
                                  Message, Note, Source, StudyError, new_id, now)
from backend.domain.ports import LibraryRepository, FileStore, DocumentParser, AnswerProvider

class LibraryService:
    def __init__(self, repository: LibraryRepository, files: FileStore,
                 parser: DocumentParser, answers: AnswerProvider, upload_limit: int):
        self.repository, self.files = repository, files
        self.parser, self.answers = parser, answers
        self.upload_limit = upload_limit

    def create_course(self, name):
        return self.repository.create_course(Course.create(name))

    def import_document(self, course_id, name, category, stream):
        self.repository.course(course_id)
        if category not in CATEGORIES:
            raise StudyError("资料用途无效。")
        name = (name or "未命名").replace("\\", "/").split("/")[-1][:240]
        extension = PurePosixPath(name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise StudyError("不支持此格式。请导入 PDF、PPTX、TXT、Markdown 或常见代码文本。")
        staged = final = None
        committed = False
        try:
            staged, size, digest = self.files.stage(stream, self.upload_limit)
            parsed = self.parser.parse(staged, extension)
            document = Document(new_id(), course_id, name, extension, category, size, digest,
                                len(parsed.pages), parsed.warning, now())
            record = asdict(document)
            final = self.files.path(record)
            self.files.commit(staged, record)
            result = self.repository.add_document(document, parsed.pages)
            committed = True
            return result
        except StudyError:
            raise
        except ValueError as error:
            raise StudyError(str(error)) from error
        except Exception as error:
            logging.exception("Import failed")
            raise StudyError("无法导入文件，可能已损坏、格式不匹配或磁盘写入失败，请检查后重试。") from error
        finally:
            # Committed imports have a DB record; compensation only applies on failure.
            if staged is not None:
                self.files.discard(staged)
            if final is not None and not committed:
                self.files.discard(final)

    def list_courses(self):
        return self.repository.courses()

    def get_course(self, course_id):
        return self.repository.course(course_id)

    def cancel_course(self, course_id):
        self.repository.cancel_pending(course_id)

    def list_documents(self, course_id):
        return self.repository.documents(course_id)

    def history(self, course_id):
        return self.repository.messages(course_id)

    def notes(self, course_id, document_id=None):
        if document_id:
            doc = self.repository.document(document_id)
            Source(document_id, 1, 1).validate(doc, course_id)
        return self.repository.notes(course_id, document_id)

    def remove_note(self, note_id):
        self.repository.delete_note(note_id)

    def source(self, course_id, document_id, page_start, page_end=None):
        self.repository.course(course_id)
        document = self.repository.document(document_id)
        source = Source(document_id, page_start, page_end or page_start)
        source.validate(document, course_id)
        return document, source

    def read_page(self, document_id, page):
        document = self.repository.document(document_id)
        Source(document_id, page, page).validate(document, document["course_id"])
        text = self.repository.page_text(document_id, page, page)
        return {"document_id": document_id, "page": page, "total": document["pages"], "text": text,
                "warning": "本页没有可提取文字，首版不支持 OCR。" if not text.strip() and document["extension"] == ".pdf" else ""}

    def original(self, document_id):
        document = self.repository.document(document_id)
        path = self.files.path(document)
        if not path.is_file():
            raise StudyError("本地原文件缺失，请重新导入。", 404)
        return document, path

    def delete_document(self, document_id):
        document = self.repository.document(document_id)
        staged = self.files.quarantine(document)
        try:
            self.repository.delete_document(document_id)
        except Exception:
            if staged:
                self.files.restore(staged, document)
            raise
        if staged:
            self.files.discard(staged)

    def answer(self, course_id, document_id, page_start, action, selected_text="",
               question="", page_end=None, persist=False):
        selected, question = selected_text.strip(), question.strip()
        if action not in {"translate", "explain", "ask", "summary"}:
            raise StudyError("操作类型无效。")
        if len(selected) > 5000 or len(question) > 2000:
            raise StudyError("选区或问题超过字符上限。")
        if action in {"translate", "explain"} and not selected:
            raise StudyError("请先选择资料中的文字。")
        if action == "ask" and not question:
            raise StudyError("请输入问题。")
        document, source = self.source(course_id, document_id, page_start, page_end)
        # Unselected questions and page previews need just one page. Selected answers
        # use the actual selected text, avoiding concatenating a huge page range.
        context = self.repository.page_text(document_id, page_start, page_start)
        content = self.answers.answer(action, selected, question, context)
        message_id = None
        if persist:
            message_id = new_id()
            label = {"translate": "翻译", "explain": "解释", "ask": question, "summary": "当前页内容预览"}[action]
            common = dict(course_id=course_id, document_id=document_id, name=document["name"],
                          page_start=source.page_start, page_end=source.page_end, selected_text=selected, action=action)
            self.repository.add_messages([
                Message(id=new_id(), role="user", content=label + (f"：{selected}" if selected else ""), created_at=now(), **common),
                Message(id=message_id, role="assistant", content=content, created_at=now(), **common)])
        return {"mode": "demo", "content": content, "citation": source.snapshot(document), "message_id": message_id}

    def save_note(self, course_id, document_id, page_start, selected_text="", body="", demo=False, page_end=None):
        selected, body = selected_text.strip(), body.strip()
        if not selected and not body:
            raise StudyError("笔记不能为空。")
        if len(selected) > 5000 or len(body) > 10000:
            raise StudyError("笔记超过字符上限。")
        document, source = self.source(course_id, document_id, page_start, page_end)
        note = Note(new_id(), course_id, document_id, document["name"], source.page_start,
                    source.page_end, selected, body, demo, now())
        return self.repository.add_note(note)
