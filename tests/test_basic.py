import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from svm.models import MemoryBlock, MemorySlot, ContextBundle
from svm.store import MemoryStore, PersistentStore
from svm.trigger import KeywordMatcher, RecallStrategy
from svm.config import SVMConfig, PRESETS, _detect_system_memory_mb
from svm.audit import AuditLogger
from svm.exceptions import SVMError, BlockNotFoundError, ConfigError


class TestMemoryBlock:
    def test_create_block(self):
        block = MemoryBlock(key="user_name", value="张三")
        assert block.key == "user_name"
        assert block.value == "张三"
        assert block.weight == 0.5
        assert block.access_count == 0
        assert not block.is_expired
        assert block.tenant_id == "default"

    def test_tenant_id(self):
        block = MemoryBlock(key="k", value="v", tenant_id="tenant-a")
        assert block.tenant_id == "tenant-a"

    def test_expiry(self):
        block = MemoryBlock(key="temp", value="x", ttl=0.001)
        import time
        time.sleep(0.01)
        assert block.is_expired

    def test_no_expiry(self):
        block = MemoryBlock(key="perm", value="y")
        assert not block.is_expired

    def test_touch(self):
        block = MemoryBlock(key="k", value="v")
        old_ts = block.last_accessed
        block.touch()
        assert block.access_count == 1
        assert block.last_accessed > old_ts

    def test_hot_score(self):
        new_block = MemoryBlock(key="new", value="hello", weight=1.0)
        old_block = MemoryBlock(
            key="old", value="world", weight=0.1,
            created_at=datetime.now() - timedelta(hours=48),
        )
        assert new_block.hot_score > old_block.hot_score

    def test_estimated_tokens(self):
        block = MemoryBlock(key="k", value="你好世界")
        assert block.estimated_tokens > 0


class TestContextBundle:
    def test_empty_bundle(self):
        bundle = ContextBundle.from_blocks([])
        assert len(bundle.blocks) == 0
        assert bundle.total_tokens == 0

    def test_bundle_sorted_by_hot_score(self):
        high = MemoryBlock(key="high", value="a" * 10, weight=1.0)
        low = MemoryBlock(key="low", value="b" * 10, weight=0.1)
        bundle = ContextBundle.from_blocks([low, high], max_tokens=1000)
        assert bundle.blocks[0].key == "high"

    def test_bundle_respects_max_tokens(self):
        blocks = [
            MemoryBlock(key=f"b{i}", value="x" * 200, weight=0.5)
            for i in range(10)
        ]
        bundle = ContextBundle.from_blocks(blocks, max_tokens=500)
        assert bundle.total_tokens <= 500


class TestMemoryStore:
    def setup_method(self):
        self.store = MemoryStore(max_bytes=1024 * 1024)

    def test_store_and_get(self):
        block = MemoryBlock(key="test", value="hello")
        self.store.store(block)
        retrieved = self.store.get("test")
        assert retrieved is not None
        assert retrieved.key == "test"
        assert retrieved.value == "hello"

    def test_get_miss(self):
        assert self.store.get("nonexistent") is None

    def test_delete(self):
        block = MemoryBlock(key="del", value="bye")
        self.store.store(block)
        assert self.store.delete("del") is True
        assert self.store.get("del") is None

    def test_slot_index(self):
        b1 = MemoryBlock(key="a1", value="foo", slot_id="s1")
        b2 = MemoryBlock(key="a2", value="bar", slot_id="s1")
        b3 = MemoryBlock(key="b1", value="baz", slot_id="s2")
        self.store.store(b1)
        self.store.store(b2)
        self.store.store(b3)
        blocks = self.store.get_slot_blocks("s1")
        assert len(blocks) == 2

    def test_search_by_keywords(self):
        self.store.store(MemoryBlock(key="name", value="张三"))
        self.store.store(MemoryBlock(key="city", value="北京"))
        results = self.store.search_by_keywords(["张三"])
        assert len(results) == 1
        assert results[0].key == "name"

    def test_recall_by_keyword(self):
        self.store.store(MemoryBlock(key="project", value="SVM 记忆组件"))
        results = self.store.recall(keywords=["SVM"])
        assert len(results) == 1

    def test_recall_top_n(self):
        for i in range(20):
            self.store.store(MemoryBlock(key=f"k{i}", value=f"value {i}"))
        results = self.store.recall(top_n=5)
        assert len(results) == 5

    def test_eviction(self):
        small_store = MemoryStore(max_bytes=500)
        for i in range(100):
            small_store.store(MemoryBlock(key=f"k{i}", value="x" * 100))
        assert small_store.used_bytes <= small_store.max_bytes

    def test_stats(self):
        self.store.store(MemoryBlock(key="s", value="test"))
        self.store.get("s")
        self.store.get("s")
        self.store.get("missing")
        stats = self.store.get_stats()
        assert stats["blocks_count"] == 1
        assert stats["hit_count"] == 2
        assert stats["miss_count"] == 1
        assert stats["hit_rate"] > 0

    def test_clear(self):
        self.store.store(MemoryBlock(key="c", value="v"))
        self.store.clear()
        assert self.store.count == 0

    def test_tenant_isolation(self):
        store_a = MemoryStore(max_bytes=1024 * 1024, tenant_id="tenant-a")
        store_b = MemoryStore(max_bytes=1024 * 1024, tenant_id="tenant-b")
        store_a.store(MemoryBlock(key="ka", value="va", tenant_id="tenant-a"))
        store_b.store(MemoryBlock(key="kb", value="vb", tenant_id="tenant-b"))
        assert store_a.get("ka") is not None
        assert store_a.get("kb") is None
        assert store_b.get("kb") is not None
        stats_a = store_a.get_stats()
        assert stats_a["blocks_count"] == 1

    def test_tenant_clear(self):
        self.store.store(MemoryBlock(key="t1", value="v1", tenant_id="ta"))
        self.store.store(MemoryBlock(key="t2", value="v2", tenant_id="tb"))
        self.store.clear(tenant_id="ta")
        assert self.store.get("t1") is None
        assert self.store.get("t2") is not None


