import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta
from svm.models import MemoryBlock
from svm.store import MemoryStore, PersistentStore
from svm.sync.engine import SyncEngine, COLD_HOT_SCORE
from svm.sync.zk_sync import ZKDatabase, SYNC_TAG, HOT_TAG


def _build_mock_zk_db(db_path: str):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        "CREATE TABLE zettel_notes ("
        "  id TEXT PRIMARY KEY, title TEXT, content TEXT, type TEXT, "
        "  status TEXT, folder TEXT, confidence REAL, source TEXT, "
        "  reviewed INTEGER, file_path TEXT, created_at TEXT, updated_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE zettel_tags ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, created_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE zettel_note_tags ("
        "  note_id TEXT, tag_id INTEGER,"
        "  FOREIGN KEY (note_id) REFERENCES zettel_notes(id),"
        "  FOREIGN KEY (tag_id) REFERENCES zettel_tags(id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE zettel_note_stats ("
        "  note_id TEXT PRIMARY KEY, glow_status TEXT, glow_score REAL,"
        "  backlink_count INTEGER, outgoing_link_count INTEGER"
        ")"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE zettel_fts USING fts5(title, content, id UNINDEXED, type UNINDEXED)"
    )
    conn.execute(
        "INSERT INTO zettel_tags (name, created_at) VALUES (?, ?)",
        (HOT_TAG, "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO zettel_tags (name, created_at) VALUES (?, ?)",
        (SYNC_TAG, "2026-01-01T00:00:00"),
    )
    hot_tag_id = conn.execute("SELECT id FROM zettel_tags WHERE name=?", (HOT_TAG,)).fetchone()[0]
    for i in range(5):
        nid = f"note_imp_{i:03d}"
        conn.execute(
            "INSERT INTO zettel_notes (id, title, content, type, status, folder, confidence, source, reviewed, file_path, created_at, updated_at) "
            "VALUES (?, ?, ?, 'atomic', 'active', 'zettels', ?, 'manual', 1, ?, ?, ?)",
            (
                nid,
                f"Important note {i}",
                f"Content of important note {i}",
                0.9 + i * 0.02,
                f"zk/{nid}.md",
                "2026-06-01T00:00:00",
                "2026-06-25T00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO zettel_note_tags (note_id, tag_id) VALUES (?, ?)",
            (nid, hot_tag_id),
        )
        conn.execute(
            "INSERT INTO zettel_fts (id, title, content) VALUES (?, ?, ?)",
            (nid, f"Important note {i}", f"Content of important note {i}"),
        )
    for i in range(3):
        nid = f"note_rec_{i:03d}"
        conn.execute(
            "INSERT INTO zettel_notes (id, title, content, type, status, folder, confidence, source, reviewed, file_path, created_at, updated_at) "
            "VALUES (?, ?, ?, 'atomic', 'active', 'inbox', ?, 'manual', 1, ?, ?, ?)",
            (
                nid,
                f"Recent note {i}",
                f"Content of recent note {i}",
                0.5,
                f"zk/{nid}.md",
                "2026-06-27T00:00:00",
                "2026-06-28T00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO zettel_fts (id, title, content) VALUES (?, ?, ?)",
            (nid, f"Recent note {i}", f"Content of recent note {i}"),
        )
    for i in range(2):
        nid = f"note_ev_{i:03d}"
        conn.execute(
            "INSERT INTO zettel_notes (id, title, content, type, status, folder, confidence, source, reviewed, file_path, created_at, updated_at) "
            "VALUES (?, ?, ?, 'atomic', 'active', 'zettels', ?, 'manual', 1, ?, ?, ?)",
            (
                nid,
                f"Evergreen note {i}",
                f"Content of evergreen note {i}",
                0.8,
                f"zk/{nid}.md",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO zettel_note_stats (note_id, glow_status, glow_score, backlink_count, outgoing_link_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (nid, "evergreen" if i == 0 else "active", 0.9 - i * 0.1, 10, 50),
        )
        conn.execute(
            "INSERT INTO zettel_fts (id, title, content) VALUES (?, ?, ?)",
            (nid, f"Evergreen note {i}", f"Content of evergreen note {i}"),
        )
    conn.commit()
    conn.close()


class TestZKDatabase:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "zk.db")
        _build_mock_zk_db(self.db_path)
        self.zk = ZKDatabase(self.db_path)

    def teardown_method(self):
        self.zk.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_important(self):
        blocks = self.zk.load_important_notes(days=365, limit=10)
        assert len(blocks) >= 5
        zk_ids = [b.zk_note_id for b in blocks]
        assert any(nid.startswith("note_imp") for nid in zk_ids)

    def test_load_recent(self):
        blocks = self.zk.load_recent_notes(days=7, limit=10)
        assert len(blocks) == 8
        zk_ids = [b.zk_note_id for b in blocks]
        assert any(nid.startswith("note_rec") for nid in zk_ids)

    def test_load_evergreen(self):
        blocks = self.zk.load_evergreen_notes(limit=10)
        assert len(blocks) == 2
        assert all(b.zk_note_id.startswith("note_ev") for b in blocks)

    def test_create_note_from_block(self):
        block = MemoryBlock(key="test_key", value="test value", weight=0.8)
        note_id = self.zk.create_note_from_block(block)
        assert note_id is not None
        conn = self.zk._connect()
        row = conn.execute("SELECT title, content, folder FROM zettel_notes WHERE id=?", (note_id,)).fetchone()
        assert row is not None
        assert "[SVM] test_key" in row["title"]
        assert row["content"] == "test value"

    def test_mark_note_important(self):
        assert self.zk.mark_note_important("note_rec_000") is True
        conn = self.zk._connect()
        hot_tag_id = conn.execute("SELECT id FROM zettel_tags WHERE name=?", (HOT_TAG,)).fetchone()[0]
        row = conn.execute(
            "SELECT 1 FROM zettel_note_tags WHERE note_id=? AND tag_id=?",
            ("note_rec_000", hot_tag_id),
        ).fetchone()
        assert row is not None

    def test_search_notes(self):
        results = self.zk.search_notes(query="Important", limit=10)
        assert len(results) >= 3
        for b in results:
            assert "Important" in b.value


class TestSyncEngine:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "zk.db")
        _build_mock_zk_db(self.db_path)
        self.store = MemoryStore(max_bytes=1024 * 1024)
        self.persist = PersistentStore(os.path.join(self.tmpdir, "svm.db"))
        self.engine = SyncEngine(
            memory=self.store,
            zk_db_path=self.db_path,
            persistent=self.persist,
            idle_minutes=0,
            tenant_id="default",
        )

    def teardown_method(self):
        self.engine.close()
        self.persist.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_hot_load_from_zk(self):
        loaded = self.engine.hot_load_from_zk(
            important_days=365, recent_days=7, evergreen_limit=20, max_blocks=100
        )
        assert loaded >= 10

    def test_hot_load_deduplicates(self):
        self.engine.hot_load_from_zk(
            important_days=365, recent_days=7, evergreen_limit=20, max_blocks=100
        )
        first_count = self.store.count
        loaded2 = self.engine.hot_load_from_zk(
            important_days=365, recent_days=7, evergreen_limit=20, max_blocks=100
        )
        assert loaded2 == 0
        assert self.store.count == first_count

    def test_flush_cold_blocks(self):
        old_ts = datetime.now() - timedelta(days=60)
        cold = MemoryBlock(key="cold1", value="cold value", weight=0.1, created_at=old_ts)
        hot = MemoryBlock(key="hot1", value="hot value", weight=0.9)
        self.store.store(cold)
        self.store.store(hot)
        flushed = self.engine.flush_cold_blocks(force=True)
        assert flushed >= 1
        assert self.store.get("cold1").zk_note_id is not None

    def test_flush_skips_when_not_idle(self):
        self.engine._last_activity = None
        self.engine._idle_minutes = 999
        old_ts = datetime.now() - timedelta(days=60)
        cold = MemoryBlock(key="cold2", value="cold", weight=0.1, created_at=old_ts)
        self.store.store(cold)
        flushed = self.engine.flush_cold_blocks(force=False)
        assert flushed == 0

    def test_sync_auto(self):
        old_ts = datetime.now() - timedelta(days=60)
        cold = MemoryBlock(key="sync_cold", value="sync cold", weight=0.1, created_at=old_ts)
        self.store.store(cold)
        result = self.engine.sync(direction="auto")
        assert "flushed_to_zk" in result
        assert "loaded_from_zk" in result
        assert "decayed" in result

    def test_sync_to_zk(self):
        old_ts = datetime.now() - timedelta(days=60)
        self.engine._last_activity = datetime.now() - timedelta(hours=1)
        cold = MemoryBlock(key="to_zk", value="to zk", weight=0.1, created_at=old_ts)
        self.store.store(cold)
        result = self.engine.sync(direction="to-zk")
        assert result["flushed_to_zk"] >= 1

    def test_sync_from_zk(self):
        result = self.engine.sync(direction="from-zk")
        assert result["loaded_from_zk"] >= 3

    def test_decay_hot_scores(self):
        b1 = MemoryBlock(key="decay1", value="v1", weight=1.0)
        b2 = MemoryBlock(key="decay2", value="v2", weight=1.0)
        self.store.store(b1)
        self.store.store(b2)
        self.store.get("decay1")
        decayed = self.engine.decay_hot_scores(factor=0.5)
        assert decayed == 1
        assert self.store.get("decay2").weight < 1.0

    def test_status(self):
        self.engine.hot_load_from_zk(
            important_days=365, recent_days=7, evergreen_limit=20, max_blocks=100
        )
        s = self.engine.status()
        assert s["total_blocks"] >= 10
        assert s["synced_to_zk"] >= 10
