import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

from ..models import MemoryBlock
from ..store.memory_store import MemoryStore
from ..store.persistent import PersistentStore
from .zk_sync import ZKDatabase

logger = logging.getLogger(__name__)

COLD_HOT_SCORE = 0.3
DEFAULT_IDLE_MINUTES = 30
DEFAULT_REFRESH_INTERVAL = 300


class SyncEngine:
    def __init__(
        self,
        memory: MemoryStore,
        zk_db_path: str,
        persistent: Optional[PersistentStore] = None,
        idle_minutes: int = DEFAULT_IDLE_MINUTES,
        tenant_id: str = "default",
    ) -> None:
        self._memory = memory
        self._persistent = persistent
        self._zk = ZKDatabase(zk_db_path)
        self._idle_minutes = idle_minutes
        self._tenant_id = tenant_id
        self._last_activity: Optional[datetime] = None
        self._last_refresh: Optional[datetime] = None

    def record_activity(self) -> None:
        self._last_activity = datetime.now()

    @property
    def is_idle(self) -> bool:
        if self._last_activity is None:
            return False
        elapsed = (datetime.now() - self._last_activity).total_seconds() / 60
        return elapsed >= self._idle_minutes

    def flush_cold_blocks(self, force: bool = False) -> int:
        if not force and not self.is_idle:
            logger.info("Not idle, skipping SVM->ZK flush")
            return 0
        blocks = self._memory.list_blocks(tenant_id=self._tenant_id)
        cold = [b for b in blocks if b.hot_score < COLD_HOT_SCORE and b.zk_note_id is None]
        if not cold:
            logger.info("No cold blocks to flush")
            return 0
        synced = 0
        for block in cold:
            note_id = self._zk.create_note_from_block(block)
            if note_id:
                block.zk_note_id = note_id
                block.synced_at = datetime.now()
                self._memory.store(block)
                if self._persistent:
                    self._persistent.save_block(block)
                synced += 1
        logger.info(f"Flushed {synced}/{len(cold)} cold blocks to ZK")
        return synced

    def hot_load_from_zk(
        self,
        important_days: int = 7,
        recent_days: int = 7,
        evergreen_limit: int = 20,
        max_blocks: int = 100,
    ) -> int:
        loaded = 0
        important = self._zk.load_important_notes(
            days=important_days, limit=max_blocks, tenant_id=self._tenant_id
        )
        for block in important:
            if loaded >= max_blocks:
                break
            existing = self._memory.get(block.key)
            if existing is None:
                self._memory.store(block)
                if self._persistent:
                    self._persistent.save_block(block)
                loaded += 1
        recent = self._zk.load_recent_notes(
            days=recent_days, limit=max_blocks - loaded, tenant_id=self._tenant_id
        )
        for block in recent:
            if loaded >= max_blocks:
                break
            existing = self._memory.get(block.key)
            if existing is None:
                self._memory.store(block)
                if self._persistent:
                    self._persistent.save_block(block)
                loaded += 1
        evergreen = self._zk.load_evergreen_notes(
            limit=max_blocks - loaded, tenant_id=self._tenant_id
        )
        for block in evergreen:
            if loaded >= max_blocks:
                break
            existing = self._memory.get(block.key)
            if existing is None:
                self._memory.store(block)
                if self._persistent:
                    self._persistent.save_block(block)
                loaded += 1
        logger.info(f"Hot-loaded {loaded} blocks from ZK (important={len(important)}, recent={len(recent)}, evergreen={len(evergreen)})")
        return loaded

    def decay_hot_scores(self, factor: float = 0.95) -> int:
        affected = 0
        for key in list(self._memory._blocks.keys()):
            block = self._memory._blocks.get(key)
            if block and block.access_count == 0:
                block.weight *= factor
                affected += 1
        logger.info(f"Decayed hot scores for {affected} untouched blocks")
        return affected

    def sync(self, direction: str = "auto") -> dict:
        result: dict = {}
        if direction in ("auto", "to-zk"):
            flushed = self.flush_cold_blocks()
            result["flushed_to_zk"] = flushed
        if direction in ("auto", "from-zk"):
            loaded = self.hot_load_from_zk()
            result["loaded_from_zk"] = loaded
        if direction == "auto":
            decayed = self.decay_hot_scores()
            result["decayed"] = decayed
        return result

    def status(self) -> dict:
        blocks = self._memory.list_blocks(tenant_id=self._tenant_id)
        synced = sum(1 for b in blocks if b.zk_note_id is not None)
        cold = sum(1 for b in blocks if b.hot_score < COLD_HOT_SCORE and b.zk_note_id is None)
        return {
            "total_blocks": len(blocks),
            "synced_to_zk": synced,
            "cold_unsynced": cold,
            "is_idle": self.is_idle,
            "idle_minutes_setting": self._idle_minutes,
        }

    def close(self) -> None:
        self._zk.close()
