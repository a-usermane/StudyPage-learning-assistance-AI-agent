import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from backend.config import ROOT
from backend.domain.models import StudyError
from backend.dp.database import initialize, connection, SQLiteLibraryRepository, original_path
from backend.dp.files import LocalFileStore
from backend.dp.parsers import LocalDocumentParser
from backend.dp.demo import DemoAnswerProvider
from backend.service.library import LibraryService

OLD_SCHEMA = """
CREATE TABLE documents (id TEXT PRIMARY KEY,name TEXT,extension TEXT,size INTEGER,sha256 TEXT,pages INTEGER,warning TEXT,created_at TEXT);
CREATE TABLE pages(document_id TEXT,number INTEGER,text TEXT);
CREATE TABLE messages(id TEXT PRIMARY KEY,document_id TEXT,role TEXT,content TEXT,page INTEGER,selected_text TEXT,action TEXT,created_at TEXT);
CREATE TABLE notes(id TEXT PRIMARY KEY,document_id TEXT,page INTEGER,selected_text TEXT,body TEXT,demo INTEGER,created_at TEXT);
"""

class StorageTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / ".cache" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def legacy(self, missing=False):
        uploads = self.root / "uploads"
        uploads.mkdir()
        doc_id = "a" * 32
        content = b"Gradient descent\nvariable = 1"
        if not missing:
            (uploads / (doc_id + ".py")).write_bytes(content)
        with connection(self.root / "library.db") as db:
            db.executescript(OLD_SCHEMA)
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)", (doc_id, "lesson.py", ".py", len(content), hashlib.sha256(content).hexdigest(), 1, "", "2026-01-01"))
            db.execute("INSERT INTO pages VALUES (?,?,?)", (doc_id, 1, content.decode()))
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)", ("message", doc_id, "assistant", "演示模式", 1, "variable", "ask", "2026-01-01"))
            db.execute("INSERT INTO notes VALUES (?,?,?,?,?,?,?)", ("note", doc_id, 1, "variable", "study", 1, "2026-01-01"))
        return doc_id, content

    def test_migration_preserves_ids_hashes_records_and_is_idempotent(self):
        doc_id, content = self.legacy()
        path = initialize(self.root)
        repo = SQLiteLibraryRepository(path)
        course = repo.courses()[0]
        self.assertEqual(course["name"], "历史资料")
        doc = repo.document(doc_id)
        self.assertEqual(doc["category"], "code")
        self.assertEqual(original_path(self.root, doc).read_bytes(), content)
        self.assertEqual(repo.messages(course["id"])[0]["id"], "message")
        self.assertEqual(repo.notes(course["id"])[0]["page_end"], 1)
        self.assertTrue((self.root / "backups/legacy-v1/uploads" / (doc_id + ".py")).exists())
        initialize(self.root)
        self.assertEqual(len(repo.courses()), 1)
        with connection(path) as db:
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())

    def test_missing_original_blocks_switch_and_retry_recovers(self):
        doc_id, content = self.legacy(missing=True)
        with self.assertRaisesRegex(RuntimeError, "原文件缺失"):
            initialize(self.root)
        self.assertFalse((self.root / "db/library.db").exists())
        self.assertTrue((self.root / "library.db").exists())
        (self.root / "uploads" / (doc_id + ".py")).write_bytes(content)
        path = initialize(self.root)
        self.assertEqual(SQLiteLibraryRepository(path).document(doc_id)["name"], "lesson.py")

    def test_interruption_after_database_switch_resumes_archival(self):
        self.legacy()
        with patch("backend.dp.database._archive_legacy", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                initialize(self.root)
        self.assertTrue((self.root / "db/library.db").exists())
        initialize(self.root)
        self.assertFalse((self.root / "uploads").exists())
        self.assertEqual(len(SQLiteLibraryRepository(self.root / "db/library.db").courses()), 1)

    def test_retry_matches_manifest_by_id_regardless_of_order(self):
        first, content = self.legacy()
        second = "b" * 32
        with connection(self.root / "library.db") as db:
            record = dict(db.execute("SELECT * FROM documents").fetchone())
            record.update(id=second, name="second.py")
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)", tuple(record.values()))
            db.execute("INSERT INTO pages VALUES (?,?,?)", (second, 1, content.decode()))
        # The second original is missing: retry must preserve this snapshot and manifest.
        with self.assertRaisesRegex(RuntimeError, "原文件缺失"):
            initialize(self.root)
        manifest_path = self.root / "backups/legacy-v1/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].reverse()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (self.root / "uploads" / (second + ".py")).write_bytes(content)
        repo = SQLiteLibraryRepository(initialize(self.root))
        self.assertEqual({doc["id"] for doc in repo.documents(repo.courses()[0]["id"])}, {first, second})

    def test_import_failures_and_file_deletion_keep_study_records(self):
        repo = SQLiteLibraryRepository(initialize(self.root))
        files = LocalFileStore(self.root, self.root / "staging")
        service = LibraryService(repo, files, LocalDocumentParser(), DemoAnswerProvider(), 40)
        course = service.create_course("test")
        with self.assertRaises(StudyError):
            service.import_document(course["id"], "broken.pdf", "slides", io.BytesIO(b"not pdf"))
        self.assertEqual(repo.courses(), [])
        self.assertEqual(list(files.staging_dir.iterdir()), [])
        doc = service.import_document(course["id"], "text.txt", "exercises", io.BytesIO(b"Gradient descent"))
        service.answer(course["id"], doc["id"], 1, "ask", question="why", persist=True)
        service.save_note(course["id"], doc["id"], 1, body="study")
        service.delete_document(doc["id"])
        self.assertEqual(len(repo.messages(course["id"])), 2)
        self.assertIsNone(repo.notes(course["id"])[0]["document_id"])
        self.assertFalse(files.path(doc).exists())

    def test_size_limit_cleans_partial_file_and_pending_cleanup(self):
        repo = SQLiteLibraryRepository(initialize(self.root))
        files = LocalFileStore(self.root, self.root / "staging")
        course = LibraryService(repo, files, LocalDocumentParser(), DemoAnswerProvider(), 5).create_course("empty")
        with self.assertRaises(StudyError) as error:
            files.stage(io.BytesIO(b"0123456789"), 5)
        self.assertEqual(error.exception.status, 413)
        self.assertFalse(list(files.staging_dir.iterdir()))
        initialize(self.root)
        with self.assertRaises(StudyError):
            repo.course(course["id"])

if __name__ == "__main__":
    unittest.main()
