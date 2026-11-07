#!/bin/zsh
set -eu
label=local.codex-task-queue
if /bin/launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
  /bin/launchctl bootout "gui/$UID/$label"
fi
plist="$HOME/Library/LaunchAgents/$label.plist"
if [[ -f "$plist" ]]; then
  mv "$plist" "$HOME/Library/Application Support/task-queue-codex/disabled.plist"
fi
echo '后台队列已停止。重新双击「打开任务队列」可恢复。'
