"""Transactional, backed-up source migration preserving all legacy ids."""
import json
import sqlite3
from contextlib import closing
from backend.dp.database import connection

def migrate_text_sources(path, data_dir):
    with connection(path) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] >= 3:
            return
        backup = data_dir / 'backups/text-sources-v3/library.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():
            staged = backup.with_suffix('.creating.db')
            try:
                with closing(sqlite3.connect(staged)) as target:
                    db.backup(target)
                staged.replace(backup)
            finally:
                staged.unlink(missing_ok=True)
        db.execute('BEGIN IMMEDIATE')
        for table in ('messages','notes'):
            db.execute(f"ALTER TABLE {table} ADD COLUMN source_json TEXT NOT NULL DEFAULT 'null'")
            for row in db.execute(f'SELECT * FROM {table}').fetchall():
                source = dict(kind='document',id=row['document_id'],document_id=row['document_id'],
                              name=row['name'],page_start=row['page_start'],page_end=row['page_end'],selected_text=row['selected_text'])
                if row['document_id'] or row['name'] != '课程问答':
                    db.execute(f'UPDATE {table} SET source_json=? WHERE id=?',(json.dumps(source,ensure_ascii=False),row['id']))
        for row in db.execute('SELECT run_id,source FROM agent_results').fetchall():
            source = json.loads(row['source'] or 'null')
            if source and 'kind' not in source:
                source = {**source,'kind':'document','id':source.get('document_id')}
                db.execute('UPDATE agent_results SET source=? WHERE run_id=?',(json.dumps(source,ensure_ascii=False),row['run_id']))
        db.execute('PRAGMA user_version=3')
