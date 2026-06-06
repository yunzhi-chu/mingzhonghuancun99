# 命中缓存99%

> AI 编程助手缓存命中率诊断、优化与监控 CLI 工具。
>
> **命中率越高 → 速度越快 → 成本越低。**

每次使用 AI 编程助手（Claude Code / Codex CLI / Hermes 等）时，都会发送一段"上下文"给 AI。如果这段上下文和上一次完全一样，AI 可以从**缓存**读取，不用重新计算。

本工具帮你：检测已安装的 AI 助手 → 从 CC-Switch 读取请求数据 → 分析缓存命中率 → 扫描配置问题 → 一键修复 → 生成网页报告。

## 快速开始

```bash
# 1. 下载
git clone https://github.com/yunzhi-chu/mingzhonghuancun99.git
cd mingzhonghuancun99

# 2. 检测环境中已安装的 AI 编程助手
python -m cache_optimizer --detect

# 3. 完整优化流程
python -m cache_optimizer --optimize
```

要求 Python ≥ 3.10，零外部依赖。

也可 pip 安装：
```bash
pip install -e .
cache-optimizer --detect
```

## 功能一览

| 命令 | 功能 |
|---|---|
| `--detect` | 检测已安装的 AI 助手 + CC-Switch |
| `--optimize` | 全流程: 检测 → 取数据 → 分析 → 交互修复 |
| `--data <file>` | 从文件读取 CCSwitch 数据并分析 |
| `--dashboard [file]` | 生成 HTML 仪表盘报告 |
| `--json` | 输出 JSON 格式 (CI/CD 集成) |
| `--fix [dry-run\|apply]` | 记忆文件合并 (自动备份, 可回滚) |
| `--setup` | 检测 CC-Switch 状态和代理配置 |

### 使用示例

```bash
# 分析今日数据并生成网页报告
python -m cache_optimizer --dashboard report.html

# 导出 JSON 给其他工具使用
python -m cache_optimizer --data data.txt --json

# 预览记忆文件合并方案
python -m cache_optimizer --fix

# 执行合并（自动备份）
python -m cache_optimizer --fix apply
```

## 支持的 AI 编程助手

| 名称 | 检测方式 | 配置扫描项 |
|---|---|---|
| **Claude Code** | `~/.claude/` + settings.json | CLAUDE.md / 记忆文件 / MCP / 技能 |
| **Codex CLI** | `~/.codex/` + 命令行 | AGENTS.md / memories / config.toml |
| **Hermes** | `~/.hermes/` + Python 包 | config.yaml / skills / ccr |

工具自动检测已安装的 agent 并执行对应的配置扫描，无需手动指定。

## 数据来源

本工具通过 **CC-Switch** 桌面应用获取请求日志数据。

CC-Switch 是一个本地代理工具（Tauri 桌面应用），放在你和 AI API 之间，记录所有请求的 token 消耗和缓存命中情况。数据存储在 `~/.cc-switch/cc-switch.db` (SQLite)。

👉 [下载 CC-Switch](https://github.com/farion1231/cc-switch/releases/latest)

没有 CC-Switch 也可以使用：从 CC-Switch 仪表盘复制请求日志，粘贴到工具中即可分析。

## 诊断指标

| 指标 | 说明 |
|---|---|
| **缓存命中率** | 当前值 vs 目标值 (默认 99%) |
| **请求分析** | 总请求数、总 token、平均输入/输出/缓存 |
| **配置扫描** | 系统提示动态内容、记忆文件、技能、MCP 服务 |
| **成本预估** | 当前成本、优化后成本、预估月省 |
| **综合评分** | 0-100 分，综合命中率和配置健康度 |

### 退出码 (CI/CD 集成)

| 退出码 | 含义 |
|---|---|
| 0 | 配置健康，无需优化 |
| 1 | 存在可优化项或无数据 |
| 2 | 命中率严重偏低 |

## 项目结构

```
cache_optimizer/
  __init__.py          # 核心: 数据解析, 分析引擎, 报告, 修复, 仪表盘, CLI
  __main__.py          # 入口 (python -m cache_optimizer)
  agents.py            # AI 编程助手检测 (Claude / Codex / Hermes)
  ccswitch_manager.py  # CC-Switch 对接: 检测, SQLite 读取, 代理配置
CHANGELOG.md           # 版本历史
pyproject.toml         # 项目配置 (pip install 支持)
LICENSE                # MIT 许可证
```

## 许可证

MIT — 随便用，随便改。
