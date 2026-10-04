"""SQLite schema and crash-retryable legacy migration, before HTTP starts."""
from contextlib import contextmanager, closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from backend.domain.models import StudyError, default_category, new_id, now

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE courses (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','ready')), created_at TEXT NOT NULL);
CREATE TABLE documents (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 name TEXT NOT NULL, extension TEXT NOT NULL, category TEXT NOT NULL,
 size INTEGER NOT NULL, sha256 TEXT NOT NULL, pages INTEGER NOT NULL,
 warning TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE pages (
 document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 number INTEGER NOT NULL, text TEXT NOT NULL, PRIMARY KEY(document_id,number));
CREATE TABLE messages (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 document_id TEXT REFERENCES documents(id) ON DELETE SET NULL, name TEXT NOT NULL,
 role TEXT NOT NULL, content TEXT NOT NULL, page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
 selected_text TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE notes (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 document_id TEXT REFERENCES documents(id) ON DELETE SET NULL, name TEXT NOT NULL,
 page_start INTEGER NOT NULL, page_end INTEGER NOT NULL, selected_text TEXT NOT NULL,
 body TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX documents_course ON documents(course_id,category);
CREATE INDEX messages_course ON messages(course_id,created_at);
CREATE INDEX notes_course ON notes(course_id,created_at);
"""

@contextmanager
def connection(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()

def original_path(data_dir, doc):
    return data_dir / "courses" / doc["course_id"] / "materials" / doc["category"] / doc["id"] / ("original" + doc["extension"])

def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def create_schema(path):
    with connection(path) as db:
        db.executescript(SCHEMA)

def _archive_legacy(data_dir, backup):
    # Renames stay inside this explicitly supplied data root; the snapshot remains immutable.
    legacy = data_dir / "library.db"
    if legacy.exists():
        for suffix in ("", "-wal", "-shm"):
            source = data_dir / ("library.db" + suffix)
            target = backup / ("legacy-source.db" + suffix)
            if source.exists() and not target.exists():
                source.rename(target)
    uploads = data_dir / "uploads"
    if uploads.exists() and not (backup / "uploads").exists():
        uploads.rename(backup / "uploads")

def initialize(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    folder = data_dir / "db"
    folder.mkdir(exist_ok=True)
    target = folder / "library.db"
    backup = data_dir / "backups" / "legacy-v1"
    marker = folder / "migration.json"
    manifest_path = backup / "manifest.json"
    if target.exists():
        with connection(target) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in {1, SCHEMA_VERSION}:
                raise RuntimeError("数据库版本不兼容；请保留数据并检查程序版本。")
        if marker.exists() and manifest_path.exists():
            _archive_legacy(data_dir, backup)
    elif (data_dir / "library.db").exists() or manifest_path.exists():
        migrate_legacy(data_dir, target, backup)
    else:
        staged = folder / "library.creating.db"
        staged.unlink(missing_ok=True)
        create_schema(staged)
        with connection(staged) as db:
            db.execute("PRAGMA user_version=1")
        staged.replace(target)
    from backend.dp.agent_storage import migrate_agent_schema
    migrate_agent_schema(target, data_dir)
    with connection(target) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("DELETE FROM courses WHERE status='pending' AND NOT EXISTS (SELECT 1 FROM documents WHERE course_id=courses.id)")
    return target

def migrate_legacy(data_dir, target, backup):
    backup.mkdir(parents=True, exist_ok=True)
    snapshot = backup / "library.db"
    manifest_path = backup / "manifest.json"
    if not manifest_path.exists():
        temporary_snapshot = backup / "snapshot.tmp.db"
        temporary_snapshot.unlink(missing_ok=True)
        with closing(sqlite3.connect((data_dir / "library.db").as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(temporary_snapshot)) as destination:
                source.backup(destination)
        temporary_snapshot.replace(snapshot)
        with connection(snapshot) as db:
            docs = [dict(row) for row in db.execute("SELECT * FROM documents ORDER BY id")]
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("documents", "pages", "messages", "notes")}
        manifest = {"version": 1, "course_id": new_id(), "created_at": now(), "counts": counts,
                    "files": [{"id": d["id"], "sha256": d["sha256"], "extension": d["extension"],
                               "category": default_category(d["extension"]) if d["extension"] != ".pptx" else "other"} for d in docs]}
        temporary_manifest = backup / "manifest.tmp.json"
        temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_manifest.replace(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in manifest["files"]}
    if len(entries) != len(manifest["files"]):
        raise RuntimeError("迁移清单包含重复资料。")
    staged = target.parent / "library.migrating.db"
    staged.unlink(missing_ok=True)
    create_schema(staged)
    with connection(snapshot) as source, connection(staged) as destination:
        docs = [dict(row) for row in source.execute("SELECT * FROM documents ORDER BY id")]
        if {doc["id"] for doc in docs} != set(entries):
            raise RuntimeError("迁移清单与备份不一致。")
        names = {doc["id"]: doc["name"] for doc in docs}
        course_id = manifest["course_id"]
        if docs:
            destination.execute("INSERT INTO courses VALUES (?,?,?,?)", (course_id, "历史资料", "ready", manifest["created_at"]))
        for doc in docs:
            entry = entries[doc["id"]]
            if entry["sha256"] != doc["sha256"] or entry["extension"] != doc["extension"]:
                raise RuntimeError("迁移清单与备份不一致。")
            doc.update(course_id=course_id, category=entry["category"])
            new_path = original_path(data_dir, doc)
            if not new_path.exists() or file_hash(new_path) != doc["sha256"]:
                old_path = data_dir / "uploads" / (doc["id"] + doc["extension"])
                if not old_path.exists():
                    old_path = backup / "uploads" / (doc["id"] + doc["extension"])
                if not old_path.exists() or file_hash(old_path) != doc["sha256"]:
                    raise RuntimeError(f"迁移失败：原文件缺失或哈希不匹配：{doc['name']}。旧数据和备份已保留。")
                new_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_file = new_path.with_suffix(new_path.suffix + ".migrating")
                shutil.copyfile(old_path, temporary_file)
                if file_hash(temporary_file) != doc["sha256"]:
                    raise RuntimeError("迁移复制校验失败。")
                temporary_file.replace(new_path)
            _insert(destination, "documents", doc)
        for row in source.execute("SELECT * FROM pages"):
            _insert(destination, "pages", dict(row))
        for table in ("messages", "notes"):
            for row in source.execute(f"SELECT * FROM {table} ORDER BY created_at,rowid"):
                record = dict(row)
                record.update(course_id=course_id, name=names[record["document_id"]],
                              page_start=record.pop("page"))
                record["page_end"] = record["page_start"]
                _insert(destination, table, record)
        for table, expected in manifest["counts"].items():
            if destination.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] != expected:
                raise RuntimeError("迁移记录数量校验失败。")
        if destination.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("迁移外键校验失败。")
        destination.execute("PRAGMA user_version=1")
    (target.parent / "migration.json").write_text(json.dumps({"version": 1, "backup": "legacy-v1"}), encoding="utf-8")
    staged.replace(target)
    _archive_legacy(data_dir, backup)

def _insert(db, table, record):
    columns = ",".join(record)
    placeholders = ",".join("?" for _ in record)
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(record.values()))

class SQLiteLibraryRepository:
    def __init__(self, path):
        self.path = Path(path)

    def _one(self, table, identity, label):
        with connection(self.path) as db:
            row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise StudyError(label + "不存在，可能已被删除。", 404)
            return dict(row)

    def course(self, course_id):
        return self._one("courses", course_id, "课程")

    def document(self, document_id):
        return self._one("documents", document_id, "资料")

    def create_course(self, course):
        with connection(self.path) as db:
            _insert(db, "courses", asdict(course))
        return asdict(course)

    def courses(self):
        with connection(self.path) as db:
            return [dict(row) for row in db.execute("SELECT c.*, (SELECT COUNT(*) FROM documents d WHERE d.course_id=c.id) AS document_count FROM courses c WHERE status='ready' ORDER BY created_at DESC,rowid DESC")]

    def cancel_pending(self, course_id):
        with connection(self.path) as db:
            course = db.execute("SELECT status FROM courses WHERE id=?", (course_id,)).fetchone()
            if course and course["status"] != "pending":
                raise StudyError("课程已有资料，不能作为空课程取消。", 409)
            db.execute("DELETE FROM courses WHERE id=? AND status='pending'", (course_id,))

    def documents(self, course_id):
        self.course(course_id)
        with connection(self.path) as db:
            return [dict(row) for row in db.execute("SELECT * FROM documents WHERE course_id=? ORDER BY created_at,rowid", (course_id,))]

    def add_document(self, document, pages):
        with connection(self.path) as db:
            _insert(db, "documents", asdict(document))
            db.executemany("INSERT INTO pages VALUES (?,?,?)", [(document.id, i, text) for i, text in enumerate(pages, 1)])
            db.execute("UPDATE courses SET status='ready' WHERE id=?", (document.course_id,))
            from backend.dp.retrieval import index_document
            index_document(db, document.id)
        return asdict(document)

    def page_text(self, document_id, start, end):
        with connection(self.path) as db:
            return "\n\n".join(row["text"] for row in db.execute("SELECT text FROM pages WHERE document_id=? AND number BETWEEN ? AND ? ORDER BY number", (document_id, start, end)))

    def delete_document(self, document_id):
        with connection(self.path) as db:
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))

    def messages(self, course_id):
        self.course(course_id)
        with connection(self.path) as db:
            import json
            messages = [dict(row) for row in db.execute("SELECT * FROM messages WHERE course_id=? ORDER BY created_at,rowid", (course_id,))]
            for message in messages:
                metadata = db.execute("SELECT * FROM agent_messages WHERE message_id=?", (message["id"],)).fetchone()
                message["mode"] = metadata["mode"] if metadata else "demo"
                message["citations"] = json.loads(metadata["citations"]) if metadata else []
                for citation in message["citations"]:
                    if not db.execute("SELECT 1 FROM documents WHERE id=?",(citation["document_id"],)).fetchone():
                        citation["document_id"] = None
            return messages

    def add_messages(self, messages):
        with connection(self.path) as db:
            for message in messages:
                _insert(db, "messages", asdict(message))

    def notes(self, course_id, document_id=None):
        self.course(course_id)
        with connection(self.path) as db:
            sql = "SELECT * FROM notes WHERE course_id=?"
            params = [course_id]
            if document_id:
                sql += " AND document_id=?"
                params.append(document_id)
            return [dict(row) for row in db.execute(sql + " ORDER BY created_at DESC,rowid DESC", params)]

    def add_note(self, note):
        with connection(self.path) as db:
            _insert(db, "notes", asdict(note))
        return asdict(note)

    def delete_note(self, note_id):
        with connection(self.path) as db:
            if not db.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount:
                raise StudyError("笔记不存在。", 404)
