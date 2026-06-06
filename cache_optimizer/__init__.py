#!/usr/bin/env python3
"""命中缓存99% — 通用 AI agent 缓存诊断与优化工具。"""

import sys
import argparse

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

from . import agents
from . import ccswitch_manager as ccsm

# ─── 数据模型 ─────────────────────────────────────────────

@dataclass
class RequestLog:
    time: str
    provider: str
    model: str
    new_input: int      # 新增输入 tokens
    cache_read: int     # 缓存读取 tokens (R prefix)
    output: int         # 输出 tokens
    cost: float         # $
    status: str
    source: str

@dataclass
class CCSwitchData:
    requests: list[RequestLog] = field(default_factory=list)
    total_new_input: int = 0
    total_cache_read: int = 0
    total_output: int = 0
    total_cost: float = 0.0
    total_requests: int = 0
    hit_rate: float = 0.0

    @classmethod
    def parse(cls, text: str) -> "CCSwitchData":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return cls()

        data = cls()

        # 检测分隔符
        header = lines[0]
        delimiter = "\t" if "\t" in header else ("," if "," in header else None)
        if delimiter is None:
            # 尝试多空格分隔
            if len(re.split(r"\s{2,}", header)) >= 5:
                reader = csv.reader(lines, delimiter="\t") if "\t" in lines[0] else csv.reader(lines)
            else:
                return cls()
        else:
            reader = csv.reader(lines, delimiter=delimiter)

        rows = list(reader)
        if len(rows) < 2:
            return cls()

        for row in rows[1:]:
            if len(row) < 6:
                continue
            try:
                col_count = len(row)
                if col_count >= 10:
                    # CCSwitch 标准格式: time, provider, model, new_input, R_cache, output, cost, ttf, status, source
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
                    # 紧凑格式: time, provider, model, input, output, cost, status, source
                    time_str = row[0].strip()
                    provider = row[1].strip()
                    model = row[2].strip()
                    # 判断第3列是否包含 R 前缀
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
                        new_input = int(col3.replace(",", ""))
                        cache_read = 0
                        output_tokens = int(col4.replace(",", ""))
                    cost = float(row[6].replace("$", "").replace(",", ""))
                    status = row[7].strip() if len(row) > 7 else ""
                    source = row[8].strip() if len(row) > 8 else ""
                else:
                    continue

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
                continue

        # 汇总
        for r in data.requests:
            data.total_new_input += r.new_input
            data.total_cache_read += r.cache_read
            data.total_output += r.output
            data.total_cost += r.cost
        data.total_requests = len(data.requests)
        total_context = data.total_new_input + data.total_cache_read
        data.hit_rate = (data.total_cache_read / total_context * 100) if total_context > 0 else 0

        return data

    @classmethod
    def parse_summary(cls, text: str) -> Optional["CCSwitchData"]:
        """从 CCSwitch 摘要文本（非表格）中提取关键指标。"""
        data = cls()
        lines = text.strip().split("\n")
        for line in lines:
            try:
                line = line.strip()
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
                # Output
                m = re.match(r"[Oo]utput[：:]\s*([\d.]+)", line)
                if m:
                    data.total_output = int(float(m.group(1)) * multiplier)
                    continue
                # 缓存命中（非率）
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

        total_context = data.total_new_input + data.total_cache_read
        if total_context > 0 and data.hit_rate == 0:
            data.hit_rate = data.total_cache_read / total_context * 100
        if data.total_cost > 0 and data.total_requests == 0:
            data.total_requests = 1

        return data if data.total_requests > 0 else None


# ─── 配置扫描 ─────────────────────────────────────────────

@dataclass
class ConfigIssue:
    severity: str      # critical / warning / info
    category: str      # "memory" / "claude_md" / "settings" / "mcp" / "skills"
    title: str
    detail: str
    impact: str        # 对命中率的影响描述
    fix: str           # 修复建议

@dataclass
class ConfigScanResult:
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


