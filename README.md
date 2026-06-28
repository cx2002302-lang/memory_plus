<p align="center">
  <img src="docs/assets/memory_plus_rich_cover.png" alt="Memory Plus" width="100%">
</p>

# 🧠 Memory Plus

> **一个为 [OpenClaw](https://github.com/openclaw) 和 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 设计的记忆管理组件**，基于 SVM（Structured Visual Memory）架构，集成 Zettelkasten 知识笔记双向同步，让 AI Agent 拥有持久化、可检索的结构化记忆。

[English](README.en.md) · **简体中文**

[![Version](https://img.shields.io/badge/version-v0.2.0-blue.svg)](https://github.com/cx2002302-lang/memory_plus/releases)
[![OpenClaw](https://img.shields.io/badge/OpenClaw-2026.4.x/2026.6.x-green.svg)](https://github.com/openclaw)
[![Hermes](https://img.shields.io/badge/Hermes%20Agent-v0.17.0-blueviolet.svg)](https://github.com/nousresearch/hermes-agent)
[![MCP Server](https://img.shields.io/badge/MCP-6%20Tools-orange.svg)](svm/mcp_server.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](pyproject.toml)

---

## ✨ 核心功能

| 功能 | 描述 |
|------|------|
| 🧠 **内存存储** | 内存 LRU 缓存 + SQLite 持久化，支持多租户隔离 |
| 🔍 **关键词匹配** | Aho-Corasick 多模式匹配引擎（pyahocorasick / 纯 Python 回退） |
| 📋 **审计日志** | SQLite 存储的 store/recall/forget/config 操作事件日志 |
| 🔄 **Zettelkasten 同步** | 双向同步：SVM→ZK（冷数据备份）+ ZK→SVM（热加载重要/近期/常青笔记） |
| 🛡️ **淘汰保护** | LRU 淘汰前自动同步到 ZK，防止数据丢失 |
| ⚖️ **准入控制** | 可配置最低权重和压力阈值，保护高价值记忆 |
| 📥 **导入迁移** | `svm import` 命令，将旧版 OpenClaw 记忆 chunks 迁移为 SVM 内存块 |
| 🔌 **MCP Server** | 内置 stdio 协议的 MCP 服务，接入 Hermes / OpenClaw 等 Agent 框架 |
| 🐳 **Docker 支持** | 4 种容器环境预装 SVM（Hermes + 3 版本 OpenClaw） |
| 🎯 **命令行** | 完整的 CLI 界面，支持 JSON 输出，跨语言调用 |

---

## ⚡ 性能基准

**测试环境**: Python 3.12.3, SQLite WAL  
**测试规模**: 553K blocks/sec 存储 · 52K matches/sec Aho-Corasick（5000 关键词）  
**当前测试套件**: 80 个单元测试全部通过 ✅

---

> 🇺🇸 **Looking for English documentation?** [Click here for English](README.en.md)

---

## 🚀 快速开始

### AI Agent 一句话安装

```bash
curl -fsSL https://raw.githubusercontent.com/cx2002302-lang/memory_plus/master/scripts/quick-install.sh | bash
```

### pip 安装

```bash
pip install memory-plus
```

或从源码安装（推荐开发模式）：

```bash
git clone https://github.com/cx2002302-lang/memory_plus.git
cd memory_plus
pip install -e ".[test]"

# 运行测试
pytest tests/
```

### CLI 基本用法

```bash
# 存储记忆
svm store --key my_key --value "记忆内容"

# 检索记忆
svm recall --keyword kw1 --keyword kw2

# 与 Zettelkasten 同步
svm sync auto

# 导入旧版记忆
svm import --source ~/.openclaw/memory/main.sqlite

# 搜索（SVM + ZK）
svm search "关键词"

# 查看状态
svm stats
```

### Docker 部署

```bash
# 使用 svm-deploy skill（需要先安装 skill）
svm-deploy

# 或手动挂载：
#   svm 数据库路径: ~/.openclaw/svm/memory.db
#   ZK 数据库路径: ~/.openclaw/zettelkasten/zettelkasten.db
```

---

## 🧩 MCP 工具（用于 AI Agent）

| 工具 | 权限 | 描述 |
|------|------|------|
| `svm_store` | 写入 | 存储一个记忆块 |
| `svm_recall` | 读取 | 按关键词检索记忆块 |
| `svm_forget` | 写入 | 删除指定记忆块 |
| `svm_list` | 读取 | 列出所有记忆块 |
| `svm_stats` | 读取 | 获取内存统计信息 |
| `svm_audit` | 读取 | 查询审计日志 |

---

## 🛡️ 数据安全

Memory Plus 与 Zettelkasten 双向同步遵循以下安全原则：

| 操作 | 安全策略 |
|------|---------|
| **SVM → ZK 写入** | 仅 INSERT，永不 UPDATE/DELETE/DROP |
| **ZK → SVM 读取** | 只读 QUERY，不修改 ZK 数据 |
| **标签写入** | `INSERT OR IGNORE`，不覆盖已有标签 |
| **淘汰保护** | LRU 淘汰前先同步到 ZK，防止数据丢失 |
| **准入控制** | 内存使用率 ≥ 80% 时拒绝低权重（< 0.1）写操作 |
| **FTS5 搜索** | 使用 `n.id IN (SELECT id FROM zettel_fts ...)` 确保 rowid 正确映射 |

> ⚠ **重要警告**：切勿在已有数据的 ZK 数据库上运行 `openclaw zk init`。
> `migrateNotesTableForArchive()` 可能重新创建 `zettel_notes` 表并导致数据丢失。
> 详见 [Schema 兼容性文档](../../docs/architecture.md#schema-compatibility)。

---

## 📁 项目结构

```
memory_plus/
├── svm/                     # Python 模块
│   ├── __init__.py          # 版本号
│   ├── cli.py               # CLI 入口
│   ├── config.py            # 配置管理（预设、自动检测内存）
│   ├── audit.py             # 审计日志
│   ├── exceptions.py        # 异常体系
│   ├── injector.py          # 上下文注入器
│   ├── mcp_server.py        # MCP 服务
│   ├── models/              # 数据模型
│   │   └── block.py         # MemoryBlock（核心内存块）
│   ├── store/               # 存储层
│   │   ├── memory_store.py  # 内存 LRU 缓存
│   │   └── persistent.py    # SQLite 持久化
│   ├── sync/                # Zettelkasten 同步引擎
│   │   ├── engine.py        # 同步编排
│   │   └── zk_sync.py       # ZK 数据库读写
│   └── trigger/             # 检索触发
│       ├── matcher.py       # Aho-Corasick 关键词匹配
│       └── strategy.py      # 检索策略
├── tests/                   # 测试套件
│   ├── test_basic.py        # 58 个基础测试
│   ├── test_import.py       # 8 个导入测试
│   ├── test_sync.py         # 18 个同步测试
│   └── test_perf.py         # 性能基准测试
├── image/                   # 配图
├── docs/                    # 文档
├── CHANGELOG.md
├── LICENSE
└── README.md
```

---

## 📜 许可证

[MIT](LICENSE) © Memory Plus Contributors
