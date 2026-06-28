<p align="center">
  <img src="docs/assets/memory_plus_rich_cover.png" alt="Memory Plus" width="100%">
</p>

# 🧠 Memory Plus

> **A memory management component for [OpenClaw](https://github.com/openclaw) and [Hermes Agent](https://github.com/nousresearch/hermes-agent)** — built on SVM (Structured Visual Memory) architecture with bidirectional Zettelkasten sync, giving AI Agents persistent, searchable structured memory.

**English** · [简体中文](README.md)

[![Version](https://img.shields.io/badge/version-v0.2.0-blue.svg)](https://github.com/cx2002302-lang/memory_plus/releases)
[![OpenClaw](https://img.shields.io/badge/OpenClaw-2026.4.x/2026.6.x-green.svg)](https://github.com/openclaw)
[![Hermes](https://img.shields.io/badge/Hermes%20Agent-v0.17.0-blueviolet.svg)](https://github.com/nousresearch/hermes-agent)
[![MCP Server](https://img.shields.io/badge/MCP-6%20Tools-orange.svg)](svm/mcp_server.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](pyproject.toml)

---

## ✨ Core Features

| Feature | Description |
|---------|-------------|
| 🧠 **Memory Store** | In-memory LRU cache with SQLite persistence, multi-tenant isolation |
| 🔍 **Keyword Matching** | Aho-Corasick multi-pattern engine (pyahocorasick / pure-Python fallback) |
| 📋 **Audit Logging** | SQLite-backed event log for store/recall/forget/config operations |
| 🔄 **Zettelkasten Sync** | Bidirectional sync: SVM→ZK (cold backup) + ZK→SVM (hot-load important/recent/evergreen notes) |
| 🛡️ **Evict-Sync Protection** | Auto-sync to ZK before LRU eviction, preventing data loss |
| ⚖️ **Admission Control** | Configurable min-weight and pressure threshold to protect high-value memories |
| 📥 **Import Migration** | `svm import` command to migrate old OpenClaw memory chunks to SVM blocks |
| 🔌 **MCP Server** | Built-in stdio MCP server for Hermes / OpenClaw agent integration |
| 🐳 **Docker Support** | 4 container environments with SVM pre-installed (Hermes + 3 OpenClaw versions) |
| 🎯 **CLI** | Full command-line interface with JSON output, cross-language consumable |

---

## ⚡ Performance

**Tested on**: Python 3.12.3, SQLite WAL  
**Scale**: 553K blocks/sec store · 52K matches/sec Aho-Corasick (5000 keywords)  
**Test Suite**: 80 unit tests passing ✅

---

> 🇨🇳 **Looking for Chinese documentation?** [点击这里查看简体中文介绍](README.md)

---

## 🚀 Quick Start

### Installation

```bash
pip install memory-plus
```

Or from source (recommended for development):

```bash
git clone https://github.com/cx2002302-lang/memory_plus.git
cd memory_plus
pip install -e ".[test]"

# Run tests
pytest tests/
```

### CLI Usage

```bash
# Store a memory
svm store --key my_key --value "memory content"

# Recall by keywords
svm recall --keyword kw1 --keyword kw2

# Sync with Zettelkasten
svm sync auto

# Import old memories
svm import --source ~/.openclaw/memory/main.sqlite

# Search (SVM + ZK)
svm search "keyword"

# View stats
svm stats
```

### Docker Deployment

```bash
# Use the svm-deploy skill (install skill first)
svm-deploy

# Or mount manually:
#   SVM database: ~/.openclaw/svm/memory.db
#   ZK database: ~/.openclaw/zettelkasten/zettelkasten.db
```

---

## 🧩 MCP Tools (for AI Agents)

| Tool | Permission | Description |
|------|------------|-------------|
| `svm_store` | Write | Store a memory block |
| `svm_recall` | Read | Recall memory blocks by keywords |
| `svm_forget` | Write | Delete a specific memory block |
| `svm_list` | Read | List all memory blocks |
| `svm_stats` | Read | Get memory statistics |
| `svm_audit` | Read | Query audit log |

---

## 📁 Project Structure

```
memory_plus/
├── svm/                     # Python module
│   ├── __init__.py          # Version
│   ├── cli.py               # CLI entry
│   ├── config.py            # Config management (presets, auto-detect memory)
│   ├── audit.py             # Audit log
│   ├── exceptions.py        # Exception hierarchy
│   ├── injector.py          # Context injector
│   ├── mcp_server.py        # MCP server
│   ├── models/              # Data models
│   │   └── block.py         # MemoryBlock (core)
│   ├── store/               # Storage layer
│   │   ├── memory_store.py  # In-memory LRU cache
│   │   └── persistent.py    # SQLite persistence
│   ├── sync/                # Zettelkasten sync engine
│   │   ├── engine.py        # Sync orchestrator
│   │   └── zk_sync.py       # ZK database reader/writer
│   └── trigger/             # Retrieval triggers
│       ├── matcher.py       # Aho-Corasick keyword matcher
│       └── strategy.py      # Recall strategy
├── tests/                   # Test suite
│   ├── test_basic.py        # 58 basic tests
│   ├── test_import.py       # 8 import tests
│   ├── test_sync.py         # 18 sync tests
│   └── test_perf.py         # Performance benchmarks
├── image/                   # Cover images
├── docs/                    # Documentation
├── CHANGELOG.md
├── LICENSE
└── README.md (README.en.md)
```

---

## 📜 License

[MIT](LICENSE) © Memory Plus Contributors
