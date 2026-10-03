"""File lifecycle adapter: stage → parse → commit, with deletion compensation."""
import hashlib
from pathlib import Path
from backend.domain.models import StudyError, new_id
from .database import original_path

class LocalFileStore:
    def __init__(self, data_dir, staging_dir):
        self.data_dir = Path(data_dir)
        self.staging_dir = Path(staging_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, stream, limit):
        path = self.staging_dir / (new_id() + ".upload")
        size, digest = 0, hashlib.sha256()
        try:
            with path.open("wb") as output:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise StudyError(f"文件超过 {limit // (1024 * 1024)} MB 上限。", 413)
                    output.write(chunk)
                    digest.update(chunk)
            if not size:
                raise StudyError("文件为空，请选择有内容的资料。")
            return path, size, digest.hexdigest()
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def path(self, document):
        return original_path(self.data_dir, document)

    def commit(self, staged, document):
        target = self.path(document)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.replace(target)

    def discard(self, path):
        path.unlink(missing_ok=True)
        # Prune only the single empty document folder, never recursive data roots.
        if path.name.startswith("original"):
            try:
                path.parent.rmdir()
            except OSError:
                pass

    def quarantine(self, document):
        source = self.path(document)
        if not source.exists():
            return None
        staged = self.staging_dir / (new_id() + ".deleted")
        try:
            source.replace(staged)
        except OSError as error:
            raise StudyError("文件正被占用，请关闭相关阅读程序后重试。", 409) from error
        return staged

    def restore(self, staged, document):
        staged.replace(self.path(document))
