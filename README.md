# 命中缓存99%

> 缓存命中率 99% — AI 编程助手缓存诊断、优化与监控。

## 这是什么工具？

每次你用 AI 编程助手（如 Claude Code、Codex CLI），都会发送一段"上下文"给 AI。
如果这段上下文和上一次完全一样，AI 就可以从**缓存**读取，不用重新算 —— 这就是**缓存命中**。

命中率越高 → 速度越快 → 成本越低。

本工具帮你：
1. **检测** — 看看你电脑上装了哪些 AI 编程助手
2. **分析** — 看看当前缓存命中率是多少，还有多少优化空间
3. **修复** — 一键解决配置问题，把命中率提到 99%
4. **监控** — 生成漂亮的网页报告，随时查看

---

## 安装

**第一步：** 打开命令行（终端 / PowerShell / CMD）

**第二步：** 把代码下载到本地：

```bash
git clone https://github.com/yunzhi-chu/mingzhonghuancun99.git
```

**第三步：** 进入文件夹：

```bash
cd mingzhonghuancun99
```

**第四步：** 验证安装成功：

```bash
python -m cache_optimizer --help
```

看到帮助信息就说明装好了。

---

## 快速上手（小白版）

### 1️⃣ 检测环境 —— 看看你装了哪些 AI 助手

```bash
python -m cache_optimizer --detect
```

它会自动检测你电脑上有没有装：
- Claude Code
- Codex CLI
- Hermes-Claw
- OpenClaw
- 以及相关的 API Key 环境变量

### 2️⃣ 完整优化 —— 一条命令走完所有流程

```bash
python -m cache_optimizer --optimize
```

这条命令会自动完成：
1. 检测你装了哪些 AI 助手
2. 安装 CCSwitch（用来记录请求数据）
3. 从 CCSwitch 获取使用数据
4. 扫描配置问题
5. 给出优化建议

### 3️⃣ 手动分析 —— 从 CCSwitch 粘贴数据

如果你已经有 CCSwitch 的数据，可以手动分析。

**从文件读取：**
```bash
python -m cache_optimizer --data data.txt
```

**直接粘贴（交互模式）：**
```bash
python -m cache_optimizer
```
然后粘贴数据，按 `Ctrl+D`（Windows 是 `Ctrl+Z` 回车）结束。

**只看摘要（不用完整表格）：**
```bash
python -m cache_optimizer --summary --data summary.txt
```

### 4️⃣ 一键修复 —— 合并记忆文件

记忆文件太多会影响命中率，本工具可以帮你合并同类文件。

**先预览合并方案（不执行）：**
```bash
python -m cache_optimizer --fix
```

**确认没问题后执行合并：**
```bash
python -m cache_optimizer --fix apply
```

> 执行前会自动备份，合并错了也能恢复。

### 5️⃣ 生成网页报告

```bash
python -m cache_optimizer --dashboard report.html
```

会生成一个漂亮的网页，自动在浏览器中打开。

### 6️⃣ 输出 JSON 格式（给其他程序用）

```bash
python -m cache_optimizer --data data.txt --json
```

### 7️⃣ 自动安装 CCSwitch

```bash
python -m cache_optimizer --setup
```

自动安装 CCSwitch 并配好代理，之后 CCSwitch 就会在后台记录所有请求数据。

---

## 支持的 AI 编程助手

| 名称 | 检测方式 | 缓存策略 |
|---|---|---|
| Claude Code | `~/.claude/` 目录 + settings.json | Anthropic 提示缓存 |
| Codex CLI | `~/.codex/` 目录 + 命令行 | OpenAI 提示缓存 |
| Hermes-Claw | `~/.hermes/` 目录 + Python 包 | 可配置缓存 |
| OpenClaw | `~/.openclaw/` 目录 + 环境变量 | 可配置缓存 |
| 通用 API Key | 环境变量 `ANTHROPIC_API_KEY` 等 | 通用优化 |

---

## CCSwitch 是什么？

CCSwitch 是一个"中间人"代理工具，放在你和 AI API 之间。
所有发给 AI 的请求都会经过它，它会记录下：

- **时间** — 什么时候发的请求
- **供应商** — 用的是 Anthropic 还是 OpenAI
- **模型** — 用的什么模型
- **新增输入** — 第一次发送的 token 数
- **缓存读取** — 命中缓存的 token 数（带 R 前缀）
- **输出** — AI 回复的 token 数
- **成本** — 每次请求花了多少钱

本工具深度集成 CCSwitch：
- 自动检测是否已安装
- 没装就一键自动安装
- 通过 API 获取请求级数据
- 分析命中率并生成优化建议

---

## 诊断指标说明

| 指标 | 说明 |
|---|---|
| **缓存命中率** | 当前值 vs 目标值（默认 99%）|
| **请求分析** | 总请求数、总 token 数、平均每轮输入/输出 |
| **配置扫描** | CLAUDE.md 动态内容、记忆文件数量、技能数量、MCP 服务 |
| **成本预估** | 当前成本、优化后成本、预估每月节省 |
| **建议引擎** | 按严重程度排序的优化建议 |

---

## 项目文件说明

```
mingzhonghuancun99/
  cache_optimizer/
    __init__.py          # 核心代码：数据解析、分析、报告、修复、网页、命令行
    __main__.py          # 入口文件
    agents.py            # 检测各种 AI 编程助手（Claude/Codex/Hermes/OpenClaw）
    ccswitch_manager.py  # CCSwitch 的安装、配置、数据获取
  pyproject.toml         # 项目配置文件
  README.md              # 本文件
  LICENSE                # 许可证
```

---

## 许可证

MIT — 随便用，随便改。
