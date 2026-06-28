# Changelog

## [0.2.1] - 2026-06-28

### Fixed
- **FTS5 search query**: corrected `n.rowid IN (SELECT rowid FROM zettel_fts ...)` to `n.id IN (SELECT id FROM zettel_fts ...)` — FTS5 rowid is auto-generated and unrelated to zettel_notes rowid; the correct join key is the TEXT `id` column
- **KeywordMatcher return type**: tuples changed to plain strings (backward-compatible)
- **`load_block()` tenant-awareness**: now correctly filters by tenant_id
- **Test mock column names**: `link_count`/`access_count` → `backlink_count`/`outgoing_link_count` to match actual ZK schema

### Added
- Data safety section in README (schema compatibility guarantees)
- `scripts/quick-install.sh` — curl|bash one-command install for AI Agent

## [0.2.0] - 2026-06-28

### Added
- Sync engine (`svm.sync.engine`, `svm.sync.zk_sync`): bidirectional SVM ↔ Zettelkasten sync
- CLI commands: `sync`, `sync-status`, `mark-important`, `search`
- Evict-sync protection: blocks synced to ZK before eviction
- Admission control: configurable min-weight and pressure ratio to protect existing memories
- `svm import` command: migrate old OpenClaw main.sqlite chunks to SVM blocks (idempotent)
- MCP server integrated at `svm/mcp_server.py` (moved from `~/.openclaw/`)
- Comprehensive test suite for sync engine (8 tests for import, 18 for sync)
- `svm-deploy` skill for agent-based one-command deployment
- CHANGELOG.md and version management

### Changed
- Project renamed from `svm` to `memory_plus` (pip install); Python module remains `svm`
- Dependencies `pyyaml` and `pyahocorasick` moved from optional to core
- MemoryBlock extended with `zk_note_id` and `synced_at` fields
- PersistentStore schema migrated with sync columns
- RAM profiles updated with admission control parameters
- All Docker containers (Hermes + OpenClaw 3 versions) have SVM installed

## [0.1.0] - 2026-06-20

### Added
- Initial MVP: MemoryBlock, MemoryStore (LRU), SQLite persistence, KeywordMatcher (Aho-Corasick)
- CLI with store/recall/forget/list/stats/config/audit commands
- Multi-tenant isolation on all storage paths
- Audit logging (SQLite-backed)
- Exception hierarchy (SVMError, BlockNotFoundError, ConfigError, TenantMismatchError)
- Config presets with auto-detect system memory
- 58 unit tests passing
- Performance benchmarks (553K blocks/sec store, 52K matches/sec AC)
- MCP server at `~/.openclaw/svm-mcp-server.py`
- SVM skill at `~/.openclaw/skills/svm-memory/SKILL.md`
- Docker deployment docs
- Hermes container integration via MCP Server (6 tools, 49ms)
- OpenClaw 3-version container test environment
