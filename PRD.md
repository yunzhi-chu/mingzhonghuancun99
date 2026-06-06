# 命中缓存99% — 产品需求文档 (PRD)

> 版本: v1.0  
> 状态: 迭代中  
> 日期: 2026-06-06

---

## 一、产品定位

### 1.1 一句话描述
AI 编程助手缓存命中率诊断、修复与监控 CLI 工具。

### 1.2 目标用户
- **核心用户**: 重度使用 AI 编程助手的开发者（Claude Code / Codex CLI / Hermes）
- **次要用户**: 需要优化 AI API 调用成本的团队负责人
- **边缘用户**: 刚接触 AI 编程助手、想了解缓存机制的新手

### 1.3 核心痛点
| 痛点 | 频次 | 强度 |
|---|---|---|
| 不知道当前缓存命中率是多少 | 每天 | 高 |
| System prompt 越来越大但不懂为什么慢 | 每次迭代 | 中 |
| 记忆文件散落一堆，合并靠手 | 偶尔 | 中 |
| 想优化但不知道从哪下手 | 每周 | 高 |
| API 账单看不懂，不知道钱花在哪 | 每月 | 中 |

### 1.4 成功指标
- 用户运行一次 `--optimize` 后能清晰看到命中率和可优化项
- 一键修复后命中率提升 ≥ 5%
- 报告给出具体可操作的修复步骤

---

## 二、用户故事

### P0 — 必须实现

1. **作为用户**，我希望运行一条命令就知道电脑上装了哪些 AI 编程助手
2. **作为用户**，我希望查看当前的缓存命中率、总成本、请求量
3. **作为用户**，我希望知道 CLAUDE.md 里有没有动态内容破坏缓存
4. **作为用户**，我希望了解记忆文件数量和大小是否过大
5. **作为用户**，我希望一键合并过多的记忆文件
6. **作为用户**，我希望生成可分享的 HTML 仪表盘报告

### P1 — 重要

7. **作为用户**，我希望了解优化到 99% 能省多少钱
8. **作为用户**，我希望按严重程度排序看到优化建议列表
9. **作为用户**，我希望从 CC-Switch 桌面端自动读取请求数据
10. **作为用户**，我希望手动粘贴 CCSwitch 数据也能分析（无 CC-Switch 用户）

### P2 — 锦上添花

11. **作为用户**，我希望持续监控命中率变化趋势
12. **作为用户**，我希望对不同 agent 分别查看命中率
13. **作为用户**，我希望合并操作能回滚（备份恢复）
14. **作为用户**，我希望 CI/CD 集成检查缓存健康度（非 0 退出码）

---

## 三、功能清单

### 3.1 CLI 命令体系

| 命令 | 别名 | 功能 | 优先级 | 状态 |
|---|---|---|---|---|
| `--detect` | `-d` | 检测环境中的 AI agent + CC-Switch | P0 | ✅ |
| `--data <file>` |  | 从文件读取 CCSwitch 数据并分析 | P0 | ✅ |
| `--json` |  | 输出 JSON 格式（机器可读） | P0 | ✅ |
| `--dashboard [file]` |  | 生成 HTML 仪表盘 | P0 | ✅ |
| `--optimize` |  | 完整流程：检测→获取数据→分析→建议 | P0 | ✅ |
| `--fix [dry-run\|apply]` |  | 一键修复记忆文件 | P0 | ✅ |
| `--setup` |  | 检测 CC-Switch 状态和代理配置 | P1 | ✅ |
| `--config <dir>` | `-c` | 指定配置目录 | P1 | ✅ |
| `--target <n>` | `-t` | 设置目标命中率（默认 99%） | P1 | ✅ |
| `--summary` |  | 只分析摘要文本 | P1 | ✅ |

### 3.2 核心模块

| 模块 | 职责 | 状态 |
|---|---|---|
| agent 检测 | 检测 Claude Code / Codex CLI / Hermes / OpenClaw | ✅ |
| CC-Switch 对接 | 检测桌面端、读 SQLite、读代理配置 | ✅ (已修) |
| 数据解析 | 解析 Tab 分隔日志 / 中文摘要文本 | ✅ |
| 配置扫描 | 扫描 CLAUDE.md 动态内容、记忆文件、技能/MCP | ✅ |
| 分析引擎 | 命中率计算、成本预估、综合评分 | ✅ |
| 报告输出 | 文字报告 / JSON / HTML 仪表盘 | ✅ |
| Fix 引擎 | 记忆文件合并（备份→预览→执行） | ✅ (有风险) |

### 3.3 分析指标

