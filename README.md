# 命中缓存99%

> 缓存命中率 99% — AI agent 缓存诊断、优化与监控。

诊断 Claude Code / Codex CLI / Hermes / OpenClaw 等 AI agent 的缓存命中率，分析配置问题，一键修复，生成监控仪表盘。

## 安装

```bash
git clone https://github.com/yunzhi-chu/mingzhonghuancun99.git
cd mingzhonghuancun99
python -m cache_optimizer --help
```

## 使用

### 1. 检测环境

自动检测已安装的 AI agent 和 CCSwitch：

```bash
python -m cache_optimizer --detect
```

### 2. 一键优化

完整流程：检测 agent → 安装 CCSwitch → 获取数据 → 分析 → 修复：

```bash
python -m cache_optimizer --optimize
```

### 3. 手动分析

从 CCSwitch 仪表盘粘贴数据：

```bash
python -m cache_optimizer
```

或从文件读取：

```bash
python -m cache_optimizer --data data.txt
```

摘要模式（适合从 CCSwitch 复制摘要信息）：

```bash
python -m cache_optimizer --summary --data summary.txt
```

### 4. 一键修复

预览记忆文件合并计划：

```bash
python -m cache_optimizer --fix
```

执行合并：

```bash
python -m cache_optimizer --fix apply
```

### 5. 生成仪表盘

```bash
python -m cache_optimizer --dashboard report.html
```

### 6. JSON 输出

```bash
python -m cache_optimizer --data data.txt --json
```

### 7. 自动安装配置

```bash
python -m cache_optimizer --setup
```

## 支持的 Agent

| Agent | 检测方式 | 缓存策略 |
|---|---|---|
| Claude Code | `~/.claude/` 目录 + settings.json | Anthropic 提示缓存 |
| Codex CLI | `~/.codex/` 目录 + 命令行 | OpenAI 提示缓存 |
| Hermes-Claw | `~/.hermes/` 目录 + Python 包 | 可配置缓存 |
| OpenClaw | `~/.openclaw/` 目录 + 环境变量 | 可配置缓存 |
| 通用 API Key | 环境变量 `ANTHROPIC_API_KEY` 等 | 通用优化 |

## CCSwitch 集成

本工具与 CCSwitch 深度集成：

- 自动检测 CCSwitch 是否安装
- 未安装时一键自动安装
- 对接 CCSwitch API 获取请求级使用数据
- 分析命中率并生成优化建议

CCSwitch 提供的数据维度：时间、供应商、模型、新增输入、缓存读取、输出、成本、TTF、状态。

## 诊断指标

- **缓存命中率**：当前值 + 目标对比（默认 99%）
- **请求分析**：总请求数、总 tokens、平均每轮输入/输出
- **配置扫描**：CLAUDE.md 动态内容、记忆文件数量、技能数量、MCP 服务
- **成本预估**：当前成本、优化后成本、预估月省
- **建议引擎**：按 severity 排序的具体优化项

## 项目结构

```
mingzhonghuancun99/
  cache_optimizer/
    __init__.py         # 核心逻辑：数据解析、分析、报告、修复、仪表盘、CLI
    __main__.py         # 入口
    agents.py           # 多 agent 检测（Claude/Codex/Hermes/OpenClaw）
    ccswitch_manager.py # CCSwitch 安装、配置、数据获取
  pyproject.toml
  README.md
  LICENSE
```

## 许可证

MIT — 使用、分享、方便。
