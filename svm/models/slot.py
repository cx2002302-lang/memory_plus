from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional
from .block import MemoryBlock


@dataclass
class MemorySlot:
    id: str
    blocks: Dict[str, MemoryBlock] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, str] = field(default_factory=dict)
