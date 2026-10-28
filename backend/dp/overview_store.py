"""Atomic course overview and resumable job files; no model logic."""
import json
import hashlib
import os
from pathlib import Path
import tempfile
from threading import RLock
from uuid import uuid4
from backend.domain.models import StudyError, now

class LocalOverviewStore:
    def __init__(self, data_dir, cache_dir):
        self.data_dir = Path(data_dir)
        namespace = hashlib.sha256(str(self.data_dir.resolve()).casefold().encode()).hexdigest()[:16]
        self.cache = Path(cache_dir) / 'course-overviews' / namespace
        self.lock = RLock()
        self.cache.mkdir(parents=True,exist_ok=True)
        for path in self.cache.glob('*/runs/*.json'):
            try:
                row = self.read(path)
            except StudyError:
                continue  # A corrupt cached task must not prevent other courses from starting.
            if row and row.get('status') in {'queued','running'}:
                row.update(status='interrupted',detail='服务重启，生成已中断，可重新生成并复用匹配的批次。')
                self.atomic(path,row)

    def path(self, course_id):
        return self.data_dir / 'courses' / course_id / 'context/course-overview.json'

    @staticmethod
    def read(path):
        if not path.exists(): return None
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value,dict): raise ValueError()
            return value
        except (OSError,ValueError): raise StudyError('课程概况文件无法读取，请检查本地文件。',503) from None

    @staticmethod
    def atomic(path, value):
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(value,handle,ensure_ascii=False)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary,path)
        except OSError:
            raise StudyError('课程概况保存失败，请检查磁盘与目录权限。',503) from None
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)

    def load(self, course_id):
        with self.lock: return self.read(self.path(course_id))

    def save(self, course_id, value, expected_version):
        with self.lock:
            old = self.load(course_id) or {}
            if old.get('version','0') != expected_version:
                raise StudyError('课程概况已被修改，请重新载入后操作。',409)
            row = {**value,'version':uuid4().hex,'updated_at':now()}
            self.atomic(self.path(course_id),row)
            return row

    def run(self, course_id, run_id, value=None):
        path = self.cache / course_id / 'runs' / (run_id+'.json')
        if value is not None: self.atomic(path,value)
        return self.read(path)

    def latest(self, course_id):
        paths = list((self.cache / course_id / 'runs').glob('*.json'))
        return self.read(max(paths,key=lambda p:p.stat().st_mtime_ns)) if paths else None

    def cached(self, course_id, key, value=None):
        path = self.cache / course_id / 'batches' / (key+'.json')
        if value is not None: self.atomic(path,value)
        return self.read(path)