class TestPersistentStore:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.persist = PersistentStore(self.db_path)

    def teardown_method(self):
        self.persist.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        block = MemoryBlock(key="pk", value="pv")
        self.persist.save_block(block)
        loaded = self.persist.load_block("pk")
        assert loaded is not None
        assert loaded.key == "pk"
        assert loaded.value == "pv"

    def test_load_all(self):
        blocks = [MemoryBlock(key=f"bk{i}", value=f"bv{i}") for i in range(5)]
        self.persist.save_blocks(blocks)
        loaded = self.persist.load_all()
        assert len(loaded) == 5

    def test_delete(self):
        self.persist.save_block(MemoryBlock(key="dk", value="dv"))
        assert self.persist.delete_block("dk") is True
        assert self.persist.load_block("dk") is None

    def test_delete_slot(self):
        self.persist.save_blocks([
            MemoryBlock(key="sa", value="x", slot_id="s"),
            MemoryBlock(key="sb", value="y", slot_id="s"),
        ])
        assert self.persist.delete_slot("s") == 2
        assert self.persist.get_count() == 0

    def test_tenant_persistence(self):
        self.persist.save_block(MemoryBlock(key="tk1", value="tv1", tenant_id="ta"))
        self.persist.save_block(MemoryBlock(key="tk2", value="tv2", tenant_id="tb"))
        all_blocks = self.persist.load_all()
        assert len(all_blocks) == 2
        ta_blocks = self.persist.load_all(tenant_id="ta")
        assert len(ta_blocks) == 1
        assert ta_blocks[0].key == "tk1"

    def test_clear_tenant(self):
        self.persist.save_block(MemoryBlock(key="ca", value="va", tenant_id="ta"))
        self.persist.save_block(MemoryBlock(key="cb", value="vb", tenant_id="tb"))
        self.persist.clear(tenant_id="ta")
        assert self.persist.get_count() == 1


class TestKeywordMatcher:
    def setup_method(self):
        self.matcher = KeywordMatcher()

    def test_match_simple(self):
        self.matcher.add_keyword("hello")
        assert self.matcher.match("hello world") == ["hello"]

    def test_match_case_insensitive(self):
        self.matcher.add_keyword("Hello")
        assert self.matcher.match("hello world") == ["hello"]

    def test_no_match(self):
        self.matcher.add_keyword("abc")
        assert self.matcher.match("xyz") == []

    def test_multiple_keywords(self):
        self.matcher.add_keywords(["foo", "bar", "baz"])
        result = self.matcher.match("foo and baz")
        assert len(result) == 2
        assert "foo" in result
        assert "baz" in result

    def test_clear(self):
        self.matcher.add_keyword("test")
        self.matcher.clear()
        assert self.matcher.count == 0

    def test_many_keywords(self):
        kws = [f"kw{i}" for i in range(200)]
        self.matcher.add_keywords(kws)
        text = "this is kw42 and kw137 in text"
        result = self.matcher.match(text)
        assert "kw42" in result
        assert "kw137" in result
        assert len(result) >= 2


class TestSVMConfig:
    def test_default_preset(self):
        config = SVMConfig()
        assert config.profile == "标准"
        assert config.max_memory_mb is not None
        assert config.max_memory_mb >= 64

    def test_profile_轻量(self):
        total = _detect_system_memory_mb()
        config = SVMConfig(profile="轻量")
        assert config.max_memory_mb <= int(total * 0.10) + 1

    def test_profile_性能(self):
        total = _detect_system_memory_mb()
        config = SVMConfig(profile="性能")
        assert config.max_memory_mb <= int(total * 0.50) + 1

    def test_custom_memory(self):
        config = SVMConfig(max_memory_mb=2048)
        assert config.max_memory_mb == 2048

    def test_to_dict(self):
        config = SVMConfig()
        d = config.to_dict()
        assert "profile" in d
        assert "max_memory_mb" in d


