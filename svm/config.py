import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


PRESETS = {
    "轻量": 0.10,
    "标准": 0.25,
    "性能": 0.50,
}

DEFAULT_CONFIG_PATH = Path.home() / ".openclaw" / "svm" / "config.yaml"


def _detect_system_memory_mb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(re.search(r"(\d+)", line).group(1))
                    return kb // 1024
    except (FileNotFoundError, IOError, AttributeError):
        pass
    return 8192


@dataclass
class SVMConfig:
    profile: str = "标准"
    max_memory_mb: Optional[int] = None
    data_dir: str = str(Path.home() / ".openclaw" / "svm")
    persistent_db: str = "memory.db"
    default_ttl: Optional[float] = None
    default_weight: float = 0.5
    recall_top_n: int = 10
    recall_max_tokens: int = 4096
    log_level: str = "INFO"
    admission_min_weight: float = 0.1
    admission_pressure_ratio: float = 0.8

    def __post_init__(self):
        if self.max_memory_mb is None:
            ratio = PRESETS.get(self.profile, 0.25)
            total = _detect_system_memory_mb()
            self.max_memory_mb = int(total * ratio)
            self.max_memory_mb = max(64, self.max_memory_mb)

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, self.persistent_db)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "max_memory_mb": self.max_memory_mb,
            "data_dir": self.data_dir,
            "persistent_db": self.persistent_db,
            "default_ttl": self.default_ttl,
            "default_weight": self.default_weight,
            "recall_top_n": self.recall_top_n,
            "recall_max_tokens": self.recall_max_tokens,
            "admission_min_weight": self.admission_min_weight,
            "admission_pressure_ratio": self.admission_pressure_ratio,
        }

    @classmethod
    def load(cls, path: Optional[str] = None) -> "SVMConfig":
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        if config_path.exists():
            if HAS_YAML:
                with open(config_path) as f:
                    data = yaml.safe_load(f) or {}
            else:
                with open(config_path) as f:
                    data = json.load(f)
            return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
        return cls()

    def save(self, path: Optional[str] = None):
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if HAS_YAML:
            with open(config_path, "w") as f:
                yaml.dump(self.to_dict(), f, allow_unicode=True)
        else:
            with open(config_path, "w") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
