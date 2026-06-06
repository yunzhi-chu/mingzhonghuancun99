"""CCSwitch 管理 — 自动安装、配置、获取数据。

CCSwitch 是什么？
  它是一个"中间人"代理工具，放在你和 AI API 之间。
  所有你发给 AI 的请求都会经过它，它会记录下来：
  - 什么时候发的
  - 用了什么模型
  - 发了多少字（tokens）
  - 其中多少命中了缓存
  - 花了多少钱

本模块负责：
  1. 检测 CCSwitch 有没有装
  2. 没装就自动装
  3. 配置让 AI agent 走 CCSwitch 代理
  4. 从 CCSwitch 拉取使用数据
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .agents import AgentInfo, detect_ccswitch


# CCSwitch 的 pip 包名
CCSWITCH_PIP = "ccswitch"
# 如果 pip 装不上，就从 GitHub 克隆（TODO: 发布后替换为真实仓库地址）
CCSWITCH_GIT = "https://github.com/your-org/ccswitch.git"


def ensure_ccswitch(auto_install: bool = True) -> dict:
    """确保 CCSwitch 已安装。没装的话自动安装。

    参数：
      auto_install: 如果没装，是否自动安装（默认是 True）

    返回值：
      detect_ccswitch() 的结果字典，包含 installed/version/path 等
    """
    ccs = detect_ccswitch()
    if ccs["installed"]:
        return ccs  # 已经装好了，直接返回

    if not auto_install:
        return ccs  # 用户不让自动装，那就返回未安装状态

    print("🚀 正在自动安装 CCSwitch...")
    return install_ccswitch()


def install_ccswitch() -> dict:
    """安装 CCSwitch。

    尝试两种方法，哪个成功了就用哪个：
      方法1: pip install（最快，推荐）
      方法2: git clone 然后 pip install（备选）

    返回值：
      detect_ccswitch() 的结果字典
    """
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


# 当 CCSwitch 装不上时，告诉用户手动操作的方法
__MANUAL_GUIDE__ = """
CCSwitch 未安装或安装失败。你仍可手动使用本工具：

  1. 从 CCSwitch 仪表盘复制请求日志（Tab 分隔格式）
  2. 运行: python -m cache_optimizer
  3. 粘贴数据，Ctrl+D 结束

或者保存到文件后: python -m cache_optimizer --data data.txt
"""


def _install_pip() -> dict:
    """方法1：通过 pip 安装 CCSwitch。

    pip 是 Python 的包管理器，就像手机上的应用商店。
    这一行命令相当于在应用商店搜索安装 CCSwitch：
      pip install ccswitch
    """
    print("  方法1: pip install...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", CCSWITCH_PIP],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip 安装失败: {result.stderr[:200]}")

    # 装完了再检测一次，确认装上了
    return detect_ccswitch()


def _install_git() -> dict:
    """方法2：通过 git clone 安装。

    如果 pip 装不上（比如网络问题），就用 git 把代码下载到本地再装。
    相当于从 GitHub 上下载源码然后手动安装。
    """
    import shutil
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git 未安装")  # 没装 git，这条路走不通

    target = Path.home() / ".ccswitch"
    target.mkdir(parents=True, exist_ok=True)

    print(f"  方法2: git clone {CCSWITCH_GIT}")
    result = subprocess.run(
        [git, "clone", CCSWITCH_GIT, str(target / "repo")],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone 失败: {result.stderr[:200]}")

    # 克隆下来后，再用 pip 安装本地代码
    subprocess.run(
        [sys.executable, "-m", "pip", "install", str(target / "repo")],
        capture_output=True, text=True, timeout=120,
    )

    return detect_ccswitch()


def configure_for_agent(agent: AgentInfo) -> dict:
    """为指定的 AI agent 配置 CCSwitch 代理。

    简单说：告诉 agent "你的请求先经过 CCSwitch 再发给 AI 厂商"。
    这样 CCSwitch 才能记录到所有请求数据。

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
    }

    # 不同 agent 有不同的代理配置方式
    if agent.name == "claude":
        # Claude Code 通过环境变量 ANTHROPIC_BASE_URL 设置代理
        config["proxy"] = {
            "type": "env",
            "variables": {
                "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            },
        }
        # 检查 Claude 的 settings.json 里是否已经配了代理
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
        # Codex CLI 通过环境变量 OPENAI_BASE_URL 设置代理
        config["proxy"] = {
            "type": "env",
            "variables": {"OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")},
        }

    # 把配置保存到 ~/.ccswitch/agents.json 文件里
    ccs_config_dir = Path.home() / ".ccswitch"
    ccs_config_dir.mkdir(parents=True, exist_ok=True)
    config_file = ccs_config_dir / "agents.json"

    # 先读取已有的配置（如果有的话）
    existing = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 新配置覆盖旧配置，然后写回文件
    existing[agent.name] = config
    config_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    return config


def fetch_data() -> Optional[dict]:
    """从 CCSwitch 获取使用数据。

    三种获取方式，按优先级尝试：
      方法1: 运行 ccswitch export 命令行导出
      方法2: 读取本地缓存文件
      方法3: 访问 CCSwitch 的本地 HTTP API

    返回值：
      dict 包含 requests（请求列表）、summary（摘要）、raw（原始数据）
      如果 CCSwitch 没装，返回 None
    """
    ccs = detect_ccswitch()
    if not ccs["installed"]:
        return None  # CCSwitch 没装，拿不到数据

    data = {
        "requests": [],
        "summary": {},
        "raw": None,
    }

    # 方法1: 使用 ccswitch 命令行的 export 功能导出 JSON 数据
    cc_cmd = None
    for cmd_name in ["ccswitch", "ccswitch-cli"]:
        found = shutil_which(cmd_name)
        if found:
            cc_cmd = found
            break

    if cc_cmd:
        try:
            # 导出今天的数据
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

    # 方法2: 读取 CCSwitch 在本地缓存的文件
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

    # 方法3: 通过 HTTP API 获取
    # CCSwitch 默认在本机的 8008 端口开了一个 API 服务
    api_url = "http://localhost:8008"
    try:
        import urllib.request
        from urllib.parse import urlparse

        # 安全限制：只允许重定向到 localhost，防止 SSRF 攻击
        # SSRF 攻击是什么？就是攻击者诱导服务器去访问内部网络的地址
        class _LocalOnlyRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                parsed = urlparse(newurl)
                if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                    return None  # 不是本机地址，拒绝重定向
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

    return data  # 所有方法都失败了，返回空数据


def shutil_which(cmd: str) -> Optional[str]:
    """跨平台查找可执行文件的路径。

    比如在 Windows 上输入 "notepad"，它会返回 "C:\\Windows\\System32\\notepad.exe"。
    相当于在命令行里输入 where（Windows）或 which（Mac/Linux）。
    """
    import shutil
    return shutil.which(cmd)


def print_setup_result(agent: Optional[AgentInfo], ccs: dict, config: Optional[dict]):
    """打印安装和配置的结果到屏幕上。

    参数：
      agent: 检测到的 agent 信息
      ccs:   CCSwitch 检测结果
      config: 代理配置结果
    """
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
