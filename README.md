# Memory Plus

Structured Visual Memory (SVM) — a memory management component for LLM Agent frameworks, with Zettelkasten synchronization.

## Features

- **Memory Store**: In-memory LRU cache with SQLite persistence, multi-tenant isolation
- **Keyword Matching**: Aho-Corasick fast multi-pattern matching (pyahocorasick or pure-Python fallback)
- **Audit Logging**: SQLite-backed event log for store/recall/forget/config operations
- **Zettelkasten Sync**: Bidirectional sync — SVM→ZK (cold backup) + ZK→SVM (hot-load important/recent/evergreen notes)
- **Evict-Sync Protection**: Blocks are synced to ZK before eviction
- **Admission Control**: Protects high-weight memories from low-weight bulk writes
- **Import**: Migrate existing OpenClaw memory chunks (`svm import`)
- **MCP Server**: stdio-based MCP server for integration with agent frameworks
- **CLI**: Full command-line interface with JSON output

## CLI Usage

```bash
svm store --key my_key --value "content"
svm recall --keyword kw1 --keyword kw2
svm sync auto
svm import --source ~/.openclaw/memory/main.sqlite
svm search "keyword"
svm stats
```

## Install

```bash
pip install memory-plus
```

Or for development:

```bash
git clone <repo>
cd memory_plus
pip install -e ".[test]"
pytest tests/
```

## License

MIT