def scan_config(base_dir: str = None) -> ConfigScanResult:
    if base_dir is None:
        base_dir = os.path.expanduser("~/.claude")
    claude_dir = Path(base_dir)
    if not claude_dir.exists():
        return ConfigScanResult()

    result = ConfigScanResult()

    # CLAUDE.md
    cm = claude_dir / "CLAUDE.md"
    if cm.exists():
        content = cm.read_text(encoding="utf-8")
        result.claude_md_size = len(content.encode("utf-8"))
        result.claude_md_lines = content.count("\n") + 1
        # 检测动态内容
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
                impact=f"每次 CI/build 类操作都产生新前缀，命中率损失约 0.1-0.5%",
                fix="将动态内容移至运行时变量或 system-reminder 区域（该区域不在缓存 key 中）。"
            ))
        # 文件大小检查
        if result.claude_md_size > 2048:
            result.issues.append(ConfigIssue(
                severity="info",
                category="claude_md",
                title=f"CLAUDE.md 体积较大 ({result.claude_md_size} bytes)",
                detail="大于 2KB 的 CLAUDE.md 会占用固定前缀空间，增大每轮总输入。",
                impact="每增大 1KB 固定前缀，约增加 $0.0001/请求的成本基数",
                fix="精简 CLAUDE.md 至 1-2KB 以内，非核心内容放入记忆文件按需加载。"
            ))

    # 记忆文件
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

    # settings.json
    sf = claude_dir / "settings.json"
    if sf.exists():
        try:
            s = json.loads(sf.read_text(encoding="utf-8"))
            # 检查 env 中是否有动态值
            env = s.get("env", {})
            for k, v in env.items():
                if "token" in k.lower() or "key" in k.lower() or "secret" in k.lower():
                    if len(v) > 20:
                        result.issues.append(ConfigIssue(
                            severity="info",
                            category="settings",
                            title="settings.json 含长 Token 值",
                            detail=f"{k}={v[:16]}...{v[-4:]}。Token 本身不直接影响命中率，但混淆时可能误认为是动态内容。",
                            impact="无直接影响",
                            fix="确保 token 值不在 CLAUDE.md 或 system prompt 中引用。"
                        ))
            # 检查 enabledPlugins
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

    # MCP
    mcp = claude_dir / "mcp.json"
    if mcp.exists():
        try:
            mc = json.loads(mcp.read_text(encoding="utf-8"))
            result.mcp_count = len(mc.get("mcpServers", {}))
        except json.JSONDecodeError:
            pass

    # 对话历史
    hist = claude_dir / "history.jsonl"
    if hist.exists():
        result.history_size_mb = hist.stat().st_size / (1024 * 1024)

    return result


# ─── 分析引擎 ─────────────────────────────────────────────

@dataclass
class AnalysisResult:
    # CCSwitch 分析
    has_ccswitch_data: bool = False
    current_hit_rate: float = 0.0
    total_requests: int = 0
    total_cost: float = 0.0
    avg_input_per_request: float = 0.0
    avg_output_per_request: float = 0.0
    avg_cache_per_request: float = 0.0
    avg_cost_per_request: float = 0.0
    variable_per_request: float = 0.0  # 平均每轮新增不可缓存部分

    # 配置分析
    config: ConfigScanResult = field(default_factory=ConfigScanResult)

    # 优化预测
    target_hit_rate: float = 99.0
    projected_savings_percent: float = 0.0
    projected_savings_monthly: float = 0.0
    projected_new_cost: float = 0.0
    recommendations: list = field(default_factory=list)

    # 诊断摘要
    diagnosis: str = ""
    overall_score: int = 0      # 0-100


