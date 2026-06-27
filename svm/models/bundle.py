from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .block import MemoryBlock


@dataclass
class ContextBundle:
    blocks: List[MemoryBlock] = field(default_factory=list)
    total_tokens: int = 0
    slot_id: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_blocks(
        cls,
        blocks: List[MemoryBlock],
        max_tokens: int = 4096,
        slot_id: Optional[str] = None,
    ) -> "ContextBundle":
        sorted_blocks = sorted(blocks, key=lambda b: b.hot_score, reverse=True)
        selected: List[MemoryBlock] = []
        total = 0
        for block in sorted_blocks:
            tokens = block.estimated_tokens
            if total + tokens > max_tokens:
                continue
            selected.append(block)
            total += tokens
        return cls(blocks=selected, total_tokens=total, slot_id=slot_id)
