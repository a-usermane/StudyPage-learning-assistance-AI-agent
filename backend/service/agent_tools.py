"""Course-bound tools and per-run evidence ledger, independent of the agent SDK."""
from backend.domain.models import StudyError

class CourseTools:
    def __init__(self, repository, retriever, request, allowed, max_calls):
        self.repository, self.retriever, self.request = repository, retriever, request
        self.allowed, self.max_calls = set(allowed), max_calls
        self.calls = 0
        self.evidence = {}

    def count(self, name):
        if name not in self.allowed:
            raise StudyError("此功能未开放该工具。")
        self.calls += 1
        if self.calls > self.max_calls:
            raise StudyError("本次工具调用已达到限制，请缩小问题范围。")

    def accept(self, rows, limit=6000):
        result, used = [], 0
        for row in rows:
            if used >= limit:
                break
            row = dict(row)
            original_length = len(row['text'])
            row["text"] = row["text"][:min(2000,limit-used)]
            row['truncated'] = len(row['text']) < original_length
            used += len(row["text"])
            self.evidence[row["id"]] = row
            result.append(row)
        return result

    def current(self):
        r = self.request
        return self.accept(self.retriever.read(r.course_id,r.document_id,r.page_start,r.page_start),3000) if r.document_id else []

    def list_documents(self):
        return [{key: doc[key] for key in ("id", "name", "category", "pages")} for doc in self.repository.documents(self.request.course_id)][:100]

    def search_documents(self, query, document_id=None, scope="current"):
        r = self.request
        if r.action == "explain":
            if document_id and document_id != r.document_id:
                raise StudyError("解释仅允许搜索当前文件。")
            document_id = r.document_id
        elif not document_id and scope != "course":
            document_id = r.document_id
        return self.accept(self.retriever.search(r.course_id,query,document_id,6))

    def read_pages(self, document_id, start, end=None):
        r = self.request
        if r.action == "explain" and document_id != r.document_id:
            raise StudyError("解释仅允许读取当前文件。")
        return self.accept(self.retriever.read(r.course_id,document_id,start,end or start))

    def search_notes(self, query):
        return [{"id": note["id"], "body": note["body"][:1200], "name": note["name"], "kind": "user_note"}
                for note in self.repository.notes(self.request.course_id)
                if query.lower() in (note["body"]+' '+note["selected_text"]).lower()][:6]

    def citations(self, content):
        import re
        ids = list(dict.fromkeys(re.findall(r"\[ref:([a-zA-Z0-9_-]+)\]",content)))
        citations = []
        for key in ids:
            if key not in self.evidence:
                continue
            row = self.retriever.validate(self.request.course_id,key)
            if row:
                citations.append({k:row[k] for k in ("id","document_id","name","page_start","page_end","line_start","line_end")})
        return citations
