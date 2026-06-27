# Docker 部署信息（来自 Zettelkasten 项目）

> 复制自 `~/.openclaw/project/zettelkasten/environments/compat-testing/`
> 原项目文档: `docs/COMPAT_TEST_OPERATIONS.md`, `plans/zettelkasten-deployment-guide.md`

## 当前运行容器状态（截至 2026-06-27）

| 容器 | 版本 | 状态 | 端口 |
|------|------|------|------|
| openclaw-latest | OpenClaw 2026.6.10 | Up (healthy) | 18892:18789, 19092:9090 |
| openclaw-2026-4-23 | — | NOT EXISTS (volume 还在) | — |
| openclaw-2026-4-24 | — | NOT EXISTS (volume 还在) | — |
| hermes-latest | Hermes Agent v0.17.0 | Up | 8652:8642, 9129:9119 |

## 一键操作命令

### 查看状态
```bash
bash environments/compat-testing/scripts/manage-test-env.sh status
```

### 启动容器
```bash
bash environments/compat-testing/scripts/start-container.sh openclaw-2026-4-23
bash environments/compat-testing/scripts/start-container.sh openclaw-2026-4-24
bash environments/compat-testing/scripts/start-container.sh openclaw-latest
bash environments/compat-testing/scripts/start-container.sh hermes-latest
```

### 部署 Zettelkasten 插件
```bash
bash environments/compat-testing/scripts/deploy-zk-to-container.sh openclaw-latest
```

### 停止/重置
```bash
bash environments/compat-testing/scripts/manage-test-env.sh stop          # 停止
bash environments/compat-testing/scripts/manage-test-env.sh stop -v       # 停止+清数据
bash environments/compat-testing/scripts/manage-test-env.sh restart       # 重启
```

## 容器详情

### openclaw-latest (2026.6.10)
- Image: `ghcr.io/openclaw/openclaw:latest`
- 数据卷: `compat-testing_oc-latest-data` → `/home/node/.openclaw`
- 源码挂载: `/opt/zettelkasten-source` (只读)
- Python 3.11 可用
- Zettelkasten 插件已启用
- `memory-core` 插件已启用（内置记忆，SVM 的目标替代对象）

### hermes-latest (v0.17.0)
- Image: `nousresearch/hermes-agent:latest`
- 数据卷: `hermes-latest-data` → `/root/.hermes`
- Python 3.13.5 可用
- 命令: `sleep infinity`（保持存活）

## API Keys
- 存放位置: `~/.openclaw/project/zettelkasten-secrets/minimax.env`
- 注入方式: `start-container.sh` 自动加载

## Zettelkasten 插件配置
- Zettelkasten 插件路径: `/home/node/.openclaw/zettelkasten-plugin/plugin/index.ts`
- 数据库: `/home/node/.openclaw/zettelkasten/zettelkasten.db`
- 笔记目录: `/home/node/.openclaw/zettelkasten/notes/`
- 可用 CLI: `openclaw zk doctor`, `openclaw zk init`, `openclaw zk stats`

## 兼容测试注意事项
- OpenClaw 2026.6.x+ minimax provider 走 Anthropic 适配，`sk-cp-` 前缀 CN key 不兼容
- 需要配置 `minimax-openai` 自定义 provider（OpenAI-compatible, baseUrl `https://api.minimaxi.com/v1`）
- `openclaw agent --local` 在 2026.4.x 有挂起问题，测试用 `openclaw-latest`

## 原始参考文件
- `environments/compat-testing/docker-compose.yml` - Compose 定义
- `environments/compat-testing/scripts/start-container.sh` - 原生 docker run 启动脚本
- `environments/compat-testing/scripts/deploy-zk-to-container.sh` - 插件部署脚本
- `environments/compat-testing/scripts/manage-test-env.sh` - 环境管理脚本
- `plans/zettelkasten-deployment-guide.md` - 完整部署指南
- `plans/deployment-test-plan.md` - 测试计划
- `docs/COMPAT_TEST_OPERATIONS.md` - 日常操作 SOP
