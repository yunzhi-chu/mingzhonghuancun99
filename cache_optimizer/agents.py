"""Agent 检测 — 自动发现你电脑上装了哪些 AI 编程助手。

什么是 agent？
  AI agent（代理）就是 AI 编程助手，比如 Claude Code、Codex CLI 等。
  它们会在你的电脑上创建配置文件，本模块就是去读取这些文件来判断你装了哪些。

为什么需要检测 agent？
  不同的 agent 使用不同的缓存策略。知道了你用哪个，我们才能给针对性的优化建议。
"""

import os
import re
import json
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field

# CC-Switch 下载链接（桌面应用，非 pip 包）
CCSWITCH_RELEASES = "https://github.com/farion1231/cc-switch/releases/latest"


@dataclass
class AgentInfo:
    """Agent 信息的数据结构（相当于一个"盒子"，装着某个 agent 的所有信息）。

    属性说明：
      name:        agent 的英文代号，如 "claude" / "codex"
      display:     显示给人看的名字，如 "Claude Code"
      version:     检测到的版本号
      config_dir:  配置文件夹的路径（比如 ~/.claude）
      is_installed: 是否已安装（True/False）
      env_keys:    这个 agent 用到的环境变量列表（如 ANTHROPIC_API_KEY）
      details:     其他额外信息，按需存
    """
    name: str
    display: str
    version: str
    config_dir: Path
    is_installed: bool
    env_keys: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


def detect_all() -> list[AgentInfo]:
    """检测电脑上所有已安装的 AI agent。

    依次检查 5 种情况：
      1. Claude Code
      2. Codex CLI
      3. Hermes-Claw
      4. OpenClaw
      5. 通用 API Key（没装具体 agent 但有 API key）

    返回值是一个列表，每个元素是一个 AgentInfo 对象。
    """
    agents = []
    # 逐个运行检测函数，把能检测到的都加进来
    for detector in [_detect_claude, _detect_codex, _detect_hermes, _detect_openclaw, _detect_generic]:
        try:
            info = detector()
            if info:
                agents.append(info)
        except Exception:
            pass  # 某个检测失败了不要紧，继续检测下一个
    return agents


def _detect_claude() -> AgentInfo | None:
    """检测 Claude Code 是否已安装。

    判断方法：看 ~/.claude/ 文件夹是否存在。
    如果存在，再进一步读取它的配置文件 settings.json，看看有没有设置模型。
    """
    config_dir = Path.home() / ".claude"
    if not config_dir.exists():
        return None  # 没有这个文件夹 = 没装 Claude Code

    version = "未知"
    # 尝试从 settings.json 里读取模型信息
    sf = config_dir / "settings.json"
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            model = data.get("env", {}).get("ANTHROPIC_MODEL", "")
            if model:
                version = f"模型: {model}"  # 比如 "模型: claude-sonnet-4-6"
        except Exception:
            pass

    return AgentInfo(
        name="claude",
        display="Claude Code",
        version=version,
        config_dir=config_dir,
        is_installed=True,
        env_keys=["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"],
        details={
            "settings": sf.exists(),                                        # 有没有 settings.json
            "claude_md": (config_dir / "CLAUDE.md").exists(),               # 有没有 CLAUDE.md
            "memory_dir": str(next(config_dir.glob("projects/*/memory"), "")),  # 记忆文件目录
            "skills": len(list(config_dir.glob("skills/*"))) if (config_dir / "skills").exists() else 0,  # 技能数量
        },
    )


def _detect_codex() -> AgentInfo | None:
    """检测 OpenAI Codex CLI 是否已安装。

    判断方法：
      1. 检查 ~/.codex/ 或 ~/.config/codex/ 文件夹是否存在
      2. 如果能运行 codex --version 命令，获取版本号
    """
    candidates = [
        Path.home() / ".codex",
        Path.home() / ".config" / "codex",
    ]
    for cfg_dir in candidates:
        if cfg_dir.exists():
            version = "未知"
            try:
                # 运行 codex --version 看看能不能拿到版本号
                result = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    version = result.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

            return AgentInfo(
                name="codex",
                display="Codex CLI",
                version=version,
                config_dir=cfg_dir,
                is_installed=True,
                env_keys=["OPENAI_API_KEY", "CODEX_API_KEY"],
            )

    return None


def _detect_hermes() -> AgentInfo | None:
    """检测 Hermes-Claw 是否已安装。

    判断方法：
      1. 检查 ~/.hermes/ 等常见目录是否存在
      2. 或者检查 Python 是否安装了 hermes_claw 包
    """
    hermes_dirs = [
        Path.home() / ".hermes",
        Path.home() / "hermes-claw",
        Path.cwd() / "hermes-claw",
    ]

    for hd in hermes_dirs:
        if hd.exists():
            return AgentInfo(
                name="hermes",
                display="Hermes-Claw",
                version="未知",
                config_dir=hd,
                is_installed=True,
                env_keys=["HERMES_API_KEY", "OLLAMA_HOST"],
                details={"vision_agent": (hd / "vision_agent").exists()},
            )

    # 检查 Python 包：能不能 import hermes_claw
    try:
        import importlib
        if importlib.util.find_spec("hermes_claw"):
            return AgentInfo(
                name="hermes",
                display="Hermes-Claw",
                version="Python 包",
                config_dir=Path.home() / ".hermes",
                is_installed=True,
                env_keys=["HERMES_API_KEY", "OLLAMA_HOST"],
            )
    except ImportError:
        pass

    return None


