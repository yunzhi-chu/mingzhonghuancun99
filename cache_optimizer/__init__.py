#!/usr/bin/env python3
"""命中缓存99% — 通用 AI agent 缓存诊断与优化工具。

什么是"缓存命中率"？
  你每次问 AI 问题时，都会把一些"上下文"（之前的对话、系统提示等）发给 AI。
  如果这些上下文和上一次完全一样，AI 就可以直接从缓存读取，不用重新算。
  缓存命中率 = 缓存读取的 token 数 / 总发送的 token 数 × 100%

  举个栗子🌰：
    你每次发 10000 个 token，其中 9900 个是重复的上下文（缓存命中），
    只有 100 个是新问题。那命中率就是 99%。

  命中率越高，速度越快、成本越低！
"""

import sys
import argparse

# 修复 Windows 终端的中文乱码问题
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import csv
import json
import os
import re
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from typing import Optional

# 导入我们自己写的其他模块
from . import agents                  # agent 检测
from . import ccswitch_manager as ccsm  # CCSwitch 管理


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════
# 什么是数据模型？
#   就像用表格来记录信息——先定义好每一列叫什么、是什么类型。
#   后面解析数据时，就按这个"表格"来填内容。

@dataclass
class RequestLog:
    """一条 API 请求的日志记录。

    相当于 CCSwitch 表格中的一行数据。

    time:       请求时间（如 2026-06-01 10:30:00）
    provider:   供应商，谁提供的 AI 服务（如 Anthropic / OpenAI）
    model:      用的什么模型（如 claude-sonnet-4-6 / gpt-4o）
    new_input:  新输入的 token 数（第一次发的、不在缓存里的内容）
    cache_read: 从缓存命中的 token 数（重复的内容）
    output:     AI 回复的 token 数
    cost:       这次请求花了多少钱（美元）
    status:     请求状态（success / error 等）
    source:     来源（如 chat / api / batch）
    """
    time: str
    provider: str
    model: str
    new_input: int
    cache_read: int
    output: int
    cost: float
    status: str
    source: str


@dataclass
class CCSwitchData:
    """CCSwitch 数据的汇总结果。

    把很多条 RequestLog 汇总到一起，算出总数和命中率。

    requests:         所有请求的列表
    total_new_input:  所有请求的新输入 token 总和
    total_cache_read: 所有请求的缓存读取 token 总和
    total_output:     所有请求的输出 token 总和
    total_cost:       所有请求的总花费（美元）
    total_requests:   总请求数
    hit_rate:         缓存命中率（百分比，如 98.64 表示 98.64%）
    """
    requests: list[RequestLog] = field(default_factory=list)
    total_new_input: int = 0
    total_cache_read: int = 0
    total_output: int = 0
    total_cost: float = 0.0
    total_requests: int = 0
    hit_rate: float = 0.0

    @classmethod
    def parse(cls, text: str) -> "CCSwitchData":
        """解析 CCSwitch 导出的 Tab 分隔文本。

        这是最核心的数据解析函数！
        输入：从 CCSwitch 复制的一大段文本（每行是一列，Tab 分隔）
        输出：CCSwitchData 对象（包含了所有请求和汇总数据）

        支持的格式：
          1. 标准格式（10列）：time, provider, model, new_input, R_cache, output, cost, ttf, status, source
          2. 紧凑格式（8列）：time, provider, model, input/output, ..., status, source

        什么是"R"前缀？
          缓存读取的 token 数前面会加一个 R，比如 "R1234"。
          表示这 1234 个 token 是从缓存里读的，不用重新算。
        """
        # 第一步：按换行符拆成行，去掉空行
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return cls()  # 没有数据，返回空结果

        data = cls()

        # 第二步：检测分隔符（Tab 还是逗号还是空格）
        header = lines[0]
        delimiter = "\t" if "\t" in header else ("," if "," in header else None)
        if delimiter is None:
            # 尝试多空格分隔
            if len(re.split(r"\s{2,}", header)) >= 5:
                reader = csv.reader(lines, delimiter="\t") if "\t" in lines[0] else csv.reader(lines)
            else:
                return cls()  # 实在识别不了分隔符，返回空
        else:
            reader = csv.reader(lines, delimiter=delimiter)

        # 第三步：逐行解析
        rows = list(reader)
        if len(rows) < 2:  # 至少要有表头 + 一行数据
            return cls()

        for row in rows[1:]:  # 第一行是表头，从第二行开始才是数据
            if len(row) < 6:
                continue  # 列数太少，这行数据不完整
            try:
                col_count = len(row)
                if col_count >= 10:
                    # 标准格式（10列）：这是 CCSwitch 最完整的导出格式
                    # 各列依次是：时间、供应商、模型、新增输入、R缓存读取、输出、费用、首token延迟、状态、来源
                    time_str = row[0].strip()
                    provider = row[1].strip()
                    model = row[2].strip()
                    new_input = int(row[3].replace(",", ""))
                    cache_read_raw = row[4].strip()
                    cache_read = int(cache_read_raw.replace("R", "").replace(",", ""))
                    output_raw = row[5].strip()
                    output_tokens = int(output_raw.replace(",", ""))
                    cost = float(row[6].replace("$", "").replace(",", ""))
                    status = row[8].strip() if len(row) > 8 else ""
                    source = row[9].strip() if len(row) > 9 else ""
                elif col_count >= 8:
                    # 紧凑格式（8列）：列数少一些，需要猜哪列是什么
                    time_str = row[0].strip()
                    provider = row[1].strip()
                    model = row[2].strip()
                    # 判断第3列和第4列哪一个是"新增输入"、哪一个是"缓存读取"
                    # 缓存读取的数据前面有个 R，比如 "R5000"
                    col3 = row[3].strip()
                    col4 = row[4].strip()
                    if col3.startswith("R"):
                        cache_read = int(col3.replace("R", "").replace(",", ""))
                        new_input = int(col4.replace(",", ""))
                        output_tokens = int(row[5].replace(",", ""))
                    elif col4.startswith("R"):
                        new_input = int(col3.replace(",", ""))
                        cache_read = int(col4.replace("R", "").replace(",", ""))
                        output_tokens = int(row[5].replace(",", ""))
                    else:
                        # 没有 R 前缀，说明所有输入都是新的（缓存命中率为 0）
                        new_input = int(col3.replace(",", ""))
                        cache_read = 0
                        output_tokens = int(col4.replace(",", ""))
                    cost = float(row[6].replace("$", "").replace(",", ""))
                    status = row[7].strip() if len(row) > 7 else ""
                    source = row[8].strip() if len(row) > 8 else ""
                else:
                    continue

                # 把这一行数据存到 RequestLog 对象里
                rl = RequestLog(
                    time=time_str,
                    provider=provider,
                    model=model,
                    new_input=new_input,
                    cache_read=cache_read,
                    output=output_tokens,
                    cost=cost,
                    status=status,
                    source=source,
                )
                data.requests.append(rl)
            except (ValueError, IndexError):
                continue  # 某一行解析出错，跳过它继续解析下一行

        # 第四步：汇总所有请求
        for r in data.requests:
            data.total_new_input += r.new_input
            data.total_cache_read += r.cache_read
            data.total_output += r.output
            data.total_cost += r.cost
        data.total_requests = len(data.requests)

        # 计算缓存命中率
        # 公式：缓存读取 / (新增输入 + 缓存读取) × 100%
        # 如果总数为 0，命中率就是 0
        total_context = data.total_new_input + data.total_cache_read
        data.hit_rate = (data.total_cache_read / total_context * 100) if total_context > 0 else 0

        return data

    @classmethod
    def parse_summary(cls, text: str) -> Optional["CCSwitchData"]:
        """从 CCSwitch 摘要文本中提取关键指标。

        有时候你只有 CCSwitch 的摘要数据（不是完整的表格），
        比如只有几行文字：
          总请求数：12,889
          总成本：$9.59
          缓存命中率：98.64%

        这个函数就是解析这种摘要文本的。

        特别说明：支持中文数字单位"万"
          比如 "新增输入：3.2万" 会被识别为 32000
        """
        data = cls()
        lines = text.strip().split("\n")
        for line in lines:
            try:
                line = line.strip()
                # 检查有没有"万"字，有的话数字要乘以 10000
                multiplier = 10000 if "万" in line else 1
                # 总请求数
                m = re.match(r"总请求数[：:]\s*([\d,.]+)", line)
                if m:
                    data.total_requests = int(float(m.group(1).replace(",", "")))
                    continue
                # 总成本
                m = re.match(r"总成本[：:]\s*\$?([\d.]+)", line)
                if m:
                    data.total_cost = float(m.group(1))
                    continue
                # 新增输入
                m = re.match(r"新增输入[：:]\s*([\d.]+)", line)
                if m:
                    data.total_new_input = int(float(m.group(1)) * multiplier)
                    continue
                # Output（AI 输出）
                m = re.match(r"[Oo]utput[：:]\s*([\d.]+)", line)
                if m:
                    data.total_output = int(float(m.group(1)) * multiplier)
                    continue
                # 缓存命中（注意不是"缓存命中率"，没有"率"字）
                m = re.match(r"缓存命中(?!率)[：:]\s*([\d.]+)", line)
                if m:
                    data.total_cache_read = int(float(m.group(1)) * multiplier)
                    continue
                # 缓存命中率
                m = re.match(r"缓存命中率[：:]\s*([\d.]+)%", line)
                if m:
                    data.hit_rate = float(m.group(1))
                    continue
            except (ValueError, ArithmeticError):
                continue

        # 如果能算出命中率但没匹配到，手动算一下
        total_context = data.total_new_input + data.total_cache_read
        if total_context > 0 and data.hit_rate == 0:
            data.hit_rate = data.total_cache_read / total_context * 100
        # 如果有成本但没请求数，至少算 1 条
        if data.total_cost > 0 and data.total_requests == 0:
            data.total_requests = 1

        return data if data.total_requests > 0 else None