class TestAuditLogger:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "audit.db")
        self.audit = AuditLogger(self.db_path)

    def teardown_method(self):
        self.audit.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_log_and_query(self):
        self.audit.log_store(key="k1", tenant_id="default")
        self.audit.log_recall(keyword_count=2, result_count=3)
        events = self.audit.query()
        assert len(events) == 2
        assert events[0]["action"] == "recall"
        assert events[1]["action"] == "store"

    def test_filter_by_action(self):
        self.audit.log_store(key="k1")
        self.audit.log_forget(key="k1", count=1)
        events = self.audit.query(action="store")
        assert len(events) == 1
        assert events[0]["action"] == "store"

    def test_disabled(self):
        audit = AuditLogger(self.db_path, enabled=False)
        audit.log_store(key="k")
        events = audit.query()
        assert len(events) == 0


class TestExceptions:
    def test_svm_error(self):
        e = SVMError("test error")
        assert str(e) == "test error"

    def test_block_not_found(self):
        e = BlockNotFoundError("mykey")
        assert e.key == "mykey"
        assert "mykey" in str(e)


class TestIntegration:
    def test_store_recall_flow(self):
        from svm.cli import SVMApp
        with tempfile.TemporaryDirectory() as tmp:
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)

            app.cmd_store(key="user", value="张三", weight=0.9)
            app.cmd_store(key="project", value="SVM", weight=0.8, slot_id="mem")

            result = app.cmd_recall(keyword=["张三"])
            assert result["count"] >= 1

            result2 = app.cmd_recall(keyword=["SVM"])
            assert result2["count"] >= 1

            stats = app.cmd_stats()
            assert stats["memory"]["blocks_count"] >= 2

            app.cmd_forget(key="user")
            stats2 = app.cmd_stats()
            assert stats2["memory"]["blocks_count"] == 1

    def test_tenant_isolation_cli(self):
        from svm.cli import SVMApp
        with tempfile.TemporaryDirectory() as tmp:
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)

            app.cmd_store(key="shared", value="from-a", tenant_id="tenant-a")
            app.cmd_store(key="shared", value="from-b", tenant_id="tenant-b")

            result_a = app.cmd_recall(keyword=["from-a"], tenant_id="tenant-a")
            result_b = app.cmd_recall(keyword=["from-b"], tenant_id="tenant-b")
            assert result_a["count"] == 1
            assert result_b["count"] == 1

    def test_audit_integration(self):
        from svm.cli import SVMApp
        with tempfile.TemporaryDirectory() as tmp:
            config = SVMConfig(data_dir=tmp, max_memory_mb=64, profile="自定义")
            app = SVMApp(config)

            app.cmd_store(key="audit_test", value="check")
            app.cmd_recall(keyword=["audit_test"])

            events = app.audit.query()
            assert len(events) >= 2
            assert events[0]["action"] == "recall"
            assert events[1]["action"] == "store"


class TestAdmissionControl:
    def setup_method(self):
        self.store = MemoryStore(max_bytes=2000, admission_min_weight=0.3, admission_pressure_ratio=0.5)

    def test_admits_when_pressure_low(self):
        for i in range(3):
            self.store.store(MemoryBlock(key=f"k{i}", value="x" * 100, weight=0.1))
        assert self.store.count == 3
        assert self.store._rejected_count == 0

    def test_rejects_low_weight_under_pressure(self):
        for i in range(8):
            self.store.store(MemoryBlock(key=f"k{i}", value="x" * 100, weight=0.6))
        assert self.store.usage_ratio >= 0.5
        rejected_before = self.store._rejected_count
        self.store.store(MemoryBlock(key="bad", value="n" * 100, weight=0.1))
        assert self.store._rejected_count == rejected_before + 1
        assert self.store.get("bad") is None

    def test_admits_high_weight_under_pressure(self):
        for i in range(8):
            self.store.store(MemoryBlock(key=f"k{i}", value="x" * 100, weight=0.6))
        rejected_before = self.store._rejected_count
        self.store.store(MemoryBlock(key="good", value="y" * 100, weight=0.9))
        assert self.store._rejected_count == rejected_before
        assert self.store.get("good") is not None

    def test_rejected_count_in_stats(self):
        for i in range(6):
            self.store.store(MemoryBlock(key=f"k{i}", value="x" * 100, weight=0.6))
        for i in range(5):
            self.store.store(MemoryBlock(key=f"bad{i}", value="n" * 100, weight=0.1))
        stats = self.store.get_stats()
        assert stats["rejected_count"] >= 5
        assert stats["admission_min_weight"] == 0.3
        assert stats["admission_pressure_ratio"] == 0.5
