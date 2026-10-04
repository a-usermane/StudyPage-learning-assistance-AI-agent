"""Versioned business additions plus separate internal agent sessions."""
from dataclasses import asdict
from contextlib import closing
import json
import sqlite3
from backend.dp.database import connection
from backend.domain.models import now

AGENT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 page_start INTEGER NOT NULL, page_end INTEGER NOT NULL, line_start INTEGER, line_end INTEGER, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_course ON chunks(course_id,document_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_words USING fts5(id UNINDEXED,text,tokenize='unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_grams USING fts5(id UNINDEXED,text,tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON chunks BEGIN
 INSERT INTO chunks_words(id,text) VALUES(new.id,new.text);
 INSERT INTO chunks_grams(id,text) VALUES(new.id,new.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
 DELETE FROM chunks_words WHERE id=old.id; DELETE FROM chunks_grams WHERE id=old.id; END;
CREATE TABLE IF NOT EXISTS agent_results (
 run_id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 message_id TEXT, mode TEXT NOT NULL, content TEXT NOT NULL, question TEXT NOT NULL, action TEXT NOT NULL,
 source TEXT, citations TEXT NOT NULL, version TEXT NOT NULL, transferred INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS agent_messages (
 message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE, mode TEXT NOT NULL, citations TEXT NOT NULL);
'''

def migrate_agent_schema(path, data_dir):
    with connection(path) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version >= 2:
            return
        backup = data_dir / "backups/agent-v2/library.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as dest:
                db.backup(dest)
        db.executescript("BEGIN IMMEDIATE;" + AGENT_SCHEMA + "PRAGMA user_version=2; COMMIT;")

class SQLiteSessionStore:
    def __init__(self, path):
        self.path = path
        with connection(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(thread_id TEXT PRIMARY KEY,course_id TEXT,action TEXT,messages TEXT,summary TEXT,updated_at TEXT,artifacts TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,course_id TEXT,thread_id TEXT,status TEXT,version TEXT,created_at TEXT,updated_at TEXT);
            ''')
            if 'artifacts' not in {r['name'] for r in db.execute('PRAGMA table_info(sessions)')}:
                db.execute("ALTER TABLE sessions ADD COLUMN artifacts TEXT NOT NULL DEFAULT '{}'")
            db.execute("UPDATE runs SET status='interrupted',updated_at=? WHERE status IN ('queued','running')", (now(),))

    def load(self, thread_id):
        with connection(self.path) as db:
            row = db.execute("SELECT * FROM sessions WHERE thread_id=?", (thread_id,)).fetchone()
            return {"messages": json.loads(row["messages"]), "summary": row["summary"], "artifacts": json.loads(row["artifacts"])} if row else {"messages": [], "summary": "", "artifacts": {}}

    def save(self, thread_id, course_id, action, messages, summary, artifacts=None):
        with connection(self.path) as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?)", (thread_id, course_id, action, json.dumps(messages,ensure_ascii=False),summary,now(),json.dumps(artifacts or {},ensure_ascii=False)))

    def run(self, run_id, course_id, thread_id, status, version):
        with connection(self.path) as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at", (run_id,course_id,thread_id,status,version,now(),now()))

class AgentRecordStore:
    def __init__(self, repository):
        self.repository = repository
        self.path = repository.path

    def save(self, context, content, citations, messages):
        # Display messages, metadata and transfer receipt commit together.
        with connection(self.path) as db:
            for message in messages:
                record = asdict(message)
                db.execute(f"INSERT INTO messages({','.join(record)}) VALUES ({','.join('?' for _ in record)})", tuple(record.values()))
                db.execute("INSERT INTO agent_messages VALUES (?,?,?)", (message.id,context.mode,json.dumps(citations,ensure_ascii=False)))
            db.execute("INSERT INTO agent_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (context.run_id,context.request.course_id,messages[-1].id if messages else None,context.mode,content,context.request.question,
                        context.request.action,json.dumps(context.source,ensure_ascii=False),json.dumps(citations,ensure_ascii=False),context.snapshot.version,int(bool(messages))))

    def transfer(self, course_id, run_id, messages):
        with connection(self.path) as db:
            row = db.execute("SELECT * FROM agent_results WHERE course_id=? AND run_id=?", (course_id,run_id)).fetchone()
            if not row:
                return None
            if not row["transferred"]:
                for message in messages(dict(row)):
                    record = asdict(message)
                    db.execute(f"INSERT INTO messages({','.join(record)}) VALUES ({','.join('?' for _ in record)})", tuple(record.values()))
                    db.execute("INSERT INTO agent_messages VALUES (?,?,?)", (message.id,row["mode"],row["citations"]))
                db.execute("UPDATE agent_results SET transferred=1 WHERE run_id=?", (run_id,))
            return dict(row)