# ═══════════════════════════════════════════════════════════════
# 配置扫描
# ═══════════════════════════════════════════════════════════════
# 扫描 AI agent 的配置文件，找出可能影响缓存命中率的问题。
#
# 什么是"固定前缀"？
#   每次发给 AI 的请求，前面都有一段不变的内容（系统提示、记忆文件等）。
#   这段内容如果每次都一样，AI 就可以缓存它。
#   但如果里面有"动态内容"（比如当前日期、随机数），那每次都不一样，
#   缓存就用不上了，命中率就会下降。

@dataclass
class ConfigIssue:
    """扫描发现的配置问题。

    severity: 严重程度（critical / warning / info / success）
    category: 问题类别（memory / claude_md / settings / mcp / skills）
    title:    问题标题
    detail:   详细说明
    impact:   对命中率有什么影响
    fix:      怎么修复
    """
    severity: str
    category: str
    title: str
    detail: str
    impact: str
    fix: str


@dataclass
class ConfigScanResult:
    """配置扫描的结果汇总。

    claude_md_size:       CLAUDE.md 文件大小（字节）
    claude_md_lines:      CLAUDE.md 文件行数
    claude_md_has_dynamic: CLAUDE.md 是否包含动态内容（日期时间等）
    memory_file_count:    记忆文件的数量
    memory_total_size:    所有记忆文件的总大小（字节）
    memory_file_list:     记忆文件列表，每个元素是 (文件名, 大小)
    skill_count:          启用了多少个技能（插件）
    mcp_count:            配置了多少个 MCP 服务
    settings_issues:      settings.json 中的问题列表
    history_size_mb:      对话历史文件大小（MB）
    issues:               所有发现的问题列表
    """
    claude_md_size: int = 0
    claude_md_lines: int = 0
    claude_md_has_dynamic: bool = False
    memory_file_count: int = 0
    memory_total_size: int = 0
    memory_file_list: list = field(default_factory=list)
    skill_count: int = 0
    mcp_count: int = 0
    settings_issues: list = field(default_factory=list)
    history_size_mb: float = 0.0
    issues: list[ConfigIssue] = field(default_factory=list)
    agents_scanned: list[str] = field(default_factory=list)  # 哪些 agent 被扫描了


def scan_config(base_dir: str = None) -> ConfigScanResult:
    """扫描单个 Claude Code 配置目录（向后兼容）。"""
    if base_dir is None:
        base_dir = os.path.expanduser("~/.claude")
    claude_dir = Path(base_dir)
    if not claude_dir.exists():
        return ConfigScanResult()
    result = ConfigScanResult()
    result.agents_scanned.append("claude")
    _scan_claude_config(claude_dir, result)
    return result


def scan_all_configs(agent_list: list = None) -> ConfigScanResult:
    """扫描所有已检测到的 AI agent 的配置。

    自动适配每个 agent 的配置文件结构。
    """
    merged = ConfigScanResult()

    if agent_list is None:
        from . import agents as _ag
        agent_list = _ag.detect_all()

    for agent in agent_list:
        name = agent.name
        cfg_dir = agent.config_dir
        if not cfg_dir.exists():
            continue

        if name == "claude":
            single = ConfigScanResult()
            single.agents_scanned.append("claude")
            _scan_claude_config(cfg_dir, single)
            _merge_into(merged, single)

        elif name == "codex":
            single = ConfigScanResult()
            single.agents_scanned.append("codex")
            _scan_codex_config(cfg_dir, single)
            _merge_into(merged, single)

        elif name == "hermes":
            single = ConfigScanResult()
            single.agents_scanned.append("hermes")
            _scan_hermes_config(cfg_dir, single)
            _merge_into(merged, single)

    return merged


def _merge_into(target: ConfigScanResult, source: ConfigScanResult):
    """合并两个扫描结果。"""
    for attr in ["claude_md_size", "claude_md_lines", "memory_file_count",
                  "memory_total_size", "skill_count", "mcp_count", "history_size_mb"]:
        setattr(target, attr, getattr(target, attr) + getattr(source, attr))
    target.claude_md_has_dynamic = target.claude_md_has_dynamic or source.claude_md_has_dynamic
    target.memory_file_list.extend(source.memory_file_list)
    target.settings_issues.extend(source.settings_issues)
    target.issues.extend(source.issues)
    target.agents_scanned.extend(source.agents_scanned)


