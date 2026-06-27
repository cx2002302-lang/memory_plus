import sqlite3
import os
import logging
from datetime import datetime
from typing import List, Optional
from ..models import MemoryBlock

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_blocks (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    task_id TEXT,
    weight REAL NOT NULL DEFAULT 0.5,
    ttl REAL,
    slot_id TEXT,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    last_accessed TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    zk_note_id TEXT,
    synced_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_blocks_slot_id ON memory_blocks(slot_id);
CREATE INDEX IF NOT EXISTS idx_memory_blocks_created_at ON memory_blocks(created_at);
CREATE INDEX IF NOT EXISTS idx_memory_blocks_weight ON memory_blocks(weight);
"""

SCHEMA_MIGRATE_TENANT = """
ALTER TABLE memory_blocks ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
"""

SCHEMA_MIGRATE_SYNC = """
ALTER TABLE memory_blocks ADD COLUMN zk_note_id TEXT;
ALTER TABLE memory_blocks ADD COLUMN synced_at TEXT;
"""


class PersistentStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        cursor = self._conn.execute("PRAGMA table_info(memory_blocks)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "tenant_id" not in columns:
            try:
                self._conn.execute(SCHEMA_MIGRATE_TENANT)
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memory_blocks_tenant_id ON memory_blocks(tenant_id)"
                )
                self._conn.commit()
                logger.info("Migrated schema: added tenant_id column")
            except sqlite3.OperationalError:
                self._conn.rollback()
        if "zk_note_id" not in columns:
            try:
                self._conn.executescript(SCHEMA_MIGRATE_SYNC)
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memory_blocks_zk_note_id ON memory_blocks(zk_note_id)"
                )
                self._conn.commit()
                logger.info("Migrated schema: added sync columns")
            except sqlite3.OperationalError:
                self._conn.rollback()

    def save_block(self, block: MemoryBlock) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO memory_blocks
               (key, value, created_at, task_id, weight, ttl, slot_id, tenant_id,
                last_accessed, access_count, zk_note_id, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                block.key,
                block.value,
                block.created_at.isoformat(),
                block.task_id,
                block.weight,
                block.ttl,
                block.slot_id,
                block.tenant_id,
                block.last_accessed.isoformat(),
                block.access_count,
                block.zk_note_id,
                block.synced_at.isoformat() if block.synced_at else None,
            ),
        )
        self._conn.commit()

    def save_blocks(self, blocks: List[MemoryBlock]) -> None:
        rows = [
            (
                b.key,
                b.value,
                b.created_at.isoformat(),
                b.task_id,
                b.weight,
                b.ttl,
                b.slot_id,
                b.tenant_id,
                b.last_accessed.isoformat(),
                b.access_count,
                b.zk_note_id,
                b.synced_at.isoformat() if b.synced_at else None,
            )
            for b in blocks
        ]
        self._conn.executemany(
            """INSERT OR REPLACE INTO memory_blocks
               (key, value, created_at, task_id, weight, ttl, slot_id, tenant_id,
                last_accessed, access_count, zk_note_id, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()

    def load_all(self, tenant_id: Optional[str] = None) -> List[MemoryBlock]:
        if tenant_id:
            cursor = self._conn.execute(
                "SELECT * FROM memory_blocks WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            )
        else:
            cursor = self._conn.execute("SELECT * FROM memory_blocks ORDER BY created_at DESC")

        blocks = []
        for row in cursor.fetchall():
            block = self._row_to_block(row)
            blocks.append(block)
        return blocks

    def load_block(self, key: str) -> Optional[MemoryBlock]:
        cursor = self._conn.execute("SELECT * FROM memory_blocks WHERE key = ?", (key,))
        row = cursor.fetchone()
        return self._row_to_block(row) if row else None

    def _row_to_block(self, row: sqlite3.Row) -> MemoryBlock:
        return MemoryBlock(
            key=row["key"],
            value=row["value"],
            created_at=datetime.fromisoformat(row["created_at"]),
            task_id=row["task_id"],
            weight=row["weight"],
            ttl=row["ttl"],
            slot_id=row["slot_id"],
            tenant_id=row["tenant_id"],
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
            access_count=row["access_count"],
            zk_note_id=row["zk_note_id"],
            synced_at=datetime.fromisoformat(row["synced_at"]) if row["synced_at"] else None,
        )

    def delete_block(self, key: str) -> bool:
        cursor = self._conn.execute("DELETE FROM memory_blocks WHERE key = ?", (key,))
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_slot(self, slot_id: str, tenant_id: Optional[str] = None) -> int:
        if tenant_id:
            cursor = self._conn.execute(
                "DELETE FROM memory_blocks WHERE slot_id = ? AND tenant_id = ?",
                (slot_id, tenant_id),
            )
        else:
            cursor = self._conn.execute("DELETE FROM memory_blocks WHERE slot_id = ?", (slot_id,))
        self._conn.commit()
        return cursor.rowcount

    def clear(self, tenant_id: Optional[str] = None) -> None:
        if tenant_id:
            self._conn.execute("DELETE FROM memory_blocks WHERE tenant_id = ?", (tenant_id,))
        else:
            self._conn.execute("DELETE FROM memory_blocks")
        self._conn.commit()

    def get_count(self, tenant_id: Optional[str] = None) -> int:
        if tenant_id:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM memory_blocks WHERE tenant_id = ?", (tenant_id,)
            )
        else:
            cursor = self._conn.execute("SELECT COUNT(*) FROM memory_blocks")
        return cursor.fetchone()[0]

    def close(self) -> None:
        self._conn.close()