def _detect_openclaw() -> AgentInfo | None:
    """检测 OpenClaw 是否已安装。

    判断方法：
      1. 检查 ~/.openclaw/ 等常见目录是否存在
      2. 或者检查环境变量 OPENCLAW_HOME 是否设置
    """
    openclaw_dirs = [
        Path.home() / ".openclaw",
        Path.home() / "OpenClaw",
    ]
    for od in openclaw_dirs:
        if od.exists():
            return AgentInfo(
                name="openclaw",
                display="OpenClaw",
                version="未知",
                config_dir=od,
                is_installed=True,
                env_keys=["OPENCLAW_API_KEY"],
            )

    # 检查环境变量
    if os.environ.get("OPENCLAW_HOME"):
        return AgentInfo(
            name="openclaw",
            display="OpenClaw",
            version="环境变量",
            config_dir=Path(os.environ["OPENCLAW_HOME"]),
            is_installed=True,
            env_keys=["OPENCLAW_API_KEY", "OPENCLAW_HOME"],
        )

    return None


def _detect_generic() -> AgentInfo | None:
    """检测通用 API Key（没装具体 agent，但有 API key 环境变量）。

    比如用户没有装 Claude Code，但设置了 ANTHROPIC_API_KEY，
    说明他可能在用 API 直接调用，我们也能给他一些通用建议。
    """
    api_keys = {
        "ANTHROPIC_API_KEY": "Anthropic API",
        "OPENAI_API_KEY": "OpenAI API",
        "DEEPSEEK_API_KEY": "DeepSeek API",
    }
    found = []
    for key, name in api_keys.items():
        if os.environ.get(key):
            found.append(name)

    # 只有真的没检测到 Claude/Codex 时才报通用，避免重复
    if found and not _detect_claude() and not _detect_codex():
        return AgentInfo(
            name="generic",
            display=" + ".join(found),
            version="API Key 模式",
            config_dir=Path.home(),
            is_installed=True,
            env_keys=list(api_keys.keys()),
        )

    return None


def detect_ccswitch() -> dict:
    """检测 CC-Switch（CCSwitch）是否已安装。

    CC-Switch 是一个桌面应用（Electron），通过系统托盘运行。
    它在本机开了正向代理（127.0.0.1:15721），记录所有 AI API 请求到 SQLite。

    检测方法：
      1. SQLite 数据库 ~/.cc-switch/cc-switch.db 是否存在
      2. 设置文件 ~/.cc-switch/settings.json 是否存在
      3. 代理端口 15721 是否可达
    """
    result = {"installed": False, "version": "", "path": "", "config": {},
              "db_path": "", "proxy_port": 0, "agents": []}

    cc_switch_dir = Path.home() / ".cc-switch"
    if not cc_switch_dir.exists():
        return result

    # 检查 SQLite 数据库
    db_path = cc_switch_dir / "cc-switch.db"
    if db_path.exists():
        result["installed"] = True
        result["path"] = str(cc_switch_dir)
        result["db_path"] = str(db_path)

    # 读取 settings.json 获取代理信息和版本
    sf = cc_switch_dir / "settings.json"
    if sf.exists():
        try:
            settings = json.loads(sf.read_text(encoding="utf-8"))
            # 只提取安全字段，不保留原始 settings 全文（防敏感信息泄漏）
            if settings.get("enableLocalProxy"):
                result["proxy_port"] = 15721
            result["version"] = settings.get("version", "桌面版")
        except Exception:
            pass

    # 从 SQLite 读取代理配置和已启用的 agent
    if result["installed"]:
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            # 获取代理配置
            try:
                cur.execute("SELECT app_type, listen_port, enabled FROM proxy_config")
                for row in cur.fetchall():
                    if row[2]:  # enabled
                        result["agents"].append(row[0])
                        result["proxy_port"] = row[1]
            except Exception:
                pass
            conn.close()
        except Exception:
            pass

    return result


def print_agents(agents: list[AgentInfo]):
    """把检测到的 agent 信息打印到屏幕上。

    格式举例：
      ✅ Claude Code v模型: claude-sonnet-4-6
         配置目录: C:\\Users\\xxx\\.claude
         settings: True
    """
    if not agents:
        print("  ❌ 未检测到已安装的 AI agent")
        return
    for a in agents:
        status = "✅" if a.is_installed else "❌"
        env_str = f" ({', '.join(a.env_keys[:2])}...)" if a.env_keys else ""
        print(f"  {status} {a.display} v{a.version}{env_str}")
        print(f"     配置目录: {a.config_dir}")
        if a.details:
            for k, v in a.details.items():
                if v:
                    print(f"     {k}: {v}")


def print_ccswitch(ccs: dict):
    """打印 CC-Switch 的检测结果。"""
    if ccs["installed"]:
        print(f"  ✅ CC-Switch {ccs['version']}")
        print(f"     数据目录: {ccs['path']}")
        print(f"     数据库: {ccs.get('db_path', 'N/A')}")
        print(f"     代理端口: {ccs.get('proxy_port', 'N/A')}")
        if ccs.get("agents"):
            print(f"     已启用代理: {', '.join(ccs['agents'])}")
    else:
        print(f"  ❌ CC-Switch 未安装")
        print(f"     下载: {CCSWITCH_RELEASES}")
