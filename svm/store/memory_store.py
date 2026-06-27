import sys
import logging
from typing import Callable, Dict, List, Optional, Set
from ..models import MemoryBlock
from ..exceptions import BlockNotFoundError

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(
        self,
        max_bytes: int,
        tenant_id: str = "default",
        on_evict: Optional[Callable[[MemoryBlock], None]] = None,
        admission_min_weight: float = 0.1,
        admission_pressure_ratio: float = 0.8,
    ) -> None:
        self._blocks: Dict[str, MemoryBlock] = {}
        self._slot_index: Dict[str, Set[str]] = {}
        self._tenant_index: Dict[str, Set[str]] = {}
        self._tenant_id = tenant_id
        self._max_bytes = max_bytes
        self._used_bytes = 0
        self._hit_count = 0
        self._miss_count = 0
        self._rejected_count = 0
        self._on_evict = on_evict
        self._admission_min_weight = admission_min_weight
        self._admission_pressure_ratio = admission_pressure_ratio

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def count(self) -> int:
        return len(self._blocks)

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def usage_ratio(self) -> float:
        return self._used_bytes / self._max_bytes if self._max_bytes > 0 else 0.0

    @property
    def hit_rate(self) -> float:
        total = self._hit_count + self._miss_count
        return self._hit_count / total if total > 0 else 0.0

    def store(self, block: MemoryBlock) -> None:
        if self.usage_ratio >= self._admission_pressure_ratio and block.weight < self._admission_min_weight:
            self._rejected_count += 1
            logger.warning(
                f"Memory pressure {self.usage_ratio:.0%} ≥ {self._admission_pressure_ratio:.0%}, "
                f"rejected low-weight ({block.weight} < {self._admission_min_weight}) key={block.key}"
            )
            return

        old_size = 0
        if block.key in self._blocks:
            old_size = self._estimate_size(self._blocks[block.key])

        new_size = self._estimate_size(block)
        needed = new_size - old_size
        if needed > 0:
            self._evict(needed)

        self._blocks[block.key] = block
        self._used_bytes += needed

        if block.slot_id:
            self._slot_index.setdefault(block.slot_id, set()).add(block.key)
        self._tenant_index.setdefault(block.tenant_id, set()).add(block.key)

        logger.debug(f"Stored block key={block.key} slot={block.slot_id} tenant={block.tenant_id}")

    def get(self, key: str) -> Optional[MemoryBlock]:
        block = self._blocks.get(key)
        if block is None:
            self._miss_count += 1
            return None
        if block.is_expired:
            self._miss_count += 1
            self.delete(key)
            return None
        block.touch()
        self._hit_count += 1
        return block

    def delete(self, key: str) -> bool:
        block = self._blocks.pop(key, None)
        if block is None:
            return False
        self._used_bytes -= self._estimate_size(block)
        if block.slot_id and block.slot_id in self._slot_index:
            self._slot_index[block.slot_id].discard(key)
            if not self._slot_index[block.slot_id]:
                del self._slot_index[block.slot_id]
        if block.tenant_id in self._tenant_index:
            self._tenant_index[block.tenant_id].discard(key)
            if not self._tenant_index[block.tenant_id]:
                del self._tenant_index[block.tenant_id]
        logger.debug(f"Deleted block key={key}")
        return True

    def get_slot_blocks(self, slot_id: str, tenant_id: Optional[str] = None) -> List[MemoryBlock]:
        keys = self._slot_index.get(slot_id, set())
        result = []
        for key in list(keys):
            block = self._blocks.get(key)
            if block is None:
                continue
            if block.is_expired:
                continue
            if tenant_id is not None and block.tenant_id != tenant_id:
                continue
            result.append(block)
        return result

    def get_tenant_keys(self, tenant_id: Optional[str] = None) -> Set[str]:
        tid = tenant_id or self._tenant_id
        return self._tenant_index.get(tid, set())

    def search_by_keywords(self, keywords: List[str], tenant_id: Optional[str] = None) -> List[MemoryBlock]:
        tid = tenant_id or self._tenant_id
        tenant_keys = self._tenant_index.get(tid)
        if tenant_keys is None:
            return []
        matched = []
        for key in list(tenant_keys):
            block = self._blocks.get(key)
            if block is None or block.is_expired:
                continue
            text = f"{block.key} {block.value}".lower()
            if any(kw.lower() in text for kw in keywords):
                matched.append(block)
        return matched

    def recall(
        self,
        keywords: Optional[List[str]] = None,
        slot_id: Optional[str] = None,
        top_n: int = 10,
        tenant_id: Optional[str] = None,
    ) -> List[MemoryBlock]:
        tid = tenant_id or self._tenant_id
        candidates: List[MemoryBlock] = []

        if keywords:
            candidates = self.search_by_keywords(keywords, tenant_id=tid)
        if slot_id:
            slot_blocks = self.get_slot_blocks(slot_id, tenant_id=tid)
            if keywords:
                slot_keys = {b.key for b in slot_blocks}
                candidates = [b for b in candidates if b.key in slot_keys]
            else:
                candidates = slot_blocks
        if not keywords and not slot_id:
            tenant_keys = self.get_tenant_keys(tid)
            candidates = [self._blocks[k] for k in tenant_keys if k in self._blocks and not self._blocks[k].is_expired]

        for block in candidates:
            block.touch()
        candidates.sort(key=lambda b: b.hot_score, reverse=True)
        return candidates[:top_n]

    def list_blocks(
        self,
        slot_id: Optional[str] = None,
        include_expired: bool = False,
        tenant_id: Optional[str] = None,
    ) -> List[MemoryBlock]:
        tid = tenant_id or self._tenant_id
        if slot_id:
            blocks = self.get_slot_blocks(slot_id, tenant_id=tid)
        else:
            tenant_keys = self.get_tenant_keys(tid)
            blocks = [self._blocks[k] for k in tenant_keys if k in self._blocks]

        if not include_expired:
            blocks = [b for b in blocks if not b.is_expired]
        return sorted(blocks, key=lambda b: b.created_at, reverse=True)

    def clear(self, tenant_id: Optional[str] = None) -> None:
        if tenant_id:
            keys = list(self._tenant_index.get(tenant_id, set()))
            for k in keys:
                self.delete(k)
        else:
            self._blocks.clear()
            self._slot_index.clear()
            self._tenant_index.clear()
            self._used_bytes = 0
            logger.info("Memory store fully cleared")

    def get_stats(self, tenant_id: Optional[str] = None) -> dict:
        tid = tenant_id or self._tenant_id
        tenant_count = len(self._tenant_index.get(tid, set()))
        return {
            "tenant_id": tid,
            "blocks_count": tenant_count,
            "total_blocks_count": self.count,
            "used_bytes": self._used_bytes,
            "max_bytes": self._max_bytes,
            "usage_ratio": round(self.usage_ratio, 4),
            "hit_rate": round(self.hit_rate, 4),
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "rejected_count": self._rejected_count,
            "admission_min_weight": self._admission_min_weight,
            "admission_pressure_ratio": self._admission_pressure_ratio,
        }

    def _evict(self, needed_bytes: int) -> None:
        if self._used_bytes + needed_bytes <= self._max_bytes:
            return
        evictable = sorted(
            [(b.hot_score, b.last_accessed, key) for key, b in self._blocks.items()],
            key=lambda x: (x[0], x[1]),
        )
        freed = 0
        for score, last_ts, key in evictable:
            if freed >= needed_bytes:
                break
            block = self._blocks[key]
            if self._on_evict and block.zk_note_id is None:
                try:
                    self._on_evict(block)
                except Exception:
                    logger.exception(f"on_evict callback failed for key={key}")
            freed += self._estimate_size(block)
            self.delete(key)
            logger.debug(f"Evicted block key={key} hot_score={score:.3f}")

    def _estimate_size(self, block: MemoryBlock) -> int:
        return sys.getsizeof(block.key) + sys.getsizeof(block.value) + 256

    def load_from_snapshot(self, blocks: List[MemoryBlock]) -> None:
        for block in blocks:
            if block.is_expired:
                continue
            size = self._estimate_size(block)
            if self._used_bytes + size > self._max_bytes:
                logger.warning("Memory full during snapshot load, stopping")
                break
            self._blocks[block.key] = block
            self._used_bytes += size
            if block.slot_id:
                self._slot_index.setdefault(block.slot_id, set()).add(block.key)
            self._tenant_index.setdefault(block.tenant_id, set()).add(block.key)
        logger.info(f"Loaded {len(blocks)} blocks, used {self._used_bytes}/{self._max_bytes} bytes")
