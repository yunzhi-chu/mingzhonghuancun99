# 命中缓存99%

> AI 编程助手缓存命中率诊断、优化与监控 CLI 工具。

每次使用 AI 编程助手（Claude Code / Codex CLI / Hermes 等）时，都会发送一段上下文给 AI。如果这段上下文和上一次完全一样，AI 可以从**缓存**读取，不用重新计算。

**命中率越高 → 速度越快 → 成本越低。**

## 功能

- **检测** — 自动发现已安装的 AI 编程助手和 CC-Switch
- **分析** — 计算当前缓存命中率、请求量、成本
- **配置扫描** — 检查系统提示动态内容、记忆文件数量、技能/MCP 数量
- **交互修复** — 逐条展示优化建议，确认后自动执行
- **一键修复** — 合并过多记忆文件（自动备份，可回滚）
- **仪表盘** — 生成漂亮的 HTML 网页报告
- **多 Agent 支持** — 自动适配 Claude Code / Codex CLI / Hermes

## 安装

```bash
git clone https://github.com/yunzhi-chu/mingzhonghuancun99.git
cd mingzhonghuancun99
python -m cache_optimizer --help
```

要求 Python ≥ 3.10，零外部依赖。

## 快速上手

```bash
# 检测环境中已安装的 AI 编程助手
python -m cache_optimizer --detect

# 全流程优化：检测 → 获取数据 → 分析 → 交互修复
python -m cache_optimizer --optimize

# 从 CC-Switch 数据文件手动分析
python -m cache_optimizer --data data.txt

# 生成 HTML 仪表盘报告
python -m cache_optimizer --data data.txt --dashboard report.html

# 输出 JSON 格式（CI/CD 集成）
python -m cache_optimizer --data data.txt --json

# 预览记忆文件合并方案
python -m cache_optimizer --fix

# 执行记忆文件合并（自动备份）
python -m cache_optimizer --fix apply

# 检测 CC-Switch 状态和代理配置
python -m cache_optimizer --setup
```

## 支持的 AI 编程助手

| 名称 | 检测方式 | 配置扫描 |
|---|---|---|
| Claude Code | `~/.claude/` + settings.json | CLAUDE.md / 记忆文件 / MCP |
| Codex CLI | `~/.codex/` + 命令行 | AGENTS.md / memories / config.toml |
| Hermes | `~/.hermes/` + Python 包 | config.yaml / skills / ccr |

本工具自动检测已安装的 agent 并执行对应的配置扫描。

## 数据来源

本工具通过 **CC-Switch**（桌面应用）获取请求日志数据。CC-Switch 是一个本地代理工具，记录所有 AI API 请求的 token 消耗和缓存命中情况。数据存储在 `~/.cc-switch/cc-switch.db`（SQLite）。

没有 CC-Switch 也可以使用：从 CC-Switch 仪表盘复制请求日志，粘贴到工具中即可分析。

## 诊断指标

| 指标 | 说明 |
|---|---|
| **缓存命中率** | 当前值 vs 目标值（默认 99%） |
| **请求分析** | 总请求数、总 token 数、平均输入/输出/缓存 |
| **配置扫描** | 系统提示动态内容、记忆文件、技能、MCP 服务 |
| **成本预估** | 当前成本、优化后成本、预估每月节省 |
| **综合评分** | 0-100 分，综合命中率和配置健康度 |

## 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 配置健康，无需优化 |
| 1 | 存在可优化项或无数据 |
| 2 | 命中率严重偏低 |

适用于 CI/CD 集成检查。

## 项目结构

```
cache_optimizer/
  __init__.py          # 核心：数据解析、分析引擎、报告输出、修复、仪表盘、CLI
  __main__.py          # 入口
  agents.py            # AI 编程助手检测
  ccswitch_manager.py  # CC-Switch 对接：检测、数据库读取、代理配置
pyproject.toml         # 项目配置
```

## 许可证

MIT
