import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    tenant_id TEXT NOT NULL DEFAULT 'default',
    details TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_events(tenant_id);
"""


class AuditLogger:
    def __init__(self, db_path: str, enabled: bool = True) -> None:
        self._enabled = enabled
        if not enabled:
            return
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.executescript(AUDIT_SCHEMA)
        self._conn.commit()

    def log(
        self,
        action: str,
        actor: str = "system",
        tenant_id: str = "default",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        if not self._enabled:
            return
        self._conn.execute(
            "INSERT INTO audit_events (timestamp, action, actor, tenant_id, details) VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(),
                action,
                actor,
                tenant_id,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def log_store(self, key: str, tenant_id: str = "default", actor: str = "system", extra: Optional[dict] = None) -> None:
        self.log("store", actor, tenant_id, {"key": key, **(extra or {})})

    def log_recall(self, keyword_count: int, result_count: int, tenant_id: str = "default", actor: str = "system") -> None:
        self.log("recall", actor, tenant_id, {"keyword_count": keyword_count, "result_count": result_count})

    def log_forget(self, key: Optional[str], count: int, tenant_id: str = "default", actor: str = "system") -> None:
        self.log("forget", actor, tenant_id, {"key": key, "count": count})

    def log_config_change(self, changes: dict, actor: str = "system") -> None:
        self.log("config_change", actor, "default", changes)

    def query(
        self,
        action: Optional[str] = None,
        tenant_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        parts = ["SELECT * FROM audit_events"]
        params: list[Any] = []
        conditions = []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if conditions:
            parts.append("WHERE " + " AND ".join(conditions))
        parts.append("ORDER BY id DESC LIMIT ?")
        params.append(limit)
        cursor = self._conn.execute(" ".join(parts), params)
        results = []
        for row in cursor.fetchall():
            results.append({
                "id": row[0],
                "timestamp": row[1],
                "action": row[2],
                "actor": row[3],
                "tenant_id": row[4],
                "details": json.loads(row[5]) if row[5] else {},
            })
        return results

    def close(self) -> None:
        if self._enabled:
            self._conn.close()
