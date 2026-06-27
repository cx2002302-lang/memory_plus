import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
from . import __version__
from .audit import AuditLogger
from .config import SVMConfig, PRESETS
from .exceptions import SVMError
from .models import MemoryBlock
from .store import MemoryStore, PersistentStore
from .trigger import KeywordMatcher, RecallStrategy
from .injector import ContextInjector
from .sync.engine import SyncEngine
from .sync.zk_sync import ZKDatabase

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("svm")


class SVMApp:
    def __init__(self, config: Optional[SVMConfig] = None) -> None:
        self.config = config or SVMConfig.load()
        self._ensure_data_dir()
        self.persistent = PersistentStore(self.config.db_path)
        self.store = MemoryStore(
            self.config.max_memory_mb * 1024 * 1024,
            tenant_id=getattr(self.config, "tenant_id", "default"),
            on_evict=self._evict_sync_cb,
            admission_min_weight=getattr(self.config, "admission_min_weight", 0.1),
            admission_pressure_ratio=getattr(self.config, "admission_pressure_ratio", 0.8),
        )
        self.matcher = KeywordMatcher()
        self.strategy = RecallStrategy(self.store, self.matcher)
        self.injector = ContextInjector()
        self.audit = AuditLogger(
            db_path=self._audit_db_path,
            enabled=getattr(self.config, "audit_enabled", True),
        )
        self._load_snapshot()

    @property
    def _audit_db_path(self) -> str:
        return os.path.join(self.config.data_dir, "audit.db")

    def _ensure_data_dir(self) -> None:
        os.makedirs(self.config.data_dir, exist_ok=True)

    def _zk_db_path(self) -> str:
        return os.path.expanduser(
            getattr(self.config, "zk_db_path", "~/.openclaw/zettelkasten/zettelkasten.db")
        )

    def _sync_engine(self) -> SyncEngine:
        return SyncEngine(
            memory=self.store,
            zk_db_path=self._zk_db_path(),
            persistent=self.persistent,
            tenant_id=self.store.tenant_id,
        )

    def _evict_sync_cb(self, block: MemoryBlock) -> None:
        zk = ZKDatabase(self._zk_db_path())
        try:
            note_id = zk.create_note_from_block(block, status="FLEETING")
            if note_id:
                block.zk_note_id = note_id
                block.synced_at = datetime.now()
                self.persistent.save_block(block)
                self.audit.log_store(
                    key=block.key, tenant_id=block.tenant_id,
                    extra={"action": "evict_sync", "zk_note_id": note_id},
                )
        except Exception:
            logger.exception(f"Evict-sync failed for {block.key}")
        finally:
            zk.close()

    def _load_snapshot(self) -> None:
        blocks = self.persistent.load_all(tenant_id=self.store.tenant_id)
        self.store.load_from_snapshot(blocks)
        logger.info(
            f"Loaded {len(blocks)} blocks into memory "
            f"({self.store.used_bytes // 1024}KB / "
            f"{self.store.max_bytes // 1024 // 1024}MB)"
        )

    def cmd_store(
        self,
        key: str,
        value: str,
        weight: Optional[float] = None,
        ttl: Optional[float] = None,
        slot_id: Optional[str] = None,
        task_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> MemoryBlock:
        tid = tenant_id or self.store.tenant_id
        block = MemoryBlock(
            key=key,
            value=value,
            weight=weight if weight is not None else self.config.default_weight,
            ttl=ttl if ttl is not None else self.config.default_ttl,
            slot_id=slot_id,
            task_id=task_id,
            tenant_id=tid,
        )
        self.store.store(block)
        self.persistent.save_block(block)
        self.audit.log_store(key=key, tenant_id=tid, extra={"slot_id": slot_id})
        return block

    def cmd_recall(
        self,
        keyword: Optional[List[str]] = None,
        slot_id: Optional[str] = None,
        top_n: Optional[int] = None,
        max_tokens: Optional[int] = None,
        context: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict:
        tid = tenant_id or self.store.tenant_id
        text = context or " ".join(keyword) if keyword else ""
        bundle = self.strategy.recall(
            context_text=text,
            top_n=top_n or self.config.recall_top_n,
            max_tokens=max_tokens or self.config.recall_max_tokens,
            slot_id=slot_id,
            tenant_id=tid,
        )
        self.audit.log_recall(
            keyword_count=len(keyword) if keyword else 0,
            result_count=len(bundle.blocks),
            tenant_id=tid,
        )
        return {
            "blocks": [
                {
                    "key": b.key,
                    "value": b.value,
                    "weight": b.weight,
                    "slot_id": b.slot_id,
                    "task_id": b.task_id,
                    "tenant_id": b.tenant_id,
                    "created_at": b.created_at.isoformat(),
                    "hot_score": round(b.hot_score, 4),
                }
                for b in bundle.blocks
            ],
            "total_tokens": bundle.total_tokens,
            "count": len(bundle.blocks),
        }

    def cmd_forget(
        self,
        key: Optional[str] = None,
        slot_id: Optional[str] = None,
        all_: bool = False,
        tenant_id: Optional[str] = None,
    ) -> int:
        tid = tenant_id or self.store.tenant_id
        count = 0
        if all_:
            count = len(self.store.get_tenant_keys(tid))
            self.store.clear(tenant_id=tid)
            self.persistent.clear(tenant_id=tid)
        elif slot_id:
            blocks = self.store.get_slot_blocks(slot_id, tenant_id=tid)
            count = len(blocks)
            for b in blocks:
                self.store.delete(b.key)
            self.persistent.delete_slot(slot_id, tenant_id=tid)
        elif key:
            self.store.delete(key)
            self.persistent.delete_block(key)
            count = 1
        self.audit.log_forget(key=key, count=count, tenant_id=tid)
        return count

    def cmd_list(
        self,
        slot_id: Optional[str] = None,
        include_expired: bool = False,
        tenant_id: Optional[str] = None,
    ) -> List[Dict]:
        tid = tenant_id or self.store.tenant_id
        blocks = self.store.list_blocks(
            slot_id=slot_id, include_expired=include_expired, tenant_id=tid
        )
        return [
            {
                "key": b.key,
                "value": b.value[:200],
                "weight": b.weight,
                "slot_id": b.slot_id,
                "task_id": b.task_id,
                "tenant_id": b.tenant_id,
                "created_at": b.created_at.isoformat(),
                "expired": b.is_expired,
                "access_count": b.access_count,
                "hot_score": round(b.hot_score, 4),
            }
            for b in blocks
        ]

    def cmd_stats(self, tenant_id: Optional[str] = None) -> Dict:
        tid = tenant_id or self.store.tenant_id
        memory_stats = self.store.get_stats(tenant_id=tid)
        return {
            "memory": {
                "tenant_id": memory_stats["tenant_id"],
                "blocks_count": memory_stats["blocks_count"],
                "total_blocks_count": memory_stats["total_blocks_count"],
                "used_mb": round(memory_stats["used_bytes"] / 1024 / 1024, 2),
                "max_mb": round(memory_stats["max_bytes"] / 1024 / 1024, 2),
                "usage_ratio": memory_stats["usage_ratio"],
                "hit_rate": memory_stats["hit_rate"],
                "hit_count": memory_stats["hit_count"],
                "miss_count": memory_stats["miss_count"],
                "rejected_count": memory_stats["rejected_count"],
                "admission_pressure": {
                    "ratio": memory_stats["admission_pressure_ratio"],
                    "min_weight": memory_stats["admission_min_weight"],
                },
            },
            "db": {
                "path": self.config.db_path,
                "blocks_count": self.persistent.get_count(tenant_id=tid),
            },
            "config": self.config.to_dict(),
        }

    def cmd_config(self, profile: Optional[str] = None) -> Dict:
        if profile:
            if profile not in PRESETS:
                valid = list(PRESETS.keys())
                raise ValueError(f"Unknown profile '{profile}'. Choose from: {valid}")
            self.config.profile = profile
            self.config.max_memory_mb = None
            self.config.__post_init__()
            self.config.save()
        return self.config.to_dict()

    def cmd_audit(
        self,
        action: Optional[str] = None,
        tenant_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict:
        events = self.audit.query(action=action, tenant_id=tenant_id, limit=limit)
        return {"events": events, "count": len(events)}

    def cmd_sync(self, direction: str = "auto") -> Dict:
        engine = self._sync_engine()
        try:
            result = engine.sync(direction=direction)
            result["status"] = "ok"
            return result
        finally:
            engine.close()

    def cmd_sync_status(self) -> Dict:
        engine = self._sync_engine()
        try:
            return {"status": "ok"} | engine.status()
        finally:
            engine.close()

    def cmd_mark_important(self, note_id: str) -> Dict:
        zk = ZKDatabase(self._zk_db_path())
        try:
            ok = zk.mark_note_important(note_id)
            return {"status": "ok" if ok else "error", "note_id": note_id}
        finally:
            zk.close()

    def cmd_search(
        self,
        query: str,
        folder: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        tags: Optional[List[str]] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        limit_svm: int = 20,
        limit_zk: int = 20,
        tenant_id: Optional[str] = None,
    ) -> Dict:
        tid = tenant_id or self.store.tenant_id
        keywords = query.split() if query.strip() else ["zk_imported", "zk_recent", "zk_evergreen"]
        svm_blocks = self.store.search_by_keywords(keywords, tenant_id=tid)[:limit_svm]
        zk = ZKDatabase(self._zk_db_path())
        try:
            zk_blocks = zk.search_notes(
                query=query,
                folder=folder,
                min_confidence=min_confidence,
                max_confidence=max_confidence,
                tags=tags,
                created_after=created_after,
                created_before=created_before,
                limit=limit_zk,
                tenant_id=tid,
            )
        finally:
            zk.close()
        return {
            "svm": [
                {
                    "key": b.key,
                    "value": b.value[:200],
                    "weight": b.weight,
                    "slot_id": b.slot_id,
                    "hot_score": round(b.hot_score, 4),
                }
                for b in svm_blocks
            ],
            "zk": [
                {
                    "key": b.key,
                    "value": b.value[:200],
                    "weight": b.weight,
                    "zk_note_id": b.zk_note_id,
                }
                for b in zk_blocks
            ],
            "count_svm": len(svm_blocks),
            "count_zk": len(zk_blocks),
        }

    def close(self) -> None:
        self.persistent.close()
        self.audit.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="svm",
        description="Structured Visual Memory - LLM memory management",
    )
    parser.add_argument("--version", action="version", version=f"svm {__version__}")
    parser.add_argument("--log-level", default=None, help="Log level (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    p_store = sub.add_parser("store", help="Store a memory block")
    p_store.add_argument("--key", required=True)
    p_store.add_argument("--value", required=True)
    p_store.add_argument("--weight", type=float)
    p_store.add_argument("--ttl", type=float)
    p_store.add_argument("--slot", dest="slot_id")
    p_store.add_argument("--task", dest="task_id")
    p_store.add_argument("--tenant", dest="tenant_id")

    p_recall = sub.add_parser("recall", help="Recall memory blocks")
    p_recall.add_argument("--keyword", action="append", dest="keyword")
    p_recall.add_argument("--slot", dest="slot_id")
    p_recall.add_argument("--top-n", type=int)
    p_recall.add_argument("--max-tokens", type=int)
    p_recall.add_argument("--context")
    p_recall.add_argument("--tenant", dest="tenant_id")

    p_forget = sub.add_parser("forget", help="Forget memory blocks")
    p_forget.add_argument("--key")
    p_forget.add_argument("--slot", dest="slot_id")
    p_forget.add_argument("--all", action="store_true", dest="all_")
    p_forget.add_argument("--tenant", dest="tenant_id")

    p_list = sub.add_parser("list", help="List memory blocks")
    p_list.add_argument("--slot", dest="slot_id")
    p_list.add_argument("--include-expired", action="store_true")
    p_list.add_argument("--tenant", dest="tenant_id")

    p_stats = sub.add_parser("stats", help="Show memory statistics")

    p_config = sub.add_parser("config", help="View or set configuration")
    p_config.add_argument("--profile", choices=list(PRESETS.keys()))

    p_audit = sub.add_parser("audit", help="View audit log")
    p_audit.add_argument("--action")
    p_audit.add_argument("--tenant", dest="tenant_id")
    p_audit.add_argument("--limit", type=int, default=100)

    p_sync = sub.add_parser("sync", help="Sync memory with Zettelkasten")
    p_sync.add_argument(
        "direction", nargs="?",
        choices=["auto", "to-zk", "from-zk"],
        default="auto",
        help="Sync direction",
    )

    p_sync_status = sub.add_parser("sync-status", help="Show sync status")

    p_mark = sub.add_parser("mark-important", help="Mark a ZK note as important")
    p_mark.add_argument("--note-id", required=True)

    p_search = sub.add_parser("search", help="Search SVM and ZK notes")
    p_search.add_argument("query", nargs="?", default="", help="Keyword search query")
    p_search.add_argument("--folder")
    p_search.add_argument("--min-confidence", type=float)
    p_search.add_argument("--max-confidence", type=float)
    p_search.add_argument("--tag", action="append", dest="tags")
    p_search.add_argument("--created-after")
    p_search.add_argument("--created-before")
    p_search.add_argument("--limit-svm", type=int, default=20)
    p_search.add_argument("--limit-zk", type=int, default=20)
    p_search.add_argument("--tenant", dest="tenant_id")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.log_level:
        logging.getLogger("svm").setLevel(getattr(logging, args.log_level.upper()))
        logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    app = SVMApp()

    try:
        if args.command == "store":
            result = app.cmd_store(
                key=args.key,
                value=args.value,
                weight=args.weight,
                ttl=args.ttl,
                slot_id=args.slot_id,
                task_id=args.task_id,
                tenant_id=args.tenant_id,
            )
            output = {
                "status": "ok",
                "key": result.key,
                "slot_id": result.slot_id,
                "tenant_id": result.tenant_id,
            }

        elif args.command == "recall":
            result = app.cmd_recall(
                keyword=args.keyword,
                slot_id=args.slot_id,
                top_n=args.top_n,
                max_tokens=args.max_tokens,
                context=args.context,
                tenant_id=args.tenant_id,
            )
            output = {"status": "ok"} | result

        elif args.command == "forget":
            count = app.cmd_forget(
                key=args.key,
                slot_id=args.slot_id,
                all_=args.all_,
                tenant_id=args.tenant_id,
            )
            output = {"status": "ok", "count": count}

        elif args.command == "list":
            blocks = app.cmd_list(
                slot_id=args.slot_id,
                include_expired=args.include_expired,
                tenant_id=args.tenant_id,
            )
            output = {"status": "ok", "blocks": blocks, "count": len(blocks)}

        elif args.command == "stats":
            output = {"status": "ok"} | app.cmd_stats()

        elif args.command == "config":
            result = app.cmd_config(profile=args.profile)
            output = {"status": "ok"} | result

        elif args.command == "audit":
            result = app.cmd_audit(
                action=args.action,
                tenant_id=args.tenant_id,
                limit=args.limit,
            )
            output = {"status": "ok"} | result

        elif args.command == "sync":
            result = app.cmd_sync(direction=args.direction)
            output = {"status": "ok"} | result

        elif args.command == "sync-status":
            output = app.cmd_sync_status()

        elif args.command == "mark-important":
            output = app.cmd_mark_important(note_id=args.note_id)

        elif args.command == "search":
            result = app.cmd_search(
                query=args.query or "*",
                folder=args.folder,
                min_confidence=args.min_confidence,
                max_confidence=args.max_confidence,
                tags=args.tags,
                created_after=args.created_after,
                created_before=args.created_before,
                limit_svm=args.limit_svm,
                limit_zk=args.limit_zk,
                tenant_id=args.tenant_id,
            )
            output = {"status": "ok"} | result

        else:
            parser.print_help()
            return 1

        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            _print_human(output, args.command)

        return 0

    except SVMError as e:
        logger.error(str(e))
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        return 1

    except Exception as e:
        logger.error(str(e))
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        return 1

    finally:
        app.close()


def _print_human(output: dict, command: str) -> None:
    if output.get("status") != "ok":
        print(f"Error: {output.get('message', 'unknown')}")
        return

    if command == "stats":
        m = output.get("memory", {})
        db = output.get("db", {})
        cfg = output.get("config", {})
        print(f"Tenant:  {m.get('tenant_id', 'default')}")
        print(f"Memory:  {m.get('blocks_count', 0)} blocks (total: {m.get('total_blocks_count', 0)})")
        print(f"         {m.get('used_mb', 0)}MB / {m.get('max_mb', 0)}MB ({m.get('usage_ratio', 0)*100:.1f}%)")
        print(f"Hit Rate: {m.get('hit_rate', 0)*100:.1f}%  (hits={m.get('hit_count')} misses={m.get('miss_count')})")
        reject = m.get('rejected_count', 0)
        if reject:
            print(f"Admission: {reject} rejected  (pressure > {m.get('admission_pressure', {}).get('ratio', 0.8)*100:.0f}% + weight < {m.get('admission_pressure', {}).get('min_weight', 0.1)})")
        print(f"DB:      {db.get('path')} ({db.get('blocks_count')} blocks)")
        print(f"Profile: {cfg.get('profile')}")

    elif command == "list":
        blocks = output.get("blocks", [])
        print(f"Total: {output.get('count', 0)} blocks")
        print("-" * 60)
        for b in blocks:
            expired = " [EXPIRED]" if b.get("expired") else ""
            print(f"  [{b['key']}]{expired}  score={b['hot_score']}  weight={b['weight']}  tenant={b.get('tenant_id', 'default')}")
            print(f"    {b['value'][:120]}")

    elif command == "recall":
        blocks = output.get("blocks", [])
        print(f"Recalled {output.get('count', 0)} blocks ({output.get('total_tokens', 0)} tokens)")
        print("-" * 60)
        for b in blocks:
            print(f"  [{b['key']}]  score={b['hot_score']}  tenant={b.get('tenant_id', 'default')}")
            print(f"    {b['value'][:120]}")

    elif command == "store":
        print(f"Stored key={output['key']} slot={output.get('slot_id')} tenant={output.get('tenant_id', 'default')}")

    elif command == "forget":
        print(f"Forgot {output.get('count', 0)} blocks")

    elif command == "config":
        print("Configuration:")
        for k, v in output.items():
            if k != "status":
                print(f"  {k}: {v}")

    elif command == "audit":
        events = output.get("events", [])
        print(f"Audit log: {output.get('count', 0)} events")
        print("-" * 80)
        for e in events:
            print(f"  [{e['timestamp']}] {e['action']} by {e['actor']} (tenant={e['tenant_id']})")
            if e['details']:
                print(f"    details: {e['details']}")

    elif command == "sync":
        print("Sync completed:")
        for k, v in output.items():
            if k != "status":
                print(f"  {k}: {v}")

    elif command == "sync-status":
        print("Sync Status:")
        for k, v in output.items():
            if k != "status":
                print(f"  {k}: {v}")

    elif command == "mark-important":
        print(f"Note {output.get('note_id')}: {'marked important' if output.get('status') == 'ok' else 'failed'}")

    elif command == "search":
        svm = output.get("svm", [])
        zk = output.get("zk", [])
        print(f"SVM: {len(svm)} results | ZK: {len(zk)} results")
        print("=" * 60)
        if svm:
            print("--- SVM Memory ---")
            for b in svm:
                print(f"  [{b['key']}]  score={b['hot_score']}  weight={b['weight']}")
                print(f"    {b['value'][:120]}")
        if zk:
            print("--- Zettelkasten ---")
            for b in zk:
                print(f"  [{b['key']}]  weight={b['weight']}  zk_id={b['zk_note_id']}")
                print(f"    {b['value'][:120]}")


if __name__ == "__main__":
    sys.exit(main())