def analyze(ccswitch: Optional[CCSwitchData], config: ConfigScanResult, target: float = 99.0) -> AnalysisResult:
    r = AnalysisResult()
    r.target_hit_rate = target
    r.config = config

    if ccswitch and ccswitch.total_requests > 0:
        r.has_ccswitch_data = True
        r.current_hit_rate = ccswitch.hit_rate
        r.total_requests = ccswitch.total_requests
        r.total_cost = ccswitch.total_cost
        r.avg_input_per_request = ccswitch.total_new_input / ccswitch.total_requests
        r.avg_cache_per_request = ccswitch.total_cache_read / ccswitch.total_requests
        r.avg_output_per_request = ccswitch.total_output / ccswitch.total_requests
        r.avg_cost_per_request = ccswitch.total_cost / ccswitch.total_requests
        r.variable_per_request = ccswitch.total_new_input / ccswitch.total_requests + ccswitch.total_output / ccswitch.total_requests

        # 优化预测
        total_context = ccswitch.total_new_input + ccswitch.total_cache_read
        if total_context > 0:
            r.projected_savings_percent = ((target - ccswitch.hit_rate) / (100 - ccswitch.hit_rate)) * 100
            current_new_input_ratio = ccswitch.total_new_input / total_context
            target_new_input_ratio = 1 - target / 100
            new_new_input = total_context * target_new_input_ratio
            saved_tokens = ccswitch.total_new_input - new_new_input
            # 粗略估算：new input 和 output 占成本的大头
            # cache read 成本约为新输入的 1/10
            current_cost_breakdown = (
                ccswitch.total_new_input * 1.0 +  # new input 权重
                ccswitch.total_output * 1.0 +     # output 权重
                ccswitch.total_cache_read * 0.1    # cache 10% 价格
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
                # 月预估（按当天数据 * 30）
                r.projected_savings_monthly = (ccswitch.total_cost - r.projected_new_cost) * 30

    # 生成建议（配置发现的问题直接加入）
    for issue in config.issues:
        r.recommendations.append({
            "severity": issue.severity,
            "category": issue.category,
            "title": issue.title,
            "detail": issue.detail,
            "impact": issue.impact,
            "fix": issue.fix,
        })

    # 基于数据的建议
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

    # 综合评分
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
    score = max(0, min(100, score))
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


# ─── 报告输出 ─────────────────────────────────────────────

HEADER = """
╔══════════════════════════════════════════════════╗
║       命中缓存99% — 诊断报告          ║
╚══════════════════════════════════════════════════╝
"""


def format_report(r: AnalysisResult) -> str:
    lines = [HEADER, ""]

    # 1. 总览
    lines.append("━" * 50)
    lines.append("一、综合评分")
    lines.append("━" * 50)

    # 评分条
    score = r.overall_score
    bar_len = 30
    filled = int(score / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"  缓存健康度: {bar}  {score}/100")
    lines.append(f"  诊断: {r.diagnosis}")
    lines.append("")

    # 2. 命中率分析
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

    # 3. 配置诊断
    lines.append("━" * 50)
    lines.append("三、配置诊断")
    lines.append("━" * 50)
    cfg = r.config
    lines.append(f"  CLAUDE.md:      {cfg.claude_md_size} bytes, {cfg.claude_md_lines} 行{' ⚠️ 含动态内容' if cfg.claude_md_has_dynamic else ''}")
    lines.append(f"  记忆文件:       {cfg.memory_file_count} 个, 共 {cfg.memory_total_size} bytes")
    if cfg.memory_file_list:
        for name, size in sorted(cfg.memory_file_list, key=lambda x: -x[1])[:5]:
            lines.append(f"    - {name}: {size} bytes")
    lines.append(f"  已启技能:       {cfg.skill_count} 个")
    lines.append(f"  MCP 服务:       {cfg.mcp_count} 个")
    lines.append(f"  对话历史:       {cfg.history_size_mb:.1f} MB")
    lines.append("")

    # 4. 优化建议
    if r.recommendations:
        lines.append("━" * 50)
        lines.append("四、优化建议（按优先级排序）")
        lines.append("━" * 50)

        # 排序：critical > warning > info > success
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


# ─── JSON 输出（机器可读） ─────────────────────────────

def format_json(r: AnalysisResult) -> str:
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


# ─── Fix 引擎 ──────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 Markdown frontmatter，返回 (metadata, body)。"""
    if not text.startswith("---"):
        return {}, text
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
    """生成记忆文件合并计划。按 type 分组，小文件优先合并。"""
    mem_path = Path(memory_dir)
    if not mem_path.exists():
        return []

    files = []
    for f in sorted(mem_path.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        text = f.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        ftype = meta.get("type", "other")
        files.append({
            "name": f.name,
            "path": str(f),
            "type": ftype,
            "size": f.stat().st_size,
            "body": body,
        })

    # 分组
    groups = {}
    for f in files:
        g = groups.setdefault(f["type"], [])
        g.append(f)

    plan = []
    for ftype, members in groups.items():
        if len(members) <= 1 and members[0]["size"] < 2000:
            continue  # 单文件且不超 2KB，不动
        if len(members) <= 1:
            continue

        total_size = sum(m["size"] for m in members)
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
    """执行记忆文件合并修复。"""
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
            continue

        # 备份原文件 + 创建合并文件
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

        # 写合并文件
        target_path = mem_path / group["target"]
        target_path.write_text(merged_content, encoding="utf-8")

        # 删除原文件
        for fname in group["files"]:
            (mem_path / fname).unlink()

        reports.append(f"    ✅ 已合并 → {group['target']}")

    if dry_run:
        reports.append("\n\n使用 --fix apply 执行合并")
    else:
        reports.append("\n\n更新 MEMORY.md 索引中...")

    return reports


def backup_memory(memory_dir: str) -> str:
    """备份记忆目录到时间戳文件夹。"""
    mem_path = Path(memory_dir)
    backup_dir = mem_path.parent / f"memory_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for f in mem_path.glob("*.md"):
        fdata = f.read_bytes()
        (backup_dir / f.name).write_bytes(fdata)
    return str(backup_dir)


# ─── 仪表盘 HTML 生成 ──────────────────────────────────

def generate_dashboard(result: AnalysisResult) -> str:
    """生成独立 HTML 仪表盘。"""
    score = result.overall_score
    bar_filled = score // 5
    bar_empty = 20 - bar_filled
    bar = "█" * bar_filled + "░" * bar_empty

    hit = f"{result.current_hit_rate:.2f}%" if result.has_ccswitch_data else "N/A"
    cost_total = f"${result.total_cost:.4f}" if result.has_ccswitch_data else "N/A"
    savings = f"${result.projected_savings_monthly:.2f}/月" if result.has_ccswitch_data else "N/A"

    recs_html = ""
    sev_color = {"critical": "#dc3545", "warning": "#ffc107", "info": "#0d6efd", "success": "#198754"}
    for i, rec in enumerate(result.recommendations, 1):
        color = sev_color.get(rec["severity"], "#6c757d")
        recs_html += f"""
        <div class="rec" style="border-left: 4px solid {color};">
            <div class="rec-header">
                <span class="rec-num">#{i}</span>
                <span class="rec-sev" style="background:{color};">{rec['severity']}</span>
                <span class="rec-cat">{rec['category']}</span>
            </div>
            <div class="rec-title">{rec['title']}</div>
            <div class="rec-body">
                <p><strong>详情:</strong> {rec['detail']}</p>
                <p><strong>影响:</strong> {rec['impact']}</p>
                <p><strong>修复:</strong> {rec['fix']}</p>
            </div>
        </div>"""

    cfg = result.config
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>命中缓存99% — 诊断报告</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0d1117; color: #c9d1d9; padding: 20px; }}
.container {{ max-width: 900px; margin: 0 auto; }}
h1 {{ color: #58a6ff; margin-bottom: 24px; font-size: 24px; }}
h2 {{ color: #58a6ff; margin: 28px 0 16px; font-size: 18px;
       border-bottom: 1px solid #21262d; padding-bottom: 8px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.stat {{ text-align: center; padding: 12px; }}
.stat-value {{ font-size: 28px; font-weight: 700; color: #f0f6fc; }}
.stat-label {{ font-size: 13px; color: #8b949e; margin-top: 4px; }}
.score-bar {{ font-size: 18px; letter-spacing: 2px; margin: 8px 0; }}
.rec {{ background: #0d1117; border-radius: 6px; padding: 16px; margin-bottom: 12px; }}
.rec-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
.rec-num {{ color: #8b949e; font-weight: 600; }}
.rec-sev {{ color: #fff; font-size: 11px; padding: 2px 8px; border-radius: 10px; text-transform: uppercase; }}
.rec-cat {{ color: #8b949e; font-size: 12px; }}
.rec-title {{ font-weight: 600; margin-bottom: 8px; }}
.rec-body {{ font-size: 13px; color: #8b949e; line-height: 1.6; }}
.rec-body p {{ margin-bottom: 4px; }}
.config-table {{ width: 100%; font-size: 13px; border-collapse: collapse; }}
.config-table td {{ padding: 6px 12px; border-bottom: 1px solid #21262d; }}
.config-table td:first-child {{ color: #8b949e; width: 140px; }}
.highlight {{ color: #f0f6fc; font-weight: 600; }}
.green {{ color: #3fb950; }}
.yellow {{ color: #d29922; }}
.footer {{ text-align: center; color: #484f58; font-size: 12px; margin-top: 32px; }}
</style>
</head>
<body>
<div class="container">
<h1>🔍 命中缓存99% — 诊断报告</h1>

<div class="card">
    <h2>综合评分</h2>
    <div style="text-align:center;padding:16px;">
        <div style="font-size:48px;font-weight:700;">{score}/100</div>
        <div class="score-bar">{bar}</div>
        <div style="color:#8b949e;">{result.diagnosis}</div>
    </div>
</div>

<div class="card">
    <h2>命中率分析</h2>
    <div class="grid">
        <div class="stat"><div class="stat-value">{hit}</div><div class="stat-label">当前命中率</div></div>
        <div class="stat"><div class="stat-value">{cost_total}</div><div class="stat-label">总成本</div></div>
        <div class="stat"><div class="stat-value">{result.total_requests}</div><div class="stat-label">请求数</div></div>
        <div class="stat"><div class="stat-value">{(result.avg_input_per_request + result.avg_cache_per_request):.0f}</div><div class="stat-label">平均上下文/请求</div></div>
    </div>
</div>

<div class="card">
    <h2>节省预估</h2>
    <div class="grid">
        <div class="stat"><div class="stat-value green">{savings}</div><div class="stat-label">预估月省</div></div>
        <div class="stat"><div class="stat-value green">{result.projected_savings_percent:.1f}%</div><div class="stat-label">节省比例</div></div>
    </div>
</div>

<div class="card">
    <h2>配置状态</h2>
    <table class="config-table">
        <tr><td>CLAUDE.md</td><td>{cfg.claude_md_size} bytes {"⚠️ 含动态内容" if cfg.claude_md_has_dynamic else ""}</td></tr>
        <tr><td>记忆文件</td><td>{cfg.memory_file_count} 个, 共 {cfg.memory_total_size} bytes</td></tr>
        <tr><td>已启技能</td><td>{cfg.skill_count} 个</td></tr>
        <tr><td>MCP 服务</td><td>{cfg.mcp_count} 个</td></tr>
        <tr><td>对话历史</td><td>{cfg.history_size_mb:.1f} MB</td></tr>
    </table>
</div>

<div class="card">
    <h2>优化建议 ({len(result.recommendations)} 项)</h2>
    {recs_html}
</div>

<div class="footer">
    命中缓存99% · 报告生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>
</div>
</body>
</html>"""
    return html


# ─── CLI ─────────────────────────────────────────────────

def main():
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

    # ─── --detect 模式 ─────────────────────────────────────
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
                masked = val[:8] + "..." + val[-4:] if len(val) > 16 else val[:4] + "..."
                print(f"  ✅ {key}={masked}")
                found_any = True
        if not found_any:
            print("  ⚠️ 未检测到 API Key 环境变量")

        sys.exit(0)

    # ─── --setup 模式 ──────────────────────────────────────
    if args.setup:
        print("\n=== 命中缓存99% — 自动安装配置 ===\n")

        agent_list = agents.detect_all()
        if not agent_list:
            print("⚠️ 未检测到已安装的 AI agent")
            print("   请先安装 Claude Code / Codex / Hermes / OpenClaw 其中之一")
            sys.exit(1)

        configured = 0
        for agent in agent_list:
            print(f"配置 {agent.display}...")
            # 确保 CCSwitch 已安装
            ccs = ccsm.ensure_ccswitch(auto_install=True)
            if not ccs["installed"]:
                print(f"  ❌ CCSwitch 安装失败，跳过 {agent.display}")
                print(ccsm.__MANUAL_GUIDE__)
                continue
            # 配置 agent 代理
            ccsm.configure_for_agent(agent)
            print(f"  ✅ 已配置 CCSwitch 代理")
            configured += 1

        if configured > 0:
            print(f"\n✅ 配置完成！CCSwitch 正在后台收集数据...")
            print("   运行 --optimize 进行完整优化")
        else:
            print("\n⚠️ 未完成配置。可跳过 CCSwitch 直接使用：")
            print("   python -m cache_optimizer --data data.txt")
        sys.exit(0)

    # ─── --optimize 模式 ──────────────────────────────────
    if args.optimize:
        print("\n=== 命中缓存99% — 完整优化流程 ===\n")

        # 步骤1: 检测
        print("步骤1/4: 检测环境...")
        agent_list = agents.detect_all()
        if not agent_list:
            print("  ❌ 未检测到 AI agent，请先安装")
            sys.exit(1)
        for a in agent_list:
            print(f"  ✅ {a.display}")

        # 步骤2: 安装 CCSwitch
        print("步骤2/4: 确保 CCSwitch 已安装...")
        ccs = ccsm.ensure_ccswitch(auto_install=True)
        if ccs["installed"]:
            print(f"  ✅ CCSwitch v{ccs['version']}")
        else:
            print("  ❌ CCSwitch 安装失败")
            print("  ⚠️ 从 CCSwitch 仪表盘导出数据后用 --data 导入")
            print("  或者直接粘贴数据: python -m cache_optimizer")
            sys.exit(0)

        # 步骤3: 获取数据
        print("步骤3/4: 从 CCSwitch 获取使用数据...")
        data = ccsm.fetch_data()
        if data and data.get("raw"):
            print(f"  ✅ 获取到数据 ({len(data.get('requests', []))} 条请求)")
        else:
            print("  ⚠️ CCSwitch 暂无数据")
            print("  [1] 等待 CCSwitch 收集数据后重试")
            print("  [2] 或现在从 CCSwitch 仪表盘导出数据: python -m cache_optimizer --data data.txt")

        # 配置代理
        for agent in agent_list:
            ccsm.configure_for_agent(agent)
            print(f"  ✅ 已为 {agent.display} 配置 CCSwitch 代理")

        # 步骤4: 分析+修复
        print("步骤4/4: 扫描配置并优化...")
        config = scan_config(str(agent_list[0].config_dir))
        result = analyze(None, config, args.target)
        if result.overall_score >= 95:
            print(f"  ✅ 当前缓存健康度 {result.overall_score}/100，无需优化")
        else:
            print(f"  📋 建议 {len(result.recommendations)} 项优化")
            print(f"  运行 --fix dry-run 查看详情")
        print()
        print(format_report(result))

        print("━" * 50)
        print("优化流程完成！")
        print("后续: 定期运行 --optimize 持续监控")
        sys.exit(0)

    # ─── --fix 模式 ────────────────────────────────────────
    if args.fix:
        # 先备份
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

        # 先备份（非 dry-run）
        backup_path = None
        if args.fix == "apply":
            backup_path = backup_memory(memory_base)
            print(f"备份已创建: {backup_path}")

        # 执行修复
        reports = apply_fix(memory_base, dry_run=(args.fix == "dry-run"))
        for line in reports:
            print(line)

        # 非 dry-run 时更新 MEMORY.md
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

    # 1. 加载 CCSwitch 数据
    ccswitch = None
    if args.data:
        try:
            with open(args.data, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, FileNotFoundError, PermissionError) as e:
            print(f"错误: 无法读取数据文件: {e}")
            sys.exit(1)
    elif not sys.stdin.isatty():
        # 管道模式（非交互），直接读
        text = sys.stdin.buffer.read().decode("utf-8").strip()
    else:
        # 交互模式，提示用户粘贴
        print("[粘贴 CCSwitch 数据（Tab 分隔的请求日志），Ctrl+D/Ctrl+Z 结束]:")
        try:
            text = sys.stdin.buffer.read().decode("utf-8").strip()
        except (KeyboardInterrupt, EOFError):
            text = ""

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

    # 2. 扫描配置
    config = scan_config(args.config)

    # 3. 分析
    result = analyze(ccswitch, config, args.target)

    # 3b. 生成仪表盘（如果指定了 --dashboard）
    if args.dashboard:
        html = generate_dashboard(result)
        out_path = args.dashboard
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"✅ 仪表盘已生成: {os.path.abspath(out_path)}")
        webbrowser.open(os.path.abspath(out_path))
        sys.exit(0)

    # 4. 输出
    if args.json:
        print(format_json(result))
    else:
        print(format_report(result))

    # 5. 退出码
    if result.overall_score < 50:
        sys.exit(2)
    elif result.overall_score < 70:
        sys.exit(1)


if __name__ == "__main__":
    main()
