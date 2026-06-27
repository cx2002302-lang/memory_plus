import os
import sys
import time
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from svm.models import MemoryBlock
from svm.store import MemoryStore, PersistentStore
from svm.trigger import KeywordMatcher


def _measure(description: str, fn, iterations: int = 1) -> float:
    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start
    per_op = elapsed / iterations
    print(f"  {description}: {elapsed:.4f}s total, {per_op*1000:.2f}ms/run")
    return elapsed


def test_keyword_matcher_small():
    """Small keyword set (10 keywords)"""
    m = KeywordMatcher()
    m.add_keywords([f"keyword_{i}" for i in range(10)])

    def run():
        for _ in range(1000):
            m.match("this is a test with keyword_5 and something else keyword_3 here")

    _measure("AC matcher (10 keywords, 1000x)", run, 1)


def test_keyword_matcher_large():
    """Large keyword set (5000 keywords)"""
    m = KeywordMatcher()
    m.add_keywords([f"kw_{i:04d}" for i in range(5000)])

    def run():
        for _ in range(100):
            m.match("looking for kw_1234 and kw_4567 in this long text " * 3)

    _measure("AC matcher (5000 keywords, 100x)", run, 1)


def test_store_throughput():
    """Store throughput with 10000 blocks"""
    store = MemoryStore(max_bytes=500 * 1024 * 1024)

    def run():
        for i in range(10000):
            store.store(MemoryBlock(key=f"k{i}", value=f"value_{i}"))

    _measure("Store 10000 blocks", run, 1)


def test_recall_latency():
    """Recall latency with 5000 blocks stored"""
    store = MemoryStore(max_bytes=500 * 1024 * 1024)
    for i in range(5000):
        store.store(MemoryBlock(
            key=f"k{i:04d}",
            value=f"value_{i} with keyword_{i % 100}",
            weight=(i % 10) / 10.0,
        ))

    def run():
        store.recall(keywords=["keyword_42"], top_n=10)

    _measure("Recall among 5000 blocks", run, 100)


def test_persistent_write():
    """SQLite write throughput"""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "perf.db")
        p = PersistentStore(db_path)

        blocks = [MemoryBlock(
            key=f"k{i:06d}", value=f"x" * 200 + str(i),
            weight=0.5, slot_id="test",
        ) for i in range(1000)]

        def run():
            p.save_blocks(blocks)

        ops = _measure("SQLite write 1000 blocks", run, 1)
        p.close()


def test_persistent_read():
    """SQLite read throughput"""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "perf.db")
        p = PersistentStore(db_path)

        blocks = [MemoryBlock(key=f"k{i:06d}", value=f"x" * 200 + str(i)) for i in range(1000)]
        p.save_blocks(blocks)

        def run():
            p.load_all()

        ops = _measure("SQLite read 1000 blocks", run, 10)
        p.close()


def test_lru_eviction_overhead():
    """LRU eviction performance under memory pressure"""
    store = MemoryStore(max_bytes=50000)
    for i in range(100):
        store.store(MemoryBlock(key=f"init_{i}", value="x" * 100))

    def run():
        for i in range(1000):
            store.store(MemoryBlock(key=f"evict_{i}", value="y" * 50))

    _measure("LRU eviction (1000 writes over capacity)", run, 1)