| 指标 | 来源 | 说明 |
|---|---|---|
| 缓存命中率 | CCSwitch | `cache_read / (new_input + cache_read)` |
| 总请求数 | CCSwitch | proxy_request_logs 行数 |
| 总成本 | CCSwitch | total_cost_usd 汇总 |
| 平均输入/输出/缓存 | CCSwitch | 各 token 类型均值 |
| 动态内容检测 | CLAUDE.md 扫描 | 日期/时间/模板变量正则 |
| 记忆文件统计 | 文件系统 | 数量、大小、分布 |
| 技能数量 | settings.json | 启用的插件数 |
| 综合评分 | 分析引擎 | 0-100，根据多维度扣分 |
| 预估月省 | 分析引擎 | 基于 token 类型价格权重 |

---

## 四、非功能性需求

### 4.1 性能
- `--detect` 应在 2 秒内返回
- `--optimize` 全流程应在 10 秒内完成（SQLite 查询 < 1 秒）
- HTML 仪表盘单文件 < 50KB，纯静态，零网络依赖

### 4.2 兼容性
- Python ≥ 3.10，纯标准库（零外部依赖）
- Windows / macOS / Linux
- 支持 Claude Code / Codex CLI / Hermes / OpenClaw
- 支持 CCSwitch 数据 + 手动粘贴双模式

### 4.3 安全性
- API Key 显示截断（前 8 后 4）
- 修复前自动备份
- 不写任何 agent 配置文件（只读模式）
- HTTP API 请求限制只允许 localhost（防 SSRF）

### 4.4 可维护性
- 每个函数有中文注释说明
- 报告中有时间戳标识生成时间
- CLI 退出码：0=正常, 1=有优化项, 2=严重问题

---

## 五、数据模型

### 5.1 核心数据结构

```
RequestLog          = { time, provider, model, new_input, cache_read, output, cost, status, source }
CCSwitchData        = { requests[], total_new_input, total_cache_read, total_output, total_cost, hit_rate }
ConfigScanResult    = { claude_md_*, memory_*, skill_count, mcp_count, history_size_mb, issues[] }
ConfigIssue         = { severity, category, title, detail, impact, fix }
AnalysisResult      = { CCSwitch 指标 + ConfigScanResult + 优化预测 + 建议列表 + 评分 }
AgentInfo           = { name, display, version, config_dir, is_installed, env_keys[], details{} }
```

### 5.2 数据流

```
CC-Switch SQLite  ──→  fetch_data()  ──→  Tab 分隔文本  ──→  CCSwitchData.parse()
手贴 / --data 文件 ──→  raw text      ──→  CCSwitchData.parse()

Agent config 目录  ──→  scan_config()  ──→  ConfigScanResult

CCSwitchData + ConfigScanResult  ──→  analyze()  ──→  AnalysisResult

AnalysisResult  ──→  format_report()  ──→  控制台文字
                 ──→  format_json()   ──→  JSON 输出
                 ──→  generate_dashboard()  ──→  HTML 报告
```

---

## 六、验收标准 (Acceptance Criteria)

### AC-01: 环境检测
- [x] 运行 `--detect` 能列出所有已安装 AI agent
- [x] 运行 `--detect` 能显示 CC-Switch 安装状态和端口
- [x] 未安装 CC-Switch 时给出明确提示

### AC-02: 数据分析
- [x] 从 SQLite 读取数据后正确计算命中率
- [x] 手动粘贴 Tab 分隔数据也能解析
- [x] 中文摘要文本（带"万"字）能正确解析
- [x] 输出 JSON 格式能被其他程序消费

### AC-03: 配置扫描
- [x] 检测 CLAUDE.md 中的动态内容（日期/时间/模板变量）
- [x] 统计记忆文件数量和大小
- [x] 读取技能数量和 MCP 服务数
- [x] 支持 Codex CLI 的配置扫描（AGENTS.md / memories/ / config.toml）

### AC-04: 一键修复
- [x] dry-run 模式不修改任何文件
- [x] apply 前自动备份
- [x] 按类型分组合并记忆文件
- [x] 合并后更新 MEMORY.md 索引
- [x] 事务保护：先写后删，写入失败回滚

### AC-05: 仪表盘
- [ ] HTML 单文件，无外部依赖
- [ ] 显示综合评分、命中率、成本、配置状态
- [ ] 列出所有优化建议

---

## 七、已知限制 / 未解决的问题

| 问题 | 影响 | 计划 |
|---|---|---|
| 只扫 Claude 的配置，Codex/Hermes 配置扫描空白 | Codex 用户看不到完整诊断 | 后续迭代 |
| `--fix` 事务保护缺失，崩溃可能丢数据 | 低概率但后果严重 | 加 SQLite 风格 begin/commit |
| OpenClaw 未公开，对其他人无意义 | 只是占位 | 标记为实验性 |
| 没有历史趋势（无法看命中率变化） | 用户看不到优化效果 | 考虑加简易 JSON 持久化 |
| 没有 daemon/持续监控模式 | 手动运行，不能告警 | 可配合 cron 使用 |

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 初始版本，基础功能 | |
| v1.0 | 当前 | 修复 CCSwitch 对接链条，完善 --optimize 流程 |
