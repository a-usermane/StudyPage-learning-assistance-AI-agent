"""Runtime configuration. All paths derive from the workspace or explicit test root."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cache_dir: Path
    upload_limit: int = 20 * 1024 * 1024

    @classmethod
    def load(cls, data_dir=None):
        return cls(Path(data_dir or os.environ.get("STUDY_DATA_DIR", ROOT / "data")).resolve(),
                   ROOT / ".cache", int(os.environ.get("STUDY_UPLOAD_LIMIT_MB", "20")) * 1024 * 1024)
