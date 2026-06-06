# Changelog

## v1.1 (2026-06-06)

- 新增交互式修复: `--optimize` 完成后逐条展示建议，确认后自动执行
- 自适应多 Agent 扫描: Claude Code / Codex CLI / Hermes 自动检测和配置扫描
- 新增 Hermes Agent 配置扫描 (config.yaml / skills / ccr)
- 仪表盘重设计: Neon Bento 风格, SVG 圆环评分, 可折叠建议, 响应式
- 修复 CCSwitch 数据对接链: 直接读取 SQLite DB, 去掉假安装流程
- 修复 Codex 动态内容警告 (用户指定不需要)
- 修复 API Key 显示过度暴露 (缩减至前4位)
- 修复 `--help` 在 Windows 下崩溃 (argparse 格式符冲突)
- 修复退出码: 无数据时返回 1 (提示) 而非 2 (严重)
- 修复 Hermes CCR 误将 .db 文件计入记忆文件
- 安全加固: HTML 转义文件名防 XSS, settings.json 不全量驻留
- 事务保护: `--fix apply` 先写后删, 写入失败自动回滚
- 添加 CC-Switch GitHub 链接, 未安装时自动打开下载页面
- 全面中文注释, 小白友好

## v1.0 (2026-06-06)

- 初始发布
- 基础功能: --detect, --data, --fix, --dashboard, --optimize, --setup
- Agent 检测: Claude Code / Codex CLI / Hermes / OpenClaw
- CCSwitch 数据对接 (pip 安装方式, 已废弃)
- 配置扫描: CLAUDE.md / 记忆文件 / MCP
- 数据解析: Tab 分隔日志 / 中文摘要
- 分析引擎: 命中率 / 成本 / 评分
- HTML 仪表盘 (GitHub 深色主题)
- 一键修复记忆文件合并
