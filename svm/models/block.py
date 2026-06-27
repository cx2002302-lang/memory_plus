from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MemoryBlock:
    key: str
    value: str
    created_at: datetime = field(default_factory=datetime.now)
    task_id: Optional[str] = None
    weight: float = 0.5
    ttl: Optional[float] = None
    slot_id: Optional[str] = None
    tenant_id: str = "default"
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    zk_note_id: Optional[str] = None
    synced_at: Optional[datetime] = None

    @property
    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return (datetime.now() - self.created_at).total_seconds() > self.ttl

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.value) // 2)

    @property
    def hot_score(self) -> float:
        age_hours = (datetime.now() - self.created_at).total_seconds() / 3600
        recency = 1.0 / (1.0 + age_hours)
        frequency = 1.0 / (1.0 + self.access_count)
        base = self.weight * 0.5 + recency * 0.3 + frequency * 0.2
        if self.zk_note_id is not None:
            base *= 0.7
        return base

    def touch(self) -> None:
        self.last_accessed = datetime.now()
        self.access_count += 1
