"""CC-Switch 管理 — 检测、读取代理配置、从 SQLite 获取使用数据。

CC-Switch 是什么？
  一个桌面应用（Electron），放在你和 AI API 之间做\"中间人\"。
  所有你发给 AI 的请求都会经过它的本地代理（127.0.0.1:15721），
  它会记录到 SQLite 数据库：
  - 时间、供应商、模型
  - 输入/输出/缓存读取 token
  - 成本

本模块不再尝试安装 CC-Switch（它是桌面应用，不是 pip 包），
而是直接读取它的 SQLite 数据库。
"""

import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from .agents import AgentInfo, detect_ccswitch

# CC-Switch 数据目录
CC_SWITCH_DIR = Path.home() / ".cc-switch"
CC_DB = CC_SWITCH_DIR / "cc-switch.db"


def ensure_ccswitch(auto_install: bool = True) -> dict:
    """检测 CC-Switch 是否已安装。

    CC-Switch 是桌面应用，无法自动安装。
    如果没装，给出引导提示。

    参数：
      auto_install: 保留参数，仅用于兼容。实际什么也不装。

    返回值：
      detect_ccswitch() 的结果字典
    """
    ccs = detect_ccswitch()
    if ccs["installed"]:
        return ccs

    if not auto_install:
        return ccs

    print("  ⚠️ CC-Switch 未检测到。请确认桌面端已启动。")
    print("     CC-Switch 是一个桌面应用（系统托盘图标），不是 pip 包。")
    print("     如果已安装，检查 ~/.cc-switch/ 目录是否存在。")
    return ccs


# 当 CC-Switch 装不上时，告诉用户手动操作的方法
__MANUAL_GUIDE__ = """
CC-Switch 未检测到或数据库不可用。你仍可手动使用本工具：

  1. 从 CC-Switch 仪表盘复制请求日志（Tab 分隔格式）
  2. 运行: python -m cache_optimizer
  3. 粘贴数据，Ctrl+D 结束

或者保存到文件后: python -m cache_optimizer --data data.txt
"""


def _time_to_ts(t: datetime) -> str:
    """把 datetime 转成 CC-Switch 日志里的时间戳格式。

    例如: 2026-06-06 18:00:00
    """
    return t.strftime("%Y-%m-%d %H:%M:%S")


def fetch_data(period: str = "today") -> Optional[dict]:
    """从 CC-Switch SQLite 数据库获取使用数据。

    直接查 proxy_request_logs 表，把数据格式化成 Tab 分隔文本，
    与 CCSwitchData.parse() 兼容。

    参数：
      period: 时间范围 — 'today'（今天）, '7d'（近7天）, '30d'（近30天）, 'all'

    返回值：
      dict 包含：
        raw:      Tab 分隔的文本（可直接喂给 CCSwitchData.parse()）
        requests: 结构化请求列表
        summary:  摘要统计
        如果数据库不存在或没有数据，返回 None
    """
    ccs = detect_ccswitch()
    if not ccs["installed"] or not ccs.get("db_path"):
        return None

    db = ccs["db_path"]
    if not os.path.exists(db):
        return None

    # 计算时间范围
    now = datetime.now(timezone.utc)
    if period == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7d":
        cutoff = now - timedelta(days=7)
    elif period == "30d":
        cutoff = now - timedelta(days=30)
    else:
        cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)

    cutoff_ts = int(cutoff.timestamp())  # SQLite 存的 created_at 是秒级时间戳

    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 查数据
        cur.execute("""
            SELECT created_at, app_type, model, input_tokens, output_tokens,
                   cache_read_tokens, total_cost_usd, status_code, data_source
            FROM proxy_request_logs
            WHERE created_at >= ?
            ORDER BY created_at ASC
        """, (cutoff_ts,))
        rows = cur.fetchall()

        if not rows:
            conn.close()
            return {
                "raw": None,
                "requests": [],
                "summary": {"total_requests": 0},
            }

        # 格式化成 Tab 分隔文本
        # 格式: time \t provider \t model \t new_input \t R_cache \t output \t cost \t ttf \t status \t source
        lines = [("时间\t供应商\t模型\t新增输入\tR缓存读取\t输出\t费用\t首token延迟\t状态\t来源")]
        requests_structured = []

        for row in rows:
            created_at_ms = row["created_at"]
            created_at_dt = datetime.fromtimestamp(created_at_ms, tz=timezone.utc)
            time_str = created_at_dt.strftime("%Y-%m-%d %H:%M:%S")

            provider = row["app_type"]  # claude / codex / gemini
            model = row["model"] or "unknown"
            new_input = row["input_tokens"] or 0
            cache_read = row["cache_read_tokens"] or 0
            output_tokens = row["output_tokens"] or 0
            cost_str = row["total_cost_usd"] or "0"
            try:
                cost = float(cost_str)
            except (ValueError, TypeError):
                cost = 0.0
            status = "success" if row["status_code"] == 200 else f"error_{row['status_code']}"
            source = row["data_source"] or "proxy"

            # Tab 分隔一行
            line = f"{time_str}\t{provider}\t{model}\t{new_input}\tR{cache_read}\t{output_tokens}\t${cost:.6f}\t0\t{status}\t{source}"
            lines.append(line)

            requests_structured.append({
                "time": time_str,
                "provider": provider,
                "model": model,
                "new_input": new_input,
                "cache_read": cache_read,
                "output": output_tokens,
                "cost": cost,
                "status": status,
                "source": source,
            })

        # 统计汇总
        total_new = sum(r["input_tokens"] or 0 for r in rows)
        total_cache = sum(r["cache_read_tokens"] or 0 for r in rows)
        total_output = sum(r["output_tokens"] or 0 for r in rows)
        total_cost = sum(float(r["total_cost_usd"] or 0) for r in rows)
        total_context = total_new + total_cache
        hit_rate = (total_cache / total_context * 100) if total_context > 0 else 0

        summary = {
            "total_requests": len(rows),
            "total_new_input": total_new,
            "total_cache_read": total_cache,
            "total_output": total_output,
            "total_cost": round(total_cost, 4),
            "hit_rate": round(hit_rate, 2),
        }

        conn.close()

        return {
            "raw": "\n".join(lines),
            "requests": requests_structured,
            "summary": summary,
        }

    except sqlite3.Error:
        return None


