# Zettelkasten 插件 — SVM 集成需求

## 背景

SVM (Structured Visual Memory) 是内存级键值存储，用于 LLM Agent 的极速记忆存取。
Zettelkasten 是持久化知识笔记系统。两者需要双向同步：

```
SVM (内存, 极速)  ←→  Zettelkasten (SQLite, 持久化)
```

## 当前方案（SVM 侧已实现，不改 ZK）

### SVM→ZK 备份
- SVM 通过直接读/写 ZK 的 SQLite 数据库实现同步
- 约定标签 `svm:synced` 标记 SVM 同步创建的笔记
- 约定标签 `svm:hot` 标记"重要"笔记
- 不依赖 ZK 的 MCP 工具

### ZK→SVN 热加载
- SVM 直接读 ZK 的 `zettel_notes` 表
- 筛选条件：`confidence >= 0.9`、`folder = 'zettels'`、`glow_status IN ('evergreen','active')`、近 7 天创建/更新

## 需要 ZK 侧新增的功能

按优先级排列：

### P0 — 重要性标记机制

**问题**：ZK 没有字段标记笔记为"重要"，SVM 需要知道哪些笔记应该热加载到内存。

**方案 A（推荐，改动最小）**：ZK 工具层识别约定标签 `svm:hot`
- 在 `zk_create_note` / `zk_update_note` 中，如果 tags 包含 `svm:hot`，在 UI 或回复中显示特殊标记
- 不需要改数据库 schema

**方案 B（更完整）**：新增 `priority` 字段
- `zettel_notes` 加列 `priority TEXT CHECK(priority IN ('high','medium','low','normal')) DEFAULT 'normal'`
- zk_create_note / zk_update_note 暴露 `--priority` 参数
- zk_search_notes 暴露 `--priority` 过滤参数

### P1 — 搜索工具暴露日期范围过滤

**问题**：`zk_search_notes` 只接受 `query` 和 `limit`，底层 `query()` 支持 `createdAfter`/`createdBefore` 但工具层没暴露。

**需求**：
- `zk_search_notes` 新增参数：`--created-after` / `--created-before`（ISO 日期字符串）
- `zk_search_notes` 新增参数：`--updated-after` / `--updated-before`

### P2 — 搜索工具暴露标签过滤

**问题**：无法按标签搜索笔记。

**需求**：
- `zk_search_notes` 新增参数：`--tag`（可重复，多标签取交集）
- 底层 `query()` 已有标签子查询支持，只需工具层暴露

### P3 — 搜索工具暴露置信度/文件夹过滤

**问题**：搜索无法按文件夹或置信度范围过滤。

**需求**：
- `zk_search_notes` 新增参数：`--folder`（inbox/references/zettels/archive）
- `zk_search_notes` 新增参数：`--min-confidence` / `--max-confidence`

### P4 — 创建/更新工具暴露更多字段

**问题**：`zk_create_note` 只能设 `title/content/tags/confidence/source`，无法设 `folder/status/type`。

**需求**：
- `zk_create_note` 新增参数：`--folder`（可选，覆盖置信度路由）
- `zk_create_note` 新增参数：`--status`（可选）
- `zk_update_note` 新增参数：`--folder`、`--status`

## 不需要改的（SVM 侧已解决）

| 功能 | SVM 方案 |
|------|---------|
| 批量创建笔记 | 直接批量 INSERT 到 ZK 数据库 |
| 读取笔记完整信息 | 直接 SELECT 读取 ZK 数据库 |
| 标记重要性 | 约定标签 `svm:hot` |
| 非空闲时不做同步 | SVM 侧空闲检测 |
| 热分衰减 | SVM 侧 hot_score 衰减策略 |

## ZK 侧实现状态（2026-06-28 已完成）

以下功能已在 `zettelkasten` 项目 `master` 分支（commit `7d1a460`）实现，1724 测试全部通过：

### 已上线

| 优先级 | 功能 | MCP 工具参数 | CLI 参数 |
|--------|------|-------------|----------|
| P0 | `svm:hot` 标签识别 | `zk_create_note` / `zk_update_note` 返回 `hot: true` | — |
| P1 | 日期范围过滤 | `zk_search_notes` → `createdAfter`/`createdBefore`/`updatedAfter`/`updatedBefore` | `--created-after`/`--created-before`/`--updated-after`/`--updated-before` |
| P2 | 标签过滤 | `zk_search_notes` → `tags` (string[], 交集) | `--tag` (可重复) |
| P3 | 文件夹/置信度过滤 | `zk_search_notes` → `folder`/`minConfidence`/`maxConfidence` | `--folder`/`--min-confidence`/`--max-confidence` |
| P4 | 创建/更新暴露更多字段 | `zk_create_note` → `folder`/`status`；`zk_update_note` → `folder`/`status` | `zk new --folder --status` |

### 设计要点（供 SVM 开发参考）

1. **搜索 + 过滤的语义**：FTS 关键词与结构化条件取 **AND 交集**。传空 query 或 `*` 可匹配全部。
2. **`svm:hot` 识别**：ZK 工具层在 `zk_create_note` / `zk_update_note` 返回 JSON 中增加 `hot: true` 字段（当 tags 包含 `svm:hot` 时）。
3. **`--folder` 覆盖优先级**：显式传入 `folder` 时**跳过置信度路由**，否则按 `confidence` 自动路由（`>=0.7 → zettels`、`>=0.4 → references`、`<0.4 → inbox`）。
4. **`--status` 默认值**：`zk_create_note` 不传 `status` 时，默认 `FLEETING`；更新时只改传入的字段。
5. **搜索底层**：`NoteRepository.search()` 接受 `filters?: QueryNotesParams`，FTS MATCH + 额外 WHERE 条件的 SQL 组合，LIKE fallback 也同步支持过滤。

### 未实现（按需后续）

- P0 方案 B（`priority` 字段）— 当前用方案 A（标签驱动），如果 SVM 需要再改
- `--type` 参数（`atomic/structure/source`）— 创建时默认 `atomic`，工具层未暴露
