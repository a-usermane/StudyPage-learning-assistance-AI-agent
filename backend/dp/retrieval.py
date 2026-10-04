"""Local lexical retrieval with stable page/line provenance."""
import hashlib
import re
from backend.dp.database import connection
from backend.domain.models import CODE_EXTENSIONS, Source, StudyError

def index_document(db, document_id):
    doc = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    for page in db.execute("SELECT number,text FROM pages WHERE document_id=? ORDER BY number", (document_id,)).fetchall():
        text = page["text"]
        for start in range(0, len(text), 1800):
            part = text[start:start+2000]
            if not part.strip():
                continue
            key = hashlib.sha256(f"{document_id}:{page['number']}:{start}:{part}".encode()).hexdigest()[:24]
            line_start = text[:start].count('\n') + 1 if doc["extension"] in CODE_EXTENSIONS else None
            line_end = line_start + part.count('\n') if line_start else None
            db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)", (key,doc["course_id"],document_id,page["number"],page["number"],line_start,line_end,part))

class SQLiteRetriever:
    def __init__(self, repository):
        self.repository = repository
        self.path = repository.path

    def rebuild(self):
        with connection(self.path) as db:
            for row in db.execute("SELECT id FROM documents WHERE NOT EXISTS(SELECT 1 FROM chunks WHERE document_id=documents.id)").fetchall():
                index_document(db,row["id"])

    def _scope(self, course_id, document_id):
        self.repository.course(course_id)
        if document_id:
            Source(document_id,1,1).validate(self.repository.document(document_id),course_id)

    def search(self, course_id, query, document_id=None, limit=6):
        self._scope(course_id,document_id)
        limit = max(1,min(int(limit),6))
        terms = re.findall(r"[\w]+", query[:500])[:12]
        if not terms:
            return []
        found = {}
        with connection(self.path) as db:
            for table, usable in (("chunks_words",terms),("chunks_grams",[t for t in terms if len(t)>=3])):
                if not usable:
                    continue
                match = ' OR '.join('"' + term.replace('"','""') + '"' for term in usable)
                sql = f"SELECT c.*,d.name FROM {table} f JOIN chunks c ON c.id=f.id JOIN documents d ON d.id=c.document_id WHERE {table} MATCH ? AND c.course_id=?"
                params = [match,course_id]
                if document_id:
                    sql += " AND c.document_id=?"; params.append(document_id)
                for row in db.execute(sql+f" ORDER BY bm25({table}) LIMIT ?", (*params,limit)):
                    found.setdefault(row["id"],dict(row))
            if not found:
                for term in terms[:4]:
                    sql = "SELECT c.*,d.name FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.course_id=? AND instr(lower(c.text),lower(?))>0"
                    params = [course_id,term]
                    if document_id:
                        sql += " AND c.document_id=?"; params.append(document_id)
                    for row in db.execute(sql+" LIMIT ?",(*params,limit)):
                        found.setdefault(row["id"],dict(row))
        return list(found.values())[:limit]

    def read(self, course_id, document_id, start, end):
        doc = self.repository.document(document_id)
        Source(document_id,start,end).validate(doc,course_id)
        if end-start >= 3:
            raise StudyError("每次最多读取 3 页。")
        with connection(self.path) as db:
            return [dict(row) for row in db.execute("SELECT c.*,d.name FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.document_id=? AND c.page_start BETWEEN ? AND ? ORDER BY c.page_start,c.line_start,c.rowid LIMIT 12",(document_id,start,end))]

    def validate(self, course_id, chunk_id):
        with connection(self.path) as db:
            row = db.execute("SELECT c.*,d.name FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=? AND c.course_id=?",(chunk_id,course_id)).fetchone()
            return dict(row) if row else None
