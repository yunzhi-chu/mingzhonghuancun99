"""Agent 检测 — 支持 Claude Code / Codex / Hermes / OpenClaw 等主流 agent。"""

import os
import re
import json
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class AgentInfo:
    name: str            # claude / codex / hermes / openclaw
    display: str         # "Claude Code"
    version: str         # 检测到的版本
    config_dir: Path     # 配置目录
    is_installed: bool   # 是否已安装
    env_keys: list = field(default_factory=list)  # 关联的环境变量
    details: dict = field(default_factory=dict)   # 额外信息


def detect_all() -> list[AgentInfo]:
    """检测所有已安装的 AI agent。"""
    agents = []
    for detector in [_detect_claude, _detect_codex, _detect_hermes, _detect_openclaw, _detect_generic]:
        try:
            info = detector()
            if info:
                agents.append(info)
        except Exception:
            pass
    return agents


def _detect_claude() -> AgentInfo | None:
    """检测 Claude Code。"""
    config_dir = Path.home() / ".claude"
    if not config_dir.exists():
        return None

    version = "未知"
    # 从 settings.json 或 mcp.json 推断版本
    sf = config_dir / "settings.json"
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            model = data.get("env", {}).get("ANTHROPIC_MODEL", "")
            if model:
                # 如果是 DeepSeek，说明通过第三方网关
                version = f"模型: {model}"
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
            "settings": sf.exists(),
            "claude_md": (config_dir / "CLAUDE.md").exists(),
            "memory_dir": str(next(config_dir.glob("projects/*/memory"), "")),
            "skills": len(list(config_dir.glob("skills/*"))) if (config_dir / "skills").exists() else 0,
        },
    )


def _detect_codex() -> AgentInfo | None:
    """检测 OpenAI Codex CLI。"""
    # 检查常见的 Codex 配置路径
    candidates = [
        Path.home() / ".codex",
        Path.home() / ".config" / "codex",
    ]
    for cfg_dir in candidates:
        if cfg_dir.exists():
            version = "未知"
            try:
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
    """检测 Hermes-Claw。"""
    # 检查是否有 Hermes 相关的配置或环境
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

    # 检查 Python 包
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
    """检测 OpenClaw。"""
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
    """检测通用 API key（有 API key 但无特定 agent 配置）。"""
    api_keys = {
        "ANTHROPIC_API_KEY": "Anthropic API",
        "OPENAI_API_KEY": "OpenAI API",
        "DEEPSEEK_API_KEY": "DeepSeek API",
    }
    found = []
    for key, name in api_keys.items():
        if os.environ.get(key):
            found.append(name)

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
    """检测 CCSwitch 是否已安装。"""
    result = {"installed": False, "version": "", "path": "", "config": {}}

    # 1. 检查命令行
    cc_cmd = shutil.which("ccswitch") or shutil.which("ccswitch-cli")
    if cc_cmd:
        result["installed"] = True
        result["path"] = cc_cmd
        try:
            out = subprocess.run([cc_cmd, "--version"], capture_output=True, text=True, timeout=5)
            result["version"] = out.stdout.strip() or out.stderr.strip()
        except Exception:
            result["version"] = "<= 1.0"
        return result

    # 2. 检查 Python 包
    try:
        import importlib.metadata
        version = importlib.metadata.version("ccswitch")
        result["installed"] = True
        result["version"] = f"Python {version}"
        result["path"] = "pip: ccswitch"
        return result
    except (ImportError, ModuleNotFoundError):
        pass

    # 3. 检查常见安装路径
    for p in [
        Path.home() / ".ccswitch",
        Path.home() / "ccswitch",
        Path("/opt/ccswitch"),
    ]:
        if p.exists() and (p / "config.json").exists():
            result["installed"] = True
            result["path"] = str(p)
            try:
                result["config"] = json.loads((p / "config.json").read_text(encoding="utf-8"))
            except Exception:
                pass
            return result

    return result


def print_agents(agents: list[AgentInfo]):
    """打印检测到的 agent 信息。"""
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
    """打印 CCSwitch 检测结果。"""
    if ccs["installed"]:
        print(f"  ✅ CCSwitch v{ccs['version']}")
        print(f"     路径: {ccs['path']}")
        if ccs.get("config"):
            print(f"     配置: {json.dumps(ccs['config'], ensure_ascii=False)}")
    else:
        print("  ❌ CCSwitch 未安装")
        print("     使用 --setup 自动安装")
