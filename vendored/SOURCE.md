# 第三方代码来源

来源 https://github.com/ravhello/claude-codex-queue
固定提交 2497b1b7713e0305f8af46b51846685a39c0a3a4
文件 claude_vscode_queue/app.py
许可 MIT，完整许可见 LICENSE。

提取 RPC 请求、环境清理、用户消息解析及其辅助函数。
适配仅支持原生 macOS/POSIX，直接启动 CLI，文件锁使用 fcntl。
移除 Windows 启动路径，保留请求初始化、错误、超时、清理和环境清理行为。