def configure_for_agent(agent: AgentInfo) -> dict:
    """读取 CC-Switch 为指定 agent 配置的代理信息。

    CC-Switch 桌面端已经配好了代理。本函数只读，不改。
    从 proxy_config 表读取代理设置，从 providers 表读取当前供应商。

    参数：
      agent: 之前检测到的 agent 信息（AgentInfo 对象）

    返回值：
      配置字典，包含 agent 信息和代理设置
    """
    config = {
        "agent": agent.name,
        "agent_display": agent.display,
        "config_dir": str(agent.config_dir),
        "proxy": None,
        "provider": None,
    }

    ccs = detect_ccswitch()
    if not ccs["installed"] or not ccs.get("db_path"):
        return config

    app_type = agent.name  # claude / codex / gemini

    try:
        conn = sqlite3.connect(ccs["db_path"])
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 获取代理配置
        cur.execute("""
            SELECT listen_address, listen_port, enabled, proxy_enabled
            FROM proxy_config WHERE app_type = ?
        """, (app_type,))
        proxy_row = cur.fetchone()
        if proxy_row:
            config["proxy"] = {
                "listen_address": proxy_row["listen_address"],
                "listen_port": proxy_row["listen_port"],
                "enabled": bool(proxy_row["enabled"]),
                "proxy_enabled": bool(proxy_row["proxy_enabled"]),
            }

        # 获取当前提供商
        cur.execute("""
            SELECT p.name, p.settings_config, p.website_url, p.category,
                   pe.url as endpoint
            FROM providers p
            LEFT JOIN provider_endpoints pe ON pe.provider_id = p.id AND pe.app_type = p.app_type
            WHERE p.app_type = ? AND p.is_current = 1
            LIMIT 1
        """, (app_type,))
        prov_row = cur.fetchone()
        if prov_row:
            config["provider"] = {
                "name": prov_row["name"],
                "endpoint": prov_row["endpoint"] or "",
                "category": prov_row["category"] or "",
            }

        conn.close()
    except sqlite3.Error:
        pass

    return config


def print_setup_result(agent: Optional[AgentInfo], ccs: dict, config: Optional[dict]):
    """打印检测和配置的结果到屏幕上。"""
    print()
    print("━" * 50)
    print("CC-Switch 状态")
    print("━" * 50)
    if agent:
        status = "✅" if agent.is_installed else "❌"
        print(f"  Agent: {status} {agent.display}")
    ccs_status = "✅" if ccs.get("installed") else "❌"
    print(f"  CC-Switch: {ccs_status}")
    if ccs.get("installed"):
        if ccs.get("db_path"):
            db_size = os.path.getsize(ccs["db_path"]) / (1024 * 1024)
            print(f"  数据库: {ccs['db_path']} ({db_size:.0f} MB)")
        if ccs.get("proxy_port"):
            print(f"  代理端口: 127.0.0.1:{ccs['proxy_port']}")
        if ccs.get("agents"):
            print(f"  已启用代理: {', '.join(ccs['agents'])}")
    if config:
        proxy = config.get("proxy") or {}
        if proxy.get("enabled"):
            print(f"  代理状态: ✅ 已启用")
            print(f"  代理地址: {proxy.get('listen_address', '127.0.0.1')}:{proxy.get('listen_port', 'N/A')}")
        if config.get("provider"):
            pr = config["provider"]
            print(f"  当前供应商: {pr.get('name', 'N/A')}")
            if pr.get("endpoint"):
                print(f"  代理终点: {pr['endpoint']}")
    print()