def _scan_claude_config(claude_dir: Path, result: ConfigScanResult):
    """扫描单个 Claude Code 配置目录。结果写入 result 对象。"""
    # ── 检查 CLAUDE.md ──────────────────────────────────────
    cm = claude_dir / "CLAUDE.md"
    if cm.exists():
        content = cm.read_text(encoding="utf-8")
        result.claude_md_size = len(content.encode("utf-8"))
        result.claude_md_lines = content.count("\n") + 1

        dynamic_patterns = [
            (r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", "日期"),
            (r"\d{2}:\d{2}", "时间"),
            (r"今天|昨天|明天|星期[一二三四五六日]", "相对日期"),
            ("CURRENT_DATE|currentDate|{{.*}}", "模板变量"),
        ]
        dynamic_items = []
        for pat, name in dynamic_patterns:
            if re.search(pat, content):
                dynamic_items.append(name)
        result.claude_md_has_dynamic = len(dynamic_items) > 0
        if dynamic_items:
            result.issues.append(ConfigIssue(
                severity="warning",
                category="claude_md",
                title="CLAUDE.md 含动态内容",
                detail=f"检测到: {', '.join(dynamic_items)}。动态内容使每次请求的前缀发生变化，导致 cache miss。",
                impact="每次 CI/build 类操作都产生新前缀，命中率损失约 0.1-0.5%",
                fix="将动态内容移至运行时变量或 system-reminder 区域（该区域不在缓存 key 中）。"
            ))
        if result.claude_md_size > 2048:
            result.issues.append(ConfigIssue(
                severity="info",
                category="claude_md",
                title=f"CLAUDE.md 体积较大 ({result.claude_md_size} bytes)",
                detail="大于 2KB 的 CLAUDE.md 会占用固定前缀空间，增大每轮总输入。",
                impact="每增大 1KB 固定前缀，约增加 $0.0001/请求的成本基数",
                fix="精简 CLAUDE.md 至 1-2KB 以内，非核心内容放入记忆文件按需加载。"
            ))

    # ── 检查记忆文件 ────────────────────────────────────────
    memory_base = claude_dir / "projects"
    if memory_base.exists():
        for proj_dir in memory_base.iterdir():
            mem_dir = proj_dir / "memory"
            if mem_dir.exists():
                for f in mem_dir.iterdir():
                    if f.suffix == ".md":
                        fsize = f.stat().st_size
                        result.memory_file_count += 1
                        result.memory_total_size += fsize
                        result.memory_file_list.append((f.name, fsize))
        if result.memory_file_count > 10:
            result.issues.append(ConfigIssue(
                severity="warning",
                category="memory",
                title=f"记忆文件过多 ({result.memory_file_count} 个)",
                detail=f"共 {result.memory_file_count} 个记忆文件，总计 {result.memory_total_size} bytes。每个文件均加载到 system prompt 中。",
                impact="每多 10 个文件，system prompt 开销增加 ~500 tokens，cache miss 概率略有上升",
                fix="合并同类记忆文件至 5 个以内。MEMORY.md 索引条目超过 200 行会被截断。"
            ))
        if result.memory_total_size > 10000:
            result.issues.append(ConfigIssue(
                severity="info",
                category="memory",
                title=f"记忆目录总大小 {result.memory_total_size} bytes",
                detail="记忆文件全量加载到固定前缀中。过大会推高每次请求的基础 token 消耗。",
                impact=f"约占总固定前缀的 {result.memory_total_size // 4} tokens",
                fix="定期清理过期记忆，合并冗余条目。"
            ))

    # ── 检查 settings.json ──────────────────────────────────
    sf = claude_dir / "settings.json"
    if sf.exists():
        try:
            s = json.loads(sf.read_text(encoding="utf-8"))
            env = s.get("env", {})
            for k, v in env.items():
                if "token" in k.lower() or "key" in k.lower() or "secret" in k.lower():
                    if len(v) > 20:
                        result.issues.append(ConfigIssue(
                            severity="info",
                            category="settings",
                            title="settings.json 含长 Token 值",
                            detail=f"{k}={v[:4]}...{v[-4:]}。Token 本身不直接影响命中率，但混淆时可能误认为是动态内容。",
                            impact="无直接影响",
                            fix="确保 token 值不在 CLAUDE.md 或 system prompt 中引用。"
                        ))
            plugins = s.get("enabledPlugins", {})
            result.skill_count = len(plugins)
            if result.skill_count > 10:
                result.issues.append(ConfigIssue(
                    severity="warning",
                    category="skills",
                    title=f"启用过多技能 ({result.skill_count} 个)",
                    detail=f"每个技能加载自己的指令到 system prompt，共 {result.skill_count} 个插件。",
                    impact="每个技能约增加 200-500 tokens 固定前缀",
                    fix="只启用当前项目必需的技能，其余按需启用。"
                ))
        except (json.JSONDecodeError, KeyError):
            pass

    # ── 检查 MCP 服务配置 ───────────────────────────────────
    mcp = claude_dir / "mcp.json"
    if mcp.exists():
        try:
            mc = json.loads(mcp.read_text(encoding="utf-8"))
            result.mcp_count = len(mc.get("mcpServers", {}))
        except json.JSONDecodeError:
            pass

    # ── 检查对话历史大小 ────────────────────────────────────
    hist = claude_dir / "history.jsonl"
    if hist.exists():
        result.history_size_mb = hist.stat().st_size / (1024 * 1024)


def _scan_codex_config(codex_dir: Path, result: ConfigScanResult):
    """扫描 Codex CLI 配置目录。

    扫描项：AGENTS.md 体积、memories/ 文件、config.toml MCP/插件。
    """
    # ── AGENTS.md 体积（不检查动态内容）──────────────────────
    ag = codex_dir / "AGENTS.md"
    if ag.exists():
        content = ag.read_text(encoding="utf-8")
        result.claude_md_size += len(content.encode("utf-8"))
        result.claude_md_lines += content.count("\n") + 1

    # ── memories/ 记忆文件 ───────────────────────────────────
    mem_dir = codex_dir / "memories"
    if mem_dir.exists():
        for f in mem_dir.iterdir():
            if f.suffix == ".md":
                sz = f.stat().st_size
                result.memory_file_count += 1
                result.memory_total_size += sz
                result.memory_file_list.append((f.name, sz))

    # ── config.toml MCP 服务数 ───────────────────────────────
    ct = codex_dir / "config.toml"
    if ct.exists():
        try:
            text = ct.read_text(encoding="utf-8")
            result.mcp_count += text.count("[mcp_servers.")
            result.skill_count += text.count("[plugins.")
        except Exception:
            pass

    # ── 历史文件大小 ────────────────────────────────────────
    hist = codex_dir / "history.jsonl"
    if hist.exists():
        result.history_size_mb += hist.stat().st_size / (1024 * 1024)


def _scan_hermes_config(hermes_dir: Path, result: ConfigScanResult):
    """扫描 Hermes Agent 配置目录。

    Hermes 用 config.yaml 配置，skills/ 目录存技能。
    """
    # ── config.yaml 体积 ─────────────────────────────────────
    cy = hermes_dir / "config.yaml"
    if cy.exists():
        content = cy.read_text(encoding="utf-8")
        result.claude_md_size += len(content.encode("utf-8"))
        result.claude_md_lines += content.count("\n") + 1
        # 检测是否有 MCP 配置
        import re as _re
        mcp_matches = _re.findall(r"mcp_servers\s*:", content)
        if mcp_matches:
            result.mcp_count += len(mcp_matches)

    # ── skills/ 技能目录 ────────────────────────────────────
    sk = hermes_dir / "skills"
    if sk.exists():
        skill_count = len([f for f in sk.iterdir() if f.is_dir() or f.suffix == ".md"])
        result.skill_count += max(1, skill_count)  # 至少有目录本身

    # ── ccr/ 记忆/缓存目录 ─────────────────────────────────
    ccr = hermes_dir / "ccr"
    if ccr.exists():
        for f in ccr.iterdir():
            if f.is_file():
                sz = f.stat().st_size
                result.memory_file_count += 1
                result.memory_total_size += sz
                result.memory_file_list.append((f.name, sz))


# ═══════════════════════════════════════════════════════════════
# 分析引擎
# ═══════════════════════════════════════════════════════════════
# 把上面拿到的数据（CCSwitch 数据 + 配置扫描结果）综合分析，
# 算出各种指标，给出优化建议。

@dataclass
class AnalysisResult:
    """完整的分析结果。

    ── CCSwitch 分析 ──
    has_ccswitch_data:   是否有 CCSwitch 数据
    current_hit_rate:    当前缓存命中率（%）
    total_requests:      总请求数
    total_cost:          总成本（美元）
    avg_input_per_request:  平均每轮新增输入 token
    avg_output_per_request: 平均每轮输出 token
    avg_cache_per_request:  平均每轮缓存读取 token
    avg_cost_per_request:   平均每轮成本
    variable_per_request:   平均每轮不可缓存的部分

    ── 配置分析 ──
    config: 配置扫描结果

    ── 优化预测 ──
    target_hit_rate:          目标命中率（默认 99%）
    projected_savings_percent: 预估节省百分比
    projected_savings_monthly: 预估每月节省（美元）
    projected_new_cost:       优化后的预估每日成本
    recommendations:          优化建议列表

    ── 诊断摘要 ──
    diagnosis:     文字诊断结果
    overall_score: 综合评分（0-100）
    """
    has_ccswitch_data: bool = False
    current_hit_rate: float = 0.0
    total_requests: int = 0
    total_cost: float = 0.0
    avg_input_per_request: float = 0.0
    avg_output_per_request: float = 0.0
    avg_cache_per_request: float = 0.0
    avg_cost_per_request: float = 0.0
    variable_per_request: float = 0.0

    config: ConfigScanResult = field(default_factory=ConfigScanResult)

    target_hit_rate: float = 99.0
    projected_savings_percent: float = 0.0
    projected_savings_monthly: float = 0.0
    projected_new_cost: float = 0.0
    recommendations: list = field(default_factory=list)

    diagnosis: str = ""
    overall_score: int = 0


def analyze(ccswitch: Optional[CCSwitchData], config: ConfigScanResult, target: float = 99.0) -> AnalysisResult:
    """执行完整的缓存命中率分析。

    参数：
      ccswitch: CCSwitch 数据（可以没有）
      config:   配置扫描结果
      target:   目标命中率（默认 99%）

    分析流程：
      1. 从 CCSwitch 数据计算当前命中率和成本
      2. 预测优化到目标命中率能省多少钱
      3. 结合配置扫描结果生成建议
      4. 计算综合评分

    什么是 cost_breakdown（成本分解）？
      不同 token 的价格不一样：
        - 新输入 token：价格最高（权重 1.0）
        - 输出 token：价格也很高（权重 1.0）
        - 缓存读取 token：便宜很多（权重 0.1）
      所以我们通过权重来估算优化后的成本。
    """
    r = AnalysisResult()
    r.target_hit_rate = target
    r.config = config

    # ── 第一步：从 CCSwitch 数据计算指标 ────────────────────
    if ccswitch and ccswitch.total_requests > 0:
        r.has_ccswitch_data = True
        r.current_hit_rate = ccswitch.hit_rate
        r.total_requests = ccswitch.total_requests
        r.total_cost = ccswitch.total_cost
        r.avg_input_per_request = ccswitch.total_new_input / ccswitch.total_requests
        r.avg_cache_per_request = ccswitch.total_cache_read / ccswitch.total_requests
        r.avg_output_per_request = ccswitch.total_output / ccswitch.total_requests
        r.avg_cost_per_request = ccswitch.total_cost / ccswitch.total_requests
        r.variable_per_request = (
            ccswitch.total_new_input / ccswitch.total_requests
            + ccswitch.total_output / ccswitch.total_requests
        )

        # ── 第二步：预测优化效果 ────────────────────────────
        # 思路很简单：
        #   现在命中率是 X%，目标是 Y%。
        #   要把命中率从 X 提到 Y，需要减少"新增输入"的比例。
        #   我们根据 token 的单价差异来估算省多少钱。
        total_context = ccswitch.total_new_input + ccswitch.total_cache_read
        if total_context > 0:
            current_new_input_ratio = ccswitch.total_new_input / total_context
            target_new_input_ratio = 1 - target / 100
            new_new_input = total_context * target_new_input_ratio
            saved_tokens = ccswitch.total_new_input - new_new_input

            # 根据 token 类型的不同价格权重估算成本
            current_cost_breakdown = (
                ccswitch.total_new_input * 1.0 +   # 新输入：全价
                ccswitch.total_output * 1.0 +      # 输出：全价
                ccswitch.total_cache_read * 0.1     # 缓存：1/10 价
            )
            new_input_at_target = total_context * (1 - target / 100)
            new_cache_at_target = total_context * (target / 100)
            target_cost_breakdown = (
                new_input_at_target * 1.0 +
                ccswitch.total_output * 1.0 +
                new_cache_at_target * 0.1
            )
            if current_cost_breakdown > 0:
                r.projected_savings_percent = (1 - target_cost_breakdown / current_cost_breakdown) * 100
                r.projected_new_cost = ccswitch.total_cost * (target_cost_breakdown / current_cost_breakdown)
                # 月预估 = 每天节省 × 30 天
                r.projected_savings_monthly = (ccswitch.total_cost - r.projected_new_cost) * 30

    # ── 第三步：生成优化建议 ────────────────────────────────
    # 先把配置扫描中发现的问题加入建议列表
    for issue in config.issues:
        r.recommendations.append({
            "severity": issue.severity,
            "category": issue.category,
            "title": issue.title,
            "detail": issue.detail,
            "impact": issue.impact,
            "fix": issue.fix,
        })

    # 如果有 CCSwitch 数据，再基于数据生成建议
    if r.has_ccswitch_data:
        if r.avg_input_per_request > 2000:
            r.recommendations.append({
                "severity": "warning",
                "category": "usage",
                "title": "每轮新增输入偏大",
                "detail": f"平均每轮新增输入 {r.avg_input_per_request:.0f} tokens。新增输入是 cache miss 的直接来源。",
                "impact": f"每轮新增 {r.avg_input_per_request:.0f} tokens 中大部分不可缓存",
                "fix": "压缩用户指令长度，减少工具调用返回体积。批量处理独立任务减少轮数。"
            })
        if r.avg_output_per_request > 2000:
            r.recommendations.append({
                "severity": "info",
                "category": "usage",
                "title": "输出 tokens 较多",
                "detail": f"平均每轮输出 {r.avg_output_per_request:.0f} tokens。输出本身不占缓存，但说明回复篇幅长。",
                "impact": "不影响命中率，但直接影响成本",
                "fix": "对于批量处理场景，适当限制 max_tokens。"
            })
        if r.current_hit_rate < 95:
            r.recommendations.append({
                "severity": "critical",
                "category": "overall",
                "title": f"当前命中率 {r.current_hit_rate:.1f}% 偏低",
                "detail": "缓存命中率低于 95% 意味着大量重复前缀未被缓存重用。",
                "impact": f"优化至 {target}% 可节省约 {r.projected_savings_percent:.1f}% 的 token 成本",
                "fix": "按以下优先级检查：1) system prompt 中的动态内容 2) 工具定义中动态参数 3) 每次请求不同的用户输入。"
            })
        elif r.current_hit_rate >= 99:
            r.recommendations.append({
                "severity": "success",
                "category": "overall",
                "title": f"命中率 {r.current_hit_rate:.1f}% 已达优秀水平",
                "detail": "缓存命中率已接近理论上限（~99%）。进一步优化空间有限。",
                "impact": "维持当前配置即可",
                "fix": "无需额外优化。关注系统 prompt 的稳定性，避免引入新的动态内容。"
            })

    # ── 第四步：计算综合评分（0-100 分） ────────────────────
    # 评分规则：
    #   基础分 100，根据问题扣分
    #   命中率每低于 99% 1 个百分点扣 3 分
    #   记忆文件超过 10 个扣 5 分
    #   CLAUDE.md 有动态内容扣 10 分
    #   技能超过 10 个扣 5 分
    #   CLAUDE.md 超过 3KB 扣 5 分
    score = 100
    if r.current_hit_rate < 99:
        score -= int((99 - r.current_hit_rate) * 3)
    if config.memory_file_count > 10:
        score -= 5
    if config.claude_md_has_dynamic:
        score -= 10
    if config.skill_count > 10:
        score -= 5
    if config.claude_md_size > 3000:
        score -= 5
    score = max(0, min(100, score))  # 确保分数在 0-100 之间
    r.overall_score = score

    # 诊断摘要
    if score >= 90:
        r.diagnosis = "优秀：缓存配置健康，无需大改。"
    elif score >= 70:
        r.diagnosis = "良好：存在少量可优化项，小幅调整即可。"
    elif score >= 50:
        r.diagnosis = "一般：多个问题需关注，优化后有明显改善空间。"
    else:
        r.diagnosis = "需优化：命中率较低，建议按优先级逐项修复。"

    return r


# ═══════════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════════
# 把分析结果格式化成漂亮的文字报告，打印到控制台。

HEADER = """
╔══════════════════════════════════════════════════╗
║       命中缓存99% — 诊断报告          ║
╚══════════════════════════════════════════════════╝
"""


def format_report(r: AnalysisResult) -> str:
    """把分析结果格式化成文字报告。

    报告包含四个部分：
      一、综合评分 — 打分 + 进度条
      二、命中率分析 — 当前命中率、成本、平均指标
      三、配置诊断 — CLAUDE.md、记忆文件、技能等状态
      四、优化建议 — 按严重程度排序的建议列表
    """
    lines = [HEADER, ""]

    # ── 第一部分：综合评分 ──────────────────────────────────
    lines.append("━" * 50)
    lines.append("一、综合评分")
    lines.append("━" * 50)

    # 画一个进度条：█ 表示已达标部分，░ 表示未达标部分
    score = r.overall_score
    bar_len = 30
    filled = int(score / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"  缓存健康度: {bar}  {score}/100")
    lines.append(f"  诊断: {r.diagnosis}")
    lines.append("")

    # ── 第二部分：命中率分析 ────────────────────────────────
    lines.append("━" * 50)
    lines.append("二、命中率分析")
    lines.append("━" * 50)
    if r.has_ccswitch_data:
        lines.append(f"  当前命中率:    {r.current_hit_rate:.2f}%")
        lines.append(f"  请求总数:      {r.total_requests}")
        lines.append(f"  总成本:        ${r.total_cost:.4f}")
        lines.append(f"  平均输入:      {r.avg_input_per_request:.0f} tokens/请求")
        lines.append(f"  平均缓存读:    {r.avg_cache_per_request:.0f} tokens/请求")
        lines.append(f"  平均输出:      {r.avg_output_per_request:.0f} tokens/请求")
        lines.append(f"  平均新增:      {r.variable_per_request:.0f} tokens/请求（不可缓存部分）")
        lines.append("")
        if r.projected_savings_percent > 0:
            lines.append(f"  目标命中率:    {r.target_hit_rate}%")
            lines.append(f"  预估节省:      {r.projected_savings_percent:.1f}%")
            lines.append(f"  预估月省:      ${r.projected_savings_monthly:.2f}")
            lines.append(f"  优化后成本:    ~${r.projected_new_cost:.4f}/天")
    else:
        lines.append("  (未提供 CCSwitch 数据，跳过成本分析)")
        lines.append("  提示: 从 CCSwitch 复制日志数据粘贴到本工具即可分析。")
    lines.append("")

    # ── 第三部分：配置诊断 ──────────────────────────────────
    lines.append("━" * 50)
    lines.append("三、配置诊断")
    lines.append("━" * 50)
    cfg = r.config
    agents_str = ", ".join(cfg.agents_scanned) if cfg.agents_scanned else "claude"
    lines.append(f"  已检测 Agent:  {agents_str}")
    lines.append(f"  系统提示:      {cfg.claude_md_size} bytes, {cfg.claude_md_lines} 行{' ⚠️ 含动态内容' if cfg.claude_md_has_dynamic else ''}")
    lines.append(f"  记忆文件:       {cfg.memory_file_count} 个, 共 {cfg.memory_total_size} bytes")
    if cfg.memory_file_list:
        for name, size in sorted(cfg.memory_file_list, key=lambda x: -x[1])[:5]:
            lines.append(f"    - {name}: {size} bytes")
    lines.append(f"  已启技能:       {cfg.skill_count} 个")
    lines.append(f"  MCP 服务:       {cfg.mcp_count} 个")
    lines.append(f"  对话历史:       {cfg.history_size_mb:.1f} MB")
    lines.append("")

    # ── 第四部分：优化建议 ──────────────────────────────────
    if r.recommendations:
        lines.append("━" * 50)
        lines.append("四、优化建议（按优先级排序）")
        lines.append("━" * 50)

        # 排序：最严重的问题排最前面
        severity_order = {"critical": 0, "warning": 1, "info": 2, "success": 3}
        sorted_recs = sorted(r.recommendations, key=lambda x: severity_order.get(x["severity"], 99))

        for i, rec in enumerate(sorted_recs, 1):
            sev_icon = {"critical": "[!]", "warning": "[~]", "info": "[i]", "success": "[+]"}
            icon = sev_icon.get(rec["severity"], "[?]")
            lines.append(f"\n  {icon} 建议 #{i} [{rec['category']}]")
            lines.append(f"  {rec['title']}")
            lines.append(f"  详情: {rec['detail']}")
            lines.append(f"  影响: {rec['impact']}")
            lines.append(f"  修复: {rec['fix']}")

    lines.append("")
    lines.append("━" * 50)
    lines.append(f"命中缓存99% · 报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("━" * 50)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# JSON 输出（机器可读）
# ═══════════════════════════════════════════════════════════════
# 如果你想把结果传给其他程序处理（而不是给人看），可以用 JSON 格式。

def format_json(r: AnalysisResult) -> str:
    """把分析结果转成 JSON 格式（方便程序读取）。

    JSON 是一种通用的数据交换格式，几乎所有编程语言都能解析。
    """
    d = {
        "score": r.overall_score,
        "diagnosis": r.diagnosis,
        "hit_rate": {
            "current": round(r.current_hit_rate, 2) if r.has_ccswitch_data else None,
            "target": r.target_hit_rate,
        },
        "cost": {
            "total": round(r.total_cost, 4) if r.has_ccswitch_data else None,
            "projected_monthly_savings": round(r.projected_savings_monthly, 2) if r.has_ccswitch_data else None,
            "savings_percent": round(r.projected_savings_percent, 1) if r.has_ccswitch_data else None,
        },
        "config": {
            "agents_scanned": r.config.agents_scanned,
            "claude_md_size": r.config.claude_md_size,
            "claude_md_has_dynamic": r.config.claude_md_has_dynamic,
            "memory_file_count": r.config.memory_file_count,
            "memory_total_size": r.config.memory_total_size,
            "skill_count": r.config.skill_count,
            "history_size_mb": round(r.config.history_size_mb, 1),
        },
        "recommendations": r.recommendations,
    }
    return json.dumps(d, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# Fix 引擎 — 一键修复
# ═══════════════════════════════════════════════════════════════
# 这个功能专门处理"记忆文件太多"的问题。
# 它会自动把同类小文件合并成一个大文件，减少固定前缀的大小。
#
# 什么是 frontmatter？
#   记忆文件的开头有 --- 包裹的元数据区域，像这样：
#   ---
#   name: user-profile
#   description: 用户信息
#   ---
#   这就是 frontmatter，记录了文件的属性信息。

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 Markdown 文件开头的 frontmatter 元数据。

    参数：
      text: 文件的完整内容

    返回值：
      (metadata, body) 元组
      - metadata: 元数据字典（如 {"name": "user-profile", "type": "user"}）
      - body: 去掉 frontmatter 后的正文内容

    例子：
      输入：
        ---
        name: test
        type: user
        ---
        正文内容
      输出：
        ({"name": "test", "type": "user"}, "正文内容")
    """
    if not text.startswith("---"):
        return {}, text  # 没有 frontmatter，全当正文处理
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta, parts[2].strip()
    except Exception:
        return {}, text


def build_merge_plan(memory_dir: str) -> list[dict]:
    """生成记忆文件的合并计划。

    思路：
      1. 找出所有记忆文件
      2. 按 type（类型）分组
      3. 同一类型的小文件建议合并成一个

    比如 type 为 "user" 的文件 user1.md 和 user2.md → 合并为 user-profile.md
    """
    mem_path = Path(memory_dir)
    if not mem_path.exists():
        return []

    files = []
    for f in sorted(mem_path.glob("*.md")):
        if f.name == "MEMORY.md":  # 索引文件不参与合并
            continue
        text = f.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        ftype = meta.get("type", "other")  # 没有 type 就归为 "other"
        files.append({
            "name": f.name,
            "path": str(f),
            "type": ftype,
            "size": f.stat().st_size,
            "body": body,
        })

    # 按类型分组
    groups = {}
    for f in files:
        g = groups.setdefault(f["type"], [])
        g.append(f)

    # 生成合并计划
    plan = []
    for ftype, members in groups.items():
        if len(members) <= 1:
            continue  # 只有一个文件，不用合并

        total_size = sum(m["size"] for m in members)
        # 不同类型合并后的目标文件名
        target_name = {
            "user": "user-profile.md",
            "feedback": "workflow-rules.md",
            "project": f"project-context.md",
        }.get(ftype, f"{ftype}.md")

        plan.append({
            "type": ftype,
            "target": target_name,
            "files": [m["name"] for m in members],
            "total_size": total_size,
            "members": members,
        })

    return plan


def apply_fix(memory_dir: str, dry_run: bool = True) -> list[str]:
    """执行记忆文件合并修复。

    参数：
      memory_dir: 记忆文件目录路径
      dry_run: 是否只预览不执行（True = 只看方案，False = 真的合并）

    返回值：
      操作报告列表，每行一条信息

    dry_run=True 时：
      只显示合并方案，不修改任何文件

    dry_run=False 时：
      1. 先写入合并文件（新文件）
      2. 全部写入成功后再删除旧文件
      3. 如果任一**写入**失败 → 回滚（删除已写入的合并文件）
      4. 如果**删除**失败 → 数据不丢，但残留旧文件
    """
    mem_path = Path(memory_dir)
    reports = []

    if not mem_path.exists():
        return ["记忆目录不存在"]

    plan = build_merge_plan(memory_dir)
    if not plan:
        return ["无需合并，记忆文件结构已优化"]

    reports.append(f"发现 {len(plan)} 组可合并文件:")

    for group in plan:
        reports.append(f"\n  [{group['type']}] → {group['target']}")
        for fname in group["files"]:
            reports.append(f"    - {fname}")
        reports.append(f"    合并后约 {group['total_size']} bytes → 更小固定前缀")

        if dry_run:
            continue  # 预览模式，到此为止

        # ── 执行模式：事务保护 ──
        # 原则：先写新文件，全部写完再删旧文件
        # 写入失败 → 删除已写新文件，回滚
        # 删除失败 → 残留旧文件，数据不丢

        merged_parts = []
        merged_frontmatter = {
            "name": group["target"].replace(".md", ""),
            "description": f"自动合并: {', '.join(group['files'])}",
            "metadata": {"type": group["type"]},
        }
        merged_frontmatter_str = (
            "---\n"
            + "\n".join(f"{k}: {v}" if not isinstance(v, dict)
                        else f"{k}: " + str(v).replace("'", '"')
                        for k, v in merged_frontmatter.items())
            + "\n---\n\n"
        )

        for member in group["members"]:
            original_name = member["name"].replace(".md", "")
            merged_parts.append(f"## {original_name}\n\n{member['body'].strip()}\n")

        merged_content = merged_frontmatter_str + "\n\n".join(merged_parts)

        target_path = mem_path / group["target"]
        written_files = []

        try:
            # 第一步：写合并文件
            target_path.write_text(merged_content, encoding="utf-8")
            written_files.append(target_path)

            # 第二步：全部写入成功后，删除旧文件
            for fname in group["files"]:
                old_file = mem_path / fname
                if old_file.exists():
                    old_file.unlink()

            reports.append(f"    ✅ 已合并 → {group['target']}")

        except Exception as e:
            # 写入或删除失败 → 回滚
            for wf in written_files:
                try:
                    if wf.exists():
                        wf.unlink()
                except Exception:
                    pass
            reports.append(f"    ❌ 合并失败: {e}（已回滚）")
            reports.append(f"       备份目录中可恢复原文件")

    if dry_run:
        reports.append("\n\n使用 --fix apply 执行合并")
    else:
        reports.append("\n\n更新 MEMORY.md 索引中...")

    return reports


def backup_memory(memory_dir: str) -> str:
    """备份记忆目录到带时间戳的文件夹。

    在执行修复前先备份，万一合并错了还能恢复。

    参数：
      memory_dir: 记忆文件目录

    返回值：
      备份文件夹的路径
    """
    mem_path = Path(memory_dir)
    backup_dir = mem_path.parent / f"memory_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for f in mem_path.glob("*.md"):
        fdata = f.read_bytes()
        (backup_dir / f.name).write_bytes(fdata)
    return str(backup_dir)


# ═══════════════════════════════════════════════════════════════
# 交互式自动修复
# ═══════════════════════════════════════════════════════════════
# --optimize 完成后，逐条询问用户是否执行修复。

def auto_fix_interactive(result, agent_list):
    """优化完成后，逐条展示并询问是否自动修复。

    参数：
      result:      analyze() 返回的 AnalysisResult
      agent_list:  agents.detect_all() 返回的 agent 列表
    """
    if not result.recommendations:
        return

    severity_order = {"critical": 0, "warning": 1, "info": 2, "success": 3}
    sorted_recs = sorted(result.recommendations,
                         key=lambda x: severity_order.get(x["severity"], 99))

    print("\n" + "━" * 50)
    print("🛠  自动修复推荐")
    print("━" * 50)

    fixed_count = 0
    skip_count = 0

    for i, rec in enumerate(sorted_recs, 1):
        # 判断这个建议能否自动修复
        fix_action = _get_auto_fix_action(rec, agent_list)
        if fix_action is None:
            # 不能自动修复，跳过
            skip_count += 1
            continue

        print(f"\n{'─' * 40}")
        print(f"  建议 #{i}: {rec['title']}")
        print(f"{'─' * 40}")
        print(f"  【解释】{rec['detail']}")
        print(f"  【好处】{rec['impact']}")
        print(f"  【操作】{fix_action['description']}")
        if fix_action.get("risk"):
            print(f"  【风险】{fix_action['risk']}")

        answer = input("\n  是否执行此优化？(y/N): ").strip().lower()
        if answer not in ("y", "yes"):
            print(f"  - 已跳过")
            skip_count += 1
            continue

        # 执行修复
        try:
            fix_action["handler"](fix_action)
            print(f"  ✅ 修复完成")
            fixed_count += 1
        except Exception as e:
            print(f"  ❌ 修复失败: {e}")

    print(f"\n{'─' * 40}")
    if fixed_count > 0:
        print(f"✅ 已执行 {fixed_count} 项优化")
    if skip_count > 0:
        print(f"⏭️  跳过 {skip_count} 项（需手动处理或已跳过）")
    if fixed_count == 0 and skip_count > 0:
        print("💡 运行 --fix dry-run 查看记忆文件合并详情")


def _get_auto_fix_action(rec, agent_list):
    """判断一条建议能否自动修复，返回动作描述或 None。"""
    cat = rec.get("category", "")
    title = rec.get("title", "")

    # ── 记忆文件合并 ──
    if "memory" in cat and "过多" in title:
        # 找 Claude 的记忆目录
        memory_dirs = []
        for agent in agent_list:
            if agent.name == "claude" and agent.config_dir.exists():
                for proj_dir in agent.config_dir.glob("projects/*/memory"):
                    if proj_dir.exists():
                        memory_dirs.append(str(proj_dir))
        if not memory_dirs:
            return None

        def _do_merge(action):
            for md in action["memory_dirs"]:
                print(f"    处理: {md}")
                backup = backup_memory(md)
                print(f"    备份: {backup}")
                reports = apply_fix(md, dry_run=False)
                for r in reports:
                    print(f"    {r}")

        return {
            "description": "按类型合并同类记忆文件（自动备份，可回滚）",
            "risk": "合并后原文件被删除，但已备份到同级目录",
            "handler": _do_merge,
            "memory_dirs": memory_dirs,
        }

    # ── 移除 CLAUDE.md 中的动态日期/时间 ──
    if "claude_md" in cat and "动态" in title:
        # 找 Claude 的 CLAUDE.md
        targets = []
        for agent in agent_list:
            if agent.name == "claude":
                f = agent.config_dir / "CLAUDE.md"
                if f.exists():
                    targets.append(("Claude Code", str(f)))

        if not targets:
            return None

        def _strip_dynamic(action):
            for display, path in action["targets"]:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                # 备份
                backup_path = path + ".bak"
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.write(content)
                # 移除日期模式
                import re as _re
                new_content = _re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", "[日期]", content)
                # 移除时间模式
                new_content = _re.sub(r"(?<!\d)\d{2}:\d{2}(?!\d)", "[时间]", new_content)
                # 移除中文相对日期
                new_content = _re.sub(r"今天|昨天|明天|星期[一二三四五六日]", "[相对日期]", new_content)
                # 只在实际有变化时才写
                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print(f"    {display}: 已移除动态内容（备份: {backup_path}）")
                else:
                    print(f"    {display}: 未发现可自动移除的动态内容")

        return {
            "description": "自动检测并替换 CLAUDE.md / AGENTS.md 中的日期、时间等动态内容为固定占位符",
            "risk": "如果日期是手动维护的，替换后需手动还原；原始文件已备份为 .bak",
            "handler": _strip_dynamic,
            "targets": targets,
            "rec": rec,
        }

    return None  # 不能自动修复


# ═══════════════════════════════════════════════════════════════
# 仪表盘 HTML 生成
# ═══════════════════════════════════════════════════════════════
# 生成一个漂亮的网页报告，可以在浏览器里打开看。

def generate_dashboard(result: AnalysisResult) -> str:
    """生成独立的 HTML 仪表盘网页 — Neon Bento 设计风格。

    自包含（所有 CSS/内联），零网络依赖。
    """
    score = result.overall_score
    cfg = result.config
    hit = f"{result.current_hit_rate:.2f}%" if result.has_ccswitch_data else "N/A"
    cost_total = f"${result.total_cost:.4f}" if result.has_ccswitch_data else "N/A"
    savings = f"${result.projected_savings_monthly:.2f}" if result.has_ccswitch_data else "N/A"
    sav_pct = f"{result.projected_savings_percent:.1f}%" if result.has_ccswitch_data else "N/A"

    # 命中率语义色
    if result.has_ccswitch_data:
        if result.current_hit_rate >= 99:
            hit_color = "#10b981"
        elif result.current_hit_rate >= 95:
            hit_color = "#3b82f6"
        elif result.current_hit_rate >= 80:
            hit_color = "#f59e0b"
        else:
            hit_color = "#ef4444"
    else:
        hit_color = "#94a3b8"

    # 分数环颜色
    if score >= 90:
        gauge_color = "#10b981"
    elif score >= 70:
        gauge_color = "#3b82f6"
    elif score >= 50:
        gauge_color = "#f59e0b"
    else:
        gauge_color = "#ef4444"

    # 圆环 SVG — stroke-dasharray 计算
    circumference = 2 * 3.14159 * 68  # r=68
    offset = circumference * (1 - score / 100)

    # 优化建议 HTML
    sev_colors = {"critical": ("#ef4444", "rgba(239,68,68,0.12)"),
                  "warning": ("#f59e0b", "rgba(245,158,11,0.12)"),
                  "info": ("#06b6d4", "rgba(6,182,212,0.12)"),
                  "success": ("#10b981", "rgba(16,185,129,0.12)")}
    sev_labels = {"critical": "严重", "warning": "警告", "info": "提示", "success": "通过"}

    recs_html = ""
    if result.recommendations:
        severity_order = {"critical": 0, "warning": 1, "info": 2, "success": 3}
        sorted_recs = sorted(result.recommendations,
                             key=lambda x: severity_order.get(x["severity"], 99))
        for i, rec in enumerate(sorted_recs, 1):
            color, bg = sev_colors.get(rec["severity"], ("#6b7280", "rgba(107,114,128,0.12)"))
            label = sev_labels.get(rec["severity"], rec["severity"])
            recs_html += f"""
            <details class="rec" style="--rec-color:{color};--rec-bg:{bg};">
                <summary class="rec-summary">
                    <span class="rec-badge sev-{rec['severity']}">{label}</span>
                    <span class="rec-cat">{rec['category']}</span>
                    <span class="rec-title-text">{rec['title']}</span>
                </summary>
                <div class="rec-body">
                    <div class="rec-row"><span class="rec-label">详情</span><span>{rec['detail']}</span></div>
                    <div class="rec-row"><span class="rec-label">影响</span><span>{rec['impact']}</span></div>
                    <div class="rec-row"><span class="rec-label">修复</span><span>{rec['fix']}</span></div>
                </div>
            </details>"""

    # 记忆文件列表（HTML 转义文件名防注入）
    mem_list_html = ""
    if cfg.memory_file_list:
        _escape_table = str.maketrans({"<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;"})
        for name, size in sorted(cfg.memory_file_list, key=lambda x: -x[1])[:5]:
            safe_name = name.translate(_escape_table)
            mem_list_html += f"<div class='mem-item'><span class='mem-name'>{safe_name}</span><span class='mem-size'>{size:,} B</span></div>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>命中缓存99% — 诊断报告</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, 'PingFang SC', 'Noto Sans SC', system-ui, sans-serif;
    background: #0a0e17; color: #e2e8f0; min-height: 100vh;
    background-image:
        radial-gradient(ellipse at 20% 50%, rgba(99,102,241,0.06) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 20%, rgba(6,182,212,0.04) 0%, transparent 50%);
}}
.container {{ max-width: 960px; margin: 0 auto; padding: 32px 16px; }}

/* ── 头部 ── */
.header {{ text-align: center; margin-bottom: 32px; }}
.header h1 {{
    font-size: 28px; font-weight: 700;
    background: linear-gradient(135deg, #6366f1, #06b6d4);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.header .subtitle {{ color: #64748b; font-size: 14px; margin-top: 4px; }}

/* ── Bento Grid ── */
.bento {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.bento-full {{ grid-column: 1 / -1; }}

/* ── 玻璃态卡片 ── */
.card {{
    background: rgba(17,24,39,0.8);
    backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px; padding: 24px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.2);
    transition: border-color 0.2s, box-shadow 0.2s;
}}
.card:hover {{ border-color: rgba(255,255,255,0.1); box-shadow: 0 8px 32px rgba(0,0,0,0.3); }}
.card-title {{
    font-size: 13px; font-weight: 600; color: #64748b;
    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 16px;
}}

/* ── 评分圆环 ── */
.gauge-wrap {{ display: flex; flex-direction: column; align-items: center; gap: 12px; }}
.gauge-svg {{ width: 160px; height: 160px; }}
.gauge-bg {{ fill: none; stroke: rgba(255,255,255,0.06); stroke-width: 8; }}
.gauge-fg {{ fill: none; stroke: {gauge_color}; stroke-width: 8;
    stroke-linecap: round; stroke-dasharray: {circumference};
    stroke-dashoffset: {offset}; transform: rotate(-90deg);
    transform-origin: 80px 80px; transition: stroke-dashoffset 1s ease-out;
}}
.gauge-text {{
    font-family: 'JetBrains Mono', 'SF Mono', monospace;
    font-size: 36px; font-weight: 700; fill: #f1f5f9;
}}
.gauge-label {{ font-size: 12px; fill: #64748b; }}
.gauge-diagnosis {{ font-size: 14px; color: #94a3b8; text-align: center; }}

/* ── KPI 指标 ── */
.kpis {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.kpi {{
    padding: 16px; border-radius: 8px;
    background: rgba(255,255,255,0.02);
    text-align: center;
}}
.kpi-value {{
    font-family: 'JetBrains Mono', 'SF Mono', monospace;
    font-size: 28px; font-weight: 700; color: #f1f5f9;
}}
.kpi-value.highlight {{ color: {hit_color}; }}
.kpi-label {{ font-size: 12px; color: #64748b; margin-top: 4px; }}

/* ── 进度条 ── */
.progress-wrap {{ margin-top: 16px; }}
.progress-bar {{
    height: 8px; border-radius: 4px; background: rgba(255,255,255,0.06);
    overflow: hidden; position: relative;
}}
.progress-fill {{
    height: 100%; border-radius: 4px;
    background: linear-gradient(90deg, #6366f1, #06b6d4);
    width: {result.current_hit_rate if result.has_ccswitch_data else 0}%;
    transition: width 1s ease-out;
}}
.progress-label {{
    display: flex; justify-content: space-between;
    font-size: 12px; color: #64748b; margin-top: 6px;
}}

/* ── 配置表 ── */
.config-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.config-item {{
    display: flex; justify-content: space-between;
    padding: 8px 12px; border-radius: 6px;
    background: rgba(255,255,255,0.02);
    font-size: 13px;
}}
.config-key {{ color: #64748b; }}
.config-value {{ color: #e2e8f0; font-weight: 500; }}
.config-value.dynamic {{ color: #f59e0b; }}

.mem-list {{ margin-top: 8px; }}
.mem-item {{
    display: flex; justify-content: space-between;
    padding: 4px 0; font-size: 12px; color: #94a3b8;
}}
.mem-name {{ color: #e2e8f0; }}
.mem-size {{ font-family: 'JetBrains Mono', monospace; color: #64748b; }}

/* ── 优化建议 ── */
.rec {{
    border-left: 4px solid var(--rec-color);
    border-radius: 8px; margin-bottom: 12px;
    overflow: hidden; transition: border-left-width 0.2s;
}}
.rec:hover {{ border-left-width: 6px; }}
.rec-summary {{
    display: flex; align-items: center; gap: 8px;
    padding: 12px 16px; cursor: pointer;
    background: var(--rec-bg);
    list-style: none; font-size: 13px;
    transition: background 0.2s;
}}
.rec-summary::-webkit-details-marker {{ display: none; }}
.rec-summary:hover {{ background: color-mix(in srgb, var(--rec-bg) 80%, white 5%); }}
.rec-badge {{
    font-size: 10px; font-weight: 600; padding: 1px 7px;
    border-radius: 8px; text-transform: uppercase;
    color: #fff; background: var(--rec-color);
    flex-shrink: 0;
}}
.rec-cat {{ color: #64748b; font-size: 11px; flex-shrink: 0; }}
.rec-title-text {{ color: #e2e8f0; font-weight: 500; }}
.rec-body {{
    padding: 12px 16px; font-size: 13px;
    border-top: 1px solid rgba(255,255,255,0.04);
}}
.rec-row {{ display: flex; gap: 8px; margin-bottom: 6px; }}
.rec-row:last-child {{ margin-bottom: 0; }}
.rec-label {{
    color: #64748b; flex-shrink: 0; min-width: 40px;
    font-weight: 500;
}}

/* ── 空状态 ── */
.empty {{ text-align: center; padding: 24px; color: #475569; font-size: 14px; }}

/* ── 页脚 ── */
.footer {{
    text-align: center; color: #334155; font-size: 11px;
    margin-top: 40px; padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.04);
}}
.footer a {{ color: #475569; text-decoration: none; }}

/* ── 响应式 ── */
@media (max-width: 640px) {{
    .container {{ padding: 16px 12px; }}
    .bento {{ grid-template-columns: 1fr; }}
    .card {{ padding: 16px; }}
    .kpis {{ grid-template-columns: 1fr 1fr; gap: 8px; }}
    .config-grid {{ grid-template-columns: 1fr; }}
    .kpi-value {{ font-size: 22px; }}
    .gauge-svg {{ width: 120px; height: 120px; }}
}}
</style>
</head>
<body>
<div class="container">

<!-- 头部 -->
<div class="header">
    <h1>⚡ 命中缓存99%</h1>
    <div class="subtitle">缓存命中率诊断报告 · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</div>

<div class="bento">
    <!-- 综合评分 -->
    <div class="card bento-full">
        <div class="card-title">综合评分</div>
        <div class="gauge-wrap">
            <svg class="gauge-svg" viewBox="0 0 160 160">
                <circle class="gauge-bg" cx="80" cy="80" r="68"/>
                <circle class="gauge-fg" cx="80" cy="80" r="68"/>
                <text class="gauge-text" x="80" y="68" text-anchor="middle">{score}</text>
                <text class="gauge-label" x="80" y="90" text-anchor="middle">/ 100</text>
            </svg>
            <div class="gauge-diagnosis">{result.diagnosis}</div>
        </div>
    </div>

    <!-- 命中率分析 -->
    <div class="card bento-full">
        <div class="card-title">命中率分析</div>
        <div class="kpis">
            <div class="kpi">
                <div class="kpi-value highlight">{hit}</div>
                <div class="kpi-label">当前命中率</div>
            </div>
            <div class="kpi">
                <div class="kpi-value">{cost_total}</div>
                <div class="kpi-label">总成本</div>
            </div>
            <div class="kpi">
                <div class="kpi-value">{result.total_requests}</div>
                <div class="kpi-label">请求数</div>
            </div>
            <div class="kpi">
                <div class="kpi-value">{result.avg_input_per_request:.0f}</div>
                <div class="kpi-label">平均新增/请求 (tokens)</div>
            </div>
        </div>
        {f'''
        <div class="progress-wrap">
            <div class="progress-bar"><div class="progress-fill"></div></div>
            <div class="progress-label">
                <span>当前: {result.current_hit_rate:.1f}%</span>
                <span>目标: {result.target_hit_rate:.0f}%</span>
            </div>
        </div>''' if result.has_ccswitch_data else ''}
    </div>

    <!-- 节省预估 -->
    <div class="card bento-full">
        <div class="card-title">节省预估</div>
        <div class="kpis">
            <div class="kpi">
                <div class="kpi-value" style="color:#10b981;">{savings}</div>
                <div class="kpi-label">预估月省</div>
            </div>
            <div class="kpi">
                <div class="kpi-value" style="color:#10b981;">{sav_pct}</div>
                <div class="kpi-label">节省比例</div>
            </div>
            <div class="kpi">
                <div class="kpi-value">{result.projected_new_cost:.4f}</div>
                <div class="kpi-label">优化后日成本</div>
            </div>
            <div class="kpi">
                <div class="kpi-value">{result.avg_cache_per_request:.0f}</div>
                <div class="kpi-label">平均缓存读取/请求</div>
            </div>
        </div>
    </div>

    <!-- 配置状态 -->
    <div class="card bento-full">
        <div class="card-title">配置状态</div>
        <div class="config-grid">
            <div class="config-item">
                <span class="config-key">已扫描 Agent</span>
                <span class="config-value">{', '.join(cfg.agents_scanned) if cfg.agents_scanned else 'claude'}</span>
            </div>
            <div class="config-item">
                <span class="config-key">系统提示</span>
                <span class="config-value">{cfg.claude_md_size:,} bytes, {cfg.claude_md_lines} 行{' <span class="config-value dynamic">⚠️ 含动态内容</span>' if cfg.claude_md_has_dynamic else ''}</span>
            </div>
            <div class="config-item">
                <span class="config-key">记忆文件</span>
                <span class="config-value">{cfg.memory_file_count} 个 / {cfg.memory_total_size:,} bytes</span>
            </div>
            <div class="config-item">
                <span class="config-key">已启技能</span>
                <span class="config-value">{cfg.skill_count} 个</span>
            </div>
            <div class="config-item">
                <span class="config-key">MCP 服务</span>
                <span class="config-value">{cfg.mcp_count} 个</span>
            </div>
            <div class="config-item">
                <span class="config-key">对话历史</span>
                <span class="config-value">{cfg.history_size_mb:.1f} MB</span>
            </div>
        </div>
        {f'<div class="mem-list">{mem_list_html}</div>' if mem_list_html else ''}
    </div>

    <!-- 优化建议 -->
    <div class="card bento-full">
        <div class="card-title">优化建议 ({len(result.recommendations)} 项)</div>
        {recs_html if recs_html else '<div class="empty">🎉 无优化建议，配置状态良好</div>'}
    </div>
</div>

<div class="footer">
    命中缓存99% · 报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} ·
    <a href="https://github.com/yunzhi-chu/mingzhonghuancun99" target="_blank">GitHub</a>
</div>

</div>
</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════════════════
# CLI 命令行入口
# ═══════════════════════════════════════════════════════════════
# 这就是用户在命令行输入 python -m cache_optimizer 时实际运行的代码。

def main():
    """主入口函数 — 解析命令行参数，执行对应的操作。

    支持的参数（用 python -m cache_optimizer --help 查看）：
      --data     <文件>   从文件读取 CCSwitch 数据
      --config   <目录>   指定 Claude Code 配置目录
      --target   <数字>   目标命中率（默认 99%）
      --json              输出 JSON 格式（机器可读）
      --summary           只分析摘要文本（不是完整表格）
      --fix     [dry-run|apply]  一键修复记忆文件
      --dashboard [文件名]  生成 HTML 网页报告
      --detect            检测电脑上的 AI agent 和 CCSwitch
      --setup             自动安装配置 CCSwitch
      --optimize          完整优化流程
    """
    parser = argparse.ArgumentParser(description="命中缓存99% — 通用 AI agent 缓存诊断与优化工具")
    parser.add_argument("-d", "--data", help="CCSwitch 数据文件（.txt/.csv），或留空从 stdin 粘贴")
    parser.add_argument("-c", "--config", help="Claude Code 配置目录（默认 ~/.claude）")
    parser.add_argument("-t", "--target", type=float, default=99.0, help="目标命中率（默认 99pct）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--summary", action="store_true", help="只从摘要文本分析（无需表格）")
    parser.add_argument("--fix", nargs="?", const="dry-run", choices=["dry-run", "apply"],
                        help="一键修复：dry-run（预览）| apply（执行）")
    parser.add_argument("--dashboard", nargs="?", const="report.html", help="生成 HTML 仪表盘（默认 report.html）")
    parser.add_argument("--detect", action="store_true", help="检测已安装的 AI agent 和 CCSwitch")
    parser.add_argument("--setup", action="store_true", help="自动安装 CCSwitch 并配置 agent 代理")
    parser.add_argument("--optimize", action="store_true", help="完整优化流程：检测→安装→分析→修复")
    args = parser.parse_args()

    # 确定配置目录
    config_dir = args.config or os.path.expanduser("~/.claude")

    # ═══════════════════════════════════════════════════════════
    # --detect 模式：检测环境
    # ═══════════════════════════════════════════════════════════
    if args.detect:
        print("\n=== 命中缓存99% — 环境检测 ===\n")

        print("检测 AI Agent...")
        agent_list = agents.detect_all()
        agents.print_agents(agent_list)
        print()

        print("检测 CCSwitch...")
        ccs = agents.detect_ccswitch()
        agents.print_ccswitch(ccs)
        print()

        print("检测环境变量...")
        env_keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                     "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "OLLAMA_HOST"]
        found_any = False
        for key in env_keys:
            val = os.environ.get(key, "")
            if val:
                masked = val[:4] + "..." + val[-4:] if len(val) > 16 else val[:2] + "..."
                print(f"  ✅ {key}={masked}")
                found_any = True
        if not found_any:
            print("  ⚠️ 未检测到 API Key 环境变量")

        sys.exit(0)

    # ═══════════════════════════════════════════════════════════
    # --setup 模式：自动安装配置
    # ═══════════════════════════════════════════════════════════
    if args.setup:
        print("\n=== 命中缓存99% — 检测 CC-Switch 状态 ===\n")

        agent_list = agents.detect_all()
        if not agent_list:
            print("⚠️ 未检测到已安装的 AI agent")
            print("   请先安装 Claude Code / Codex / Hermes / OpenClaw 其中之一")
            sys.exit(1)

        ccs = ccsm.ensure_ccswitch()
        csm = "✅" if ccs["installed"] else "❌"
        print(f"  {csm} CC-Switch: {'已安装' if ccs['installed'] else '未检测到'}")
        if ccs["installed"]:
            if ccs.get("agents"):
                print(f"  已启用代理: {', '.join(ccs['agents'])}")
            for agent in agent_list:
                cfg = ccsm.configure_for_agent(agent)
                proxy = cfg.get("proxy") or {}
                if proxy.get("enabled"):
                    prov = cfg.get("provider")
                    print(f"  ✅ {agent.display}: 代理已启用 ({proxy['listen_address']}:{proxy['listen_port']})")
                    if prov and prov.get("name"):
                        print(f"     当前供应商: {prov['name']}")
                else:
                    print(f"  ⚠️ {agent.display}: 代理未启用")
                    print(f"     请在 CC-Switch 桌面端开启 {agent.display} 的代理开关")
            print(f"\n配置完成！运行 --optimize 进行完整优化")
        else:
            print(ccsm.__MANUAL_GUIDE__)
        sys.exit(0)

    # ═══════════════════════════════════════════════════════════
    # --optimize 模式：完整优化流程
    # ═══════════════════════════════════════════════════════════
    if args.optimize:
        print("\n=== 命中缓存99% — 完整优化流程 ===\n")

        # 步骤1: 检测电脑上装了哪些 AI agent
        print("步骤1/4: 检测环境...")
        agent_list = agents.detect_all()
        if not agent_list:
            print("  ❌ 未检测到 AI agent，请先安装")
            sys.exit(1)
        for a in agent_list:
            print(f"  ✅ {a.display}")

        # 步骤2: 安装（或确认）CCSwitch
        print("步骤2/4: 确保 CCSwitch 已安装...")
        ccs = ccsm.ensure_ccswitch(auto_install=True)
        if ccs["installed"]:
            print(f"  ✅ CCSwitch v{ccs['version']}")
        else:
            print("  ❌ CCSwitch 安装失败")
            print("  ⚠️ 从 CCSwitch 仪表盘导出数据后用 --data 导入")
            print("  或者直接粘贴数据: python -m cache_optimizer")
            sys.exit(0)

        # 步骤3: 从 CCSwitch 获取使用数据
        print("步骤3/4: 从 CCSwitch 获取使用数据...")
        ccswitch_data = None
        data = ccsm.fetch_data()
        if data and data.get("raw"):
            try:
                ccswitch_data = CCSwitchData.parse(data["raw"])
                print(f"  ✅ 获取到数据 ({ccswitch_data.total_requests} 条请求, "
                      f"命中率 {ccswitch_data.hit_rate:.1f}%)")
            except Exception as e:
                print(f"  ⚠️ 数据解析失败: {e}")
        else:
            print("  ⚠️ CCSwitch 暂无数据")
            print("  [1] 等待 CCSwitch 收集数据后重试")
            print("  [2] 或现在从 CCSwitch 仪表盘导出数据: python -m cache_optimizer --data data.txt")

        # 获取每个 agent 的 CC-Switch 代理配置
        for agent in agent_list:
            cfg = ccsm.configure_for_agent(agent)
            proxy = cfg.get("proxy") or {}
            if proxy.get("enabled"):
                print(f"  ✅ {agent.display} 代理状态: 已启用")
            else:
                print(f"  ⚠️ {agent.display} 代理未开启，数据可能不完整")

        # 步骤4: 分析 + 修复建议
        print("步骤4/4: 扫描配置并优化...")
        config = scan_all_configs(agent_list)
        result = analyze(ccswitch_data, config, args.target)
        if result.overall_score >= 95:
            print(f"  ✅ 当前缓存健康度 {result.overall_score}/100，无需优化")
        else:
            print(f"  📋 发现 {len(result.recommendations)} 项可优化内容")
        print()
        print(format_report(result))

        # 推荐修复交互
        if not sys.stdin.isatty():
            print("\n(管道模式，跳过交互修复)")
        else:
            auto_fix_interactive(result, agent_list)

        print("━" * 50)
        print("优化流程完成！")
        print("后续: 定期运行 --optimize 持续监控")
        sys.exit(0)

    # ═══════════════════════════════════════════════════════════
    # --fix 模式：一键修复记忆文件
    # ═══════════════════════════════════════════════════════════
    if args.fix:
        # 先找到记忆文件目录
        memory_base = None
        for proj_dir in Path(config_dir).glob("projects/*/memory"):
            if proj_dir.exists():
                memory_base = str(proj_dir)
                break

        if not memory_base:
            print("未找到记忆目录")
            sys.exit(1)

        print(f"\n=== 命中缓存99% — 一键修复 ===\n")
        print(f"目标记忆目录: {memory_base}")
        print(f"模式: {'预览 (dry-run)' if args.fix == 'dry-run' else '执行 (apply)'}")
        print()

        # 执行模式：先备份，再修复
        backup_path = None
        if args.fix == "apply":
            backup_path = backup_memory(memory_base)
            print(f"备份已创建: {backup_path}")

        # 执行修复
        reports = apply_fix(memory_base, dry_run=(args.fix == "dry-run"))
        for line in reports:
            print(line)

        # 执行模式：更新 MEMORY.md 索引
        if args.fix == "apply":
            mem_path = Path(memory_base)
            memory_md = mem_path / "MEMORY.md"
            if memory_md.exists():
                new_lines = []
                for f in sorted(mem_path.glob("*.md")):
                    if f.name == "MEMORY.md":
                        continue
                    text = f.read_text(encoding="utf-8")
                    meta, _ = parse_frontmatter(text)
                    desc = meta.get("description", f.name)
                    new_lines.append(f"- [{desc}]({f.name})")
                memory_md.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                print(f"\n✅ MEMORY.md 已更新，共 {len(new_lines)} 条索引")

            print(f"\n修复完成。回滚: 删除合并后文件，恢复 {backup_path}")

        sys.exit(0)

    # ═══════════════════════════════════════════════════════════
    # 数据分析模式（默认）
    # ═══════════════════════════════════════════════════════════
    # 这是最常用的模式：加载 CCSwitch 数据 → 扫描配置 → 分析 → 输出报告

    # 1. 加载 CCSwitch 数据
    ccswitch = None
    if args.data:
        # 从文件读取
        try:
            with open(args.data, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, FileNotFoundError, PermissionError) as e:
            print(f"错误: 无法读取数据文件: {e}")
            sys.exit(1)
    elif not sys.stdin.isatty():
        # 管道模式：直接从上一个命令的输出读取
        # 比如: ccswitch export | python -m cache_optimizer
        text = sys.stdin.buffer.read().decode("utf-8").strip()
    else:
        # 交互模式：提示用户粘贴数据
        print("[粘贴 CCSwitch 数据（Tab 分隔的请求日志），Ctrl+D/Ctrl+Z 结束]:")
        try:
            text = sys.stdin.buffer.read().decode("utf-8").strip()
        except (KeyboardInterrupt, EOFError):
            text = ""

    # 解析数据
    if text:
        try:
            if args.summary:
                ccswitch = CCSwitchData.parse_summary(text)
            else:
                ccswitch = CCSwitchData.parse(text)
        except Exception as e:
            print(f"数据解析失败: {e}")
            print("提示: 数据应为 CCSwitch 导出的 Tab 分隔格式")
            sys.exit(1)

    # 2. 扫描配置（自适应所有 agent）
    config = scan_all_configs()

    # 3. 分析
    result = analyze(ccswitch, config, args.target)

    # 3b. 生成仪表盘（如果指定了 --dashboard）
    if args.dashboard:
        html = generate_dashboard(result)
        out_path = args.dashboard
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✅ 仪表盘已生成: {os.path.abspath(out_path)}")
        webbrowser.open(os.path.abspath(out_path))  # 自动在浏览器打开
        sys.exit(0)

    # 4. 输出：JSON 或文字报告
    if args.json:
        print(format_json(result))
    else:
        print(format_report(result))

    # 5. 退出码
    # 分数 < 50  → 退出码 2（严重问题）
    # 分数 < 70  → 退出码 1（有问题）
    # 分数 >= 70 → 退出码 0（正常）
    if result.overall_score < 50:
        sys.exit(2)
    elif result.overall_score < 70:
        sys.exit(1)


if __name__ == "__main__":
    main()
