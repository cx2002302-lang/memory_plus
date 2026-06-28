import os
import sys
import tempfile
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from svm.cli import SVMApp
from svm.config import SVMConfig


def _build_mock_memory_db(db_path: str, count: int = 10):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE chunks ("
        "  id TEXT, path TEXT, source TEXT, start_line INTEGER, end_line INTEGER, "
        "  hash TEXT, model TEXT, text TEXT, embedding TEXT, updated_at INTEGER"
        ")"
    )
    conn.execute(
        "CREATE TABLE files ("
        "  path TEXT, source TEXT, hash TEXT, mtime REAL, size INTEGER"
        ")"
    )
    conn.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content=chunks)")
    for i in range(count):
        conn.execute(
            "INSERT INTO chunks (id, path, source, start_line, end_line, hash, model, text, embedding, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"id{i:03d}",
                f"memory/2026-06-{i % 30 + 1:02d}.md",
                "memory",
                i * 10 + 1,
                (i + 1) * 10,
                f"hash{i}",
                "fts-only",
                f"这是第 {i} 条记忆内容，用于测试导入功能。",
                "[]",
                1785000000000 + i * 3600000,
            ),
        )
    conn.execute(
        "INSERT INTO files (path, source, hash, mtime, size) VALUES (?, ?, ?, ?, ?)",
        ("memory/2026-06-01.md", "memory", "filehash1", 1785000000000.0, 100),
    )
    conn.commit()
    conn.close()


class TestImport:
    def test_import_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "memory.db")
            _build_mock_memory_db(src)
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)
            result = app.cmd_import_openclaw_memory(source=src, dry_run=True)
            assert result["status"] == "ok"
            assert result["total"] == 10
            assert result["imported"] == 10
            assert result["skipped"] == 0
            assert result["dry_run"] is True
            stats = app.cmd_stats()
            assert stats["memory"]["blocks_count"] == 0

    def test_import_actual(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "memory.db")
            _build_mock_memory_db(src)
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)
            result = app.cmd_import_openclaw_memory(source=src)
            assert result["status"] == "ok"
            assert result["total"] == 10
            assert result["imported"] == 10
            assert result["dry_run"] is False
            stats = app.cmd_stats()
            assert stats["memory"]["blocks_count"] == 10

    def test_import_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "memory.db")
            _build_mock_memory_db(src)
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)
            app.cmd_import_openclaw_memory(source=src)
            result2 = app.cmd_import_openclaw_memory(source=src)
            assert result2["imported"] == 0
            assert result2["skipped"] == 10
            stats = app.cmd_stats()
            assert stats["memory"]["blocks_count"] == 10

    def test_import_source_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)
            result = app.cmd_import_openclaw_memory(source="/nonexistent/path")
            assert result["status"] == "error"

    def test_import_empty_text_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "memory.db")
            conn = sqlite3.connect(src)
            conn.execute(
                "CREATE TABLE chunks ("
                "  id TEXT, path TEXT, source TEXT, start_line INTEGER, end_line INTEGER, "
                "  hash TEXT, model TEXT, text TEXT, embedding TEXT, updated_at INTEGER"
                ")"
            )
            conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("id1", "mem.md", "memory", 1, 5, "h1", "fts-only", "   ", "[]", 1785000000000),
            )
            conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("id2", "mem.md", "memory", 6, 10, "h2", "fts-only", "实际内容", "[]", 1785000000000),
            )
            conn.commit()
            conn.close()
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)
            result = app.cmd_import_openclaw_memory(source=src)
            assert result["imported"] == 1
            assert result["skipped"] == 1

    def test_import_tenant_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "memory.db")
            _build_mock_memory_db(src)
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)
            r1 = app.cmd_import_openclaw_memory(source=src, tenant_id="ta")
            r2 = app.cmd_import_openclaw_memory(source=src, tenant_id="tb")
            assert r1["imported"] == 10
            assert r2["imported"] == 10
            stats_a = app.cmd_stats(tenant_id="ta")
            stats_b = app.cmd_stats(tenant_id="tb")
            assert stats_a["memory"]["blocks_count"] == 10
            assert stats_b["memory"]["blocks_count"] == 10

    def test_import_slot_marking(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "memory.db")
            _build_mock_memory_db(src)
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)
            app.cmd_import_openclaw_memory(source=src)
            blocks = app.cmd_list()
            for b in blocks:
                assert b["slot_id"] == "imported:openclaw-memory"
