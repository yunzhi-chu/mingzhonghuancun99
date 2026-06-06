"""CCSwitch 管理 — 检测、安装、数据获取。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .agents import AgentInfo, detect_ccswitch


CCSWITCH_PIP = "ccswitch"
CCSWITCH_GIT = "https://github.com/your-org/ccswitch.git"  # TODO: 发布后替换为真实 CCSwitch 仓库地址


def ensure_ccswitch(auto_install: bool = True) -> dict:
    """确保 CCSwitch 已安装，未安装则自动安装。"""
    ccs = detect_ccswitch()
    if ccs["installed"]:
        return ccs

    if not auto_install:
        return ccs

    print("🚀 正在自动安装 CCSwitch...")
    return install_ccswitch()


def install_ccswitch() -> dict:
    """安装 CCSwitch。"""
    methods = [
        _install_pip,
        _install_git,
    ]

    for method in methods:
        try:
            result = method()
            if result["installed"]:
                print(f"  ✅ CCSwitch 安装成功: v{result['version']}")
                return result
        except Exception as e:
            print(f"  ⚠️ 安装方式失败: {e}")

    return {"installed": False, "version": "", "path": "", "error": "所有安装方式均失败"}


__MANUAL_GUIDE__ = """
CCSwitch 未安装或安装失败。你仍可手动使用本工具：

  1. 从 CCSwitch 仪表盘复制请求日志（Tab 分隔格式）
  2. 运行: python -m cache_optimizer
  3. 粘贴数据，Ctrl+D 结束

或者保存到文件后: python -m cache_optimizer --data data.txt
"""


def _install_pip() -> dict:
    """通过 pip 安装 CCSwitch。"""
    print("  方法1: pip install...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", CCSWITCH_PIP],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip 安装失败: {result.stderr[:200]}")

    # 验证
    return detect_ccswitch()


def _install_git() -> dict:
    """通过 git clone 安装。"""
    import shutil
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git 未安装")

    target = Path.home() / ".ccswitch"
    target.mkdir(parents=True, exist_ok=True)

    print(f"  方法2: git clone {CCSWITCH_GIT}")
    result = subprocess.run(
        [git, "clone", CCSWITCH_GIT, str(target / "repo")],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone 失败: {result.stderr[:200]}")

    # 尝试 pip install 本地
    subprocess.run(
        [sys.executable, "-m", "pip", "install", str(target / "repo")],
        capture_output=True, text=True, timeout=120,
    )

    return detect_ccswitch()


def configure_for_agent(agent: AgentInfo) -> dict:
    """为指定 agent 配置 CCSwitch。"""
    config = {
        "agent": agent.name,
        "agent_display": agent.display,
        "config_dir": str(agent.config_dir),
        "proxy": None,
    }

    if agent.name == "claude":
        config["proxy"] = {
            "type": "env",
            "variables": {
                "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            },
        }
        # 检查是否已配置代理
        sf = agent.config_dir / "settings.json"
        if sf.exists():
            try:
                data = json.loads(sf.read_text(encoding="utf-8"))
                env = data.get("env", {})
                if "ANTHROPIC_BASE_URL" in env:
                    config["proxy"]["current"] = env["ANTHROPIC_BASE_URL"]
            except Exception:
                pass

    elif agent.name == "codex":
        config["proxy"] = {
            "type": "env",
            "variables": {"OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")},
        }

    # 保存 CCSwitch agent 配置
    ccs_config_dir = Path.home() / ".ccswitch"
    ccs_config_dir.mkdir(parents=True, exist_ok=True)
    config_file = ccs_config_dir / "agents.json"

    existing = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing[agent.name] = config
    config_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    return config


def fetch_data() -> Optional[dict]:
    """从 CCSwitch 获取使用数据。"""
    ccs = detect_ccswitch()
    if not ccs["installed"]:
        return None

    data = {
        "requests": [],
        "summary": {},
        "raw": None,
    }

    # 方法1: ccswitch 命令行导出
    cc_cmd = None
    for cmd_name in ["ccswitch", "ccswitch-cli"]:
        found = shutil_which(cmd_name)
        if found:
            cc_cmd = found
            break

    if cc_cmd:
        try:
            # 导出今日数据
            result = subprocess.run(
                [cc_cmd, "export", "--format", "json", "--period", "today"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                data["raw"] = result.stdout
                parsed = json.loads(result.stdout)
                if isinstance(parsed, dict):
                    data["summary"] = parsed.get("summary", parsed)
                    data["requests"] = parsed.get("requests", [])
                return data
        except Exception:
            pass

    # 方法2: 读取本地缓存
    cache_files = [
        Path.home() / ".ccswitch" / "cache" / "today.json",
        Path.home() / ".ccswitch" / "data" / "requests.jsonl",
    ]
    for cf in cache_files:
        if cf.exists():
            try:
                data["raw"] = cf.read_text(encoding="utf-8")
                data["source"] = str(cf)
                if cf.suffix == ".json":
                    parsed = json.loads(data["raw"])
                    data["summary"] = parsed if isinstance(parsed, dict) else {}
                return data
            except Exception:
                pass

    # 方法3: 通过 API 获取
    api_url = "http://localhost:8008"  # CCSwitch 默认地址
    try:
        import urllib.request
        from urllib.parse import urlparse

        # 只允许 localhost 重定向，防 SSRF
        class _LocalOnlyRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                parsed = urlparse(newurl)
                if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                    return None
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        opener = urllib.request.build_opener(_LocalOnlyRedirect)
        resp = opener.open(f"{api_url}/api/usage/today", timeout=10)
        if resp.status == 200:
            data["raw"] = resp.read().decode("utf-8")
            parsed = json.loads(data["raw"])
            data["summary"] = parsed if isinstance(parsed, dict) else {}
            return data
    except Exception:
        pass

    return data


def shutil_which(cmd: str) -> Optional[str]:
    """跨平台 which。"""
    import shutil
    return shutil.which(cmd)


def print_setup_result(agent: Optional[AgentInfo], ccs: dict, config: Optional[dict]):
    """打印安装配置结果。"""
    print()
    print("━" * 50)
    print("安装与配置结果")
    print("━" * 50)
    if agent:
        status = "✅" if agent.is_installed else "❌"
        print(f"  Agent: {status} {agent.display}")
    ccs_status = "✅" if ccs.get("installed") else "❌"
    print(f"  CCSwitch: {ccs_status} v{ccs.get('version', 'N/A')}")
    if config:
        print(f"  代理配置: ✅ 已为 {config['agent_display']} 配置")
        if config.get("proxy", {}).get("current"):
            print(f"  当前代理: {config['proxy']['current']}")
    print()
