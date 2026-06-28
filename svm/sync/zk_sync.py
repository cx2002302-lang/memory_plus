import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from ..models import MemoryBlock

logger = logging.getLogger(__name__)

SYNC_TAG = "svm:synced"
HOT_TAG = "svm:hot"

ZK_NOTE_SOURCE = "distilled"


class ZKDatabase:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure_tag(self, tag_name: str) -> int:
        conn = self._connect()
        cursor = conn.execute("SELECT id FROM zettel_tags WHERE name = ?", (tag_name,))
        row = cursor.fetchone()
        if row:
            return row["id"]
        conn.execute(
            "INSERT INTO zettel_tags (name, created_at) VALUES (?, ?)",
            (tag_name, datetime.now().isoformat()),
        )
        conn.commit()
        return conn.execute("SELECT id FROM zettel_tags WHERE name = ?", (tag_name,)).fetchone()["id"]

    def load_important_notes(
        self, days: int = 7, limit: int = 50, tenant_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        conn = self._connect()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """
            SELECT DISTINCT n.* FROM zettel_notes n
            LEFT JOIN zettel_note_tags nt ON n.id = nt.note_id
            LEFT JOIN zettel_tags t ON nt.tag_id = t.id
            WHERE n.folder != 'archive'
              AND (
                  t.name = ?
                  OR n.confidence >= 0.9
                  OR n.folder = 'zettels'
                  OR n.created_at >= ?
                  OR n.updated_at >= ?
              )
            ORDER BY n.confidence DESC, n.updated_at DESC
            LIMIT ?
            """,
            (HOT_TAG, cutoff, cutoff, limit),
        )
        blocks = []
        for row in rows:
            tags = self._get_note_tags(row["id"])
            keywords = [t for t in tags if not t.startswith("svm:")] or ["zk_imported"]
            block = MemoryBlock(
                key=f"zk:{row['id']}",
                value=row["title"] + "\n\n" + (row["content"] or ""),
                weight=row["confidence"] or 0.5,
                slot_id="zk_hotload",
                tenant_id=tenant_id or "default",
                zk_note_id=row["id"],
            )
            blocks.append(block)
        return blocks

    def load_recent_notes(
        self, days: int = 7, limit: int = 50, tenant_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        conn = self._connect()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """
            SELECT * FROM zettel_notes
            WHERE folder != 'archive'
              AND (created_at >= ? OR updated_at >= ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (cutoff, cutoff, limit),
        )
        blocks = []
        for row in rows:
            tags = self._get_note_tags(row["id"])
            keywords = [t for t in tags if not t.startswith("svm:")] or ["zk_recent"]
            block = MemoryBlock(
                key=f"zk:recent:{row['id']}",
                value=row["title"] + "\n\n" + (row["content"] or ""),
                weight=row["confidence"] or 0.5,
                slot_id="zk_hotload",
                tenant_id=tenant_id or "default",
                zk_note_id=row["id"],
            )
            blocks.append(block)
        return blocks

    def load_evergreen_notes(
        self, limit: int = 50, tenant_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT n.* FROM zettel_notes n
            JOIN zettel_note_stats s ON n.id = s.note_id
            WHERE n.folder != 'archive'
              AND s.glow_status IN ('evergreen', 'active')
            ORDER BY s.glow_score DESC
            LIMIT ?
            """,
            (limit,),
        )
        blocks = []
        for row in rows:
            tags = self._get_note_tags(row["id"])
            keywords = [t for t in tags if not t.startswith("svm:")] or ["zk_evergreen"]
            block = MemoryBlock(
                key=f"zk:evergreen:{row['id']}",
                value=row["title"] + "\n\n" + (row["content"] or ""),
                weight=row["confidence"] or 0.5,
                slot_id="zk_hotload",
                tenant_id=tenant_id or "default",
                zk_note_id=row["id"],
            )
            blocks.append(block)
        return blocks

    def search_notes(
        self,
        query: str,
        folder: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        tags: Optional[List[str]] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        limit: int = 20,
        tenant_id: Optional[str] = None,
    ) -> List[MemoryBlock]:
        conn = self._connect()
        sql = (
            "SELECT DISTINCT n.id, n.title, n.content, n.confidence, n.folder, "
            "n.status, n.created_at, n.updated_at FROM zettel_notes n "
        )
        params: list = []
        wheres = ["n.folder != 'archive'"]

        if tags:
            placeholders = ",".join("?" for _ in tags)
            sql += f"LEFT JOIN zettel_note_tags nt ON n.id = nt.note_id "
            sql += f"LEFT JOIN zettel_tags t ON nt.tag_id = t.id "
            for tag in tags:
                wheres.append("EXISTS (SELECT 1 FROM zettel_note_tags nt2 "
                              "JOIN zettel_tags t2 ON nt2.tag_id = t2.id "
                              "WHERE nt2.note_id = n.id AND t2.name = ?)")
                params.append(tag)

        if query and query != "*":
            q_sql = "SELECT id FROM zettel_fts WHERE zettel_fts MATCH ?"
            wheres.append(f"n.id IN ({q_sql})")
            params.append(query)

        if folder:
            wheres.append("n.folder = ?")
            params.append(folder)

        if min_confidence is not None:
            wheres.append("n.confidence >= ?")
            params.append(min_confidence)

        if max_confidence is not None:
            wheres.append("n.confidence <= ?")
            params.append(max_confidence)

        if created_after:
            wheres.append("n.created_at >= ?")
            params.append(created_after)

        if created_before:
            wheres.append("n.created_at <= ?")
            params.append(created_before)

        sql += "WHERE " + " AND ".join(wheres)
        sql += " ORDER BY n.confidence DESC, n.updated_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        blocks = []
        for row in rows:
            note_tags = self._get_note_tags(row["id"])
            keywords = [t for t in note_tags if not t.startswith("svm:")] or ["zk_search"]
            block = MemoryBlock(
                key=f"zk:{row['id']}",
                value=row["title"] + "\n\n" + (row["content"] or ""),
                weight=row["confidence"] or 0.5,
                slot_id="zk_search",
                tenant_id=tenant_id or "default",
                zk_note_id=row["id"],
            )
            blocks.append(block)
        return blocks

    def _get_note_tags(self, note_id: str) -> List[str]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT t.name FROM zettel_tags t
            JOIN zettel_note_tags nt ON t.id = nt.tag_id
            WHERE nt.note_id = ?
            """,
            (note_id,),
        )
        return [row["name"] for row in rows.fetchall()]

    def create_note_from_block(self, block: MemoryBlock, status: str = "FLEETING") -> Optional[str]:
        conn = self._connect()
        now = datetime.now()
        note_id = now.strftime("%Y%m%d%H%M%S") + f"{int(now.timestamp() * 1000) % 1000:03d}"
        title = f"[SVM] {block.key}"
        content = block.value
        folder = "zettels" if block.weight >= 0.7 else "references"
        try:
            conn.execute(
                """INSERT INTO zettel_notes
                   (id, title, content, type, status, folder, confidence,
                    source, reviewed, file_path, created_at, updated_at)
                   VALUES (?, ?, ?, 'atomic', ?, ?, ?, ?, 0, ?, ?, ?)""",
                (
                    note_id,
                    title[:500],
                    content,
                    status,
                    folder,
                    min(block.weight, 1.0),
                    ZK_NOTE_SOURCE,
                    f"svm/{block.key[:50].replace('/', '_')}",
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            sync_tag_id = self._ensure_tag(SYNC_TAG)
            conn.execute(
                "INSERT OR IGNORE INTO zettel_note_tags (note_id, tag_id) VALUES (?, ?)",
                (note_id, sync_tag_id),
            )
            if block.slot_id:
                slot_tag_id = self._ensure_tag(f"svm:slot:{block.slot_id}")
                conn.execute(
                    "INSERT OR IGNORE INTO zettel_note_tags (note_id, tag_id) VALUES (?, ?)",
                    (note_id, slot_tag_id),
                )
            conn.commit()
            logger.info(f"Created ZK note {note_id} from SVM block {block.key}")
            return note_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create ZK note: {e}")
            return None

    def mark_note_important(self, note_id: str) -> bool:
        conn = self._connect()
        try:
            hot_tag_id = self._ensure_tag(HOT_TAG)
            conn.execute(
                "INSERT OR IGNORE INTO zettel_note_tags (note_id, tag_id) VALUES (?, ?)",
                (note_id, hot_tag_id),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to mark note {note_id} as important: {e}")
            return False
