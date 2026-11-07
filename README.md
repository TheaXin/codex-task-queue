# 候场 · Codex 任务队列

在本机网页中选择已有 Codex 会话、安排任务，并在额度可用后执行。任务保存在 SQLite 中，网页关闭后，已安装的 macOS 后台服务继续调度。

## macOS App

安装 Xcode 或 Command Line Tools 后，运行 `bash macos/build.sh`。解压 `dist/候场-macOS.zip`，双击「候场.app」。App 使用独立窗口，与网页共用本机任务数据库。需要 Python 3.10+ 和已登录的 Codex CLI。构建产物仅做本地签名，未进行 Apple 公证。

## 功能

- 选择「仅保存灵感」，无需指定会话或执行时间。灵感可以编辑，只有明确加入队列才会执行。

- 按名称、目录和会话 ID 搜索已有会话，提交前展示完整 ID。
- 立即排队或设置最早执行时间，额度不足时等待恢复。
- 同一会话按计划时间和入队顺序处理，前一项未完成时阻止后续任务插入。
- 通过任务标记读取 Codex 回执，区分等待、执行中、完成和需要核对。
- 对明确的额度中断发送续跑指令，要求先核对已完成成果。
- 按状态筛选任务，展开完整内容，取消等待中的任务。

## 环境与启动

已在 macOS 上使用 Codex CLI 0.166.0 验证。需要 Python 3.10 或更新版本，以及已登录的官方 Codex CLI。运行代码仅依赖 Python 标准库和仓库内附带的上游代码。

macOS 上，在项目目录执行一次：

```sh
python3 launcher.py
```

也可双击 `打开任务队列.command`。启动器安装用户级 LaunchAgent、打开网页，并在以后登录时启动服务。再次运行启动器会更新运行版本，保留队列数据。

打开 [本机任务工作台](http://127.0.0.1:8787)。选择会话，核对目录和完整 ID，填写任务并加入队列。

停止后台服务可双击 `停止后台队列.command`。再次运行启动器可重新启用服务。

直接运行服务适合开发与调试：

```sh
python3 server.py --port 8787
```

直接启动会持续占用当前进程。关闭该进程后，队列在下次启动时恢复检查。服务使用 POSIX 文件锁，原生 Windows 不支持当前实现。Linux 和其他平台尚未验证。macOS 启动器依赖 `launchctl` 和 `open`。

## 数据与运行条件

| 内容 | 位置 |
| --- | --- |
| 启动器安装的程序版本、日志与数据 | `~/Library/Application Support/task-queue-codex/` |
| 启动器模式的任务数据库 | 上述目录中的 `data/jobs.sqlite` |
| 直接启动时的任务数据库 | 项目下 `.queue-data/jobs.sqlite` |
| 自定义数据目录 | 直接启动时设置环境变量 `QUEUE_DATA`（启动器固定使用安装目录下的 data） |
| 登录启动配置 | `~/Library/LaunchAgents/` 中的项目配置 |

数据库包含任务内容、会话 ID、时间和状态。备份前停止服务，再复制整个数据目录。升级时保留数据目录。

后台运行需要用户登录 macOS、电脑开机并联网。睡眠、关机或服务停止期间，到期任务会在运行恢复后重新检查。目标会话的 Codex 权限设置仍适用，权限审批可能需要人工处理。

页面仅监听 `127.0.0.1`。额度检查通过本机 Codex 运行时完成。额度等待不会自动购买额度或兑换重置券。

## 故障恢复与边界

网页提交使用稳定的任务 ID，重复提交相同请求会复用已保存记录。投递前先持久化状态，收到回执后再更新执行状态。

如果发送超时、进程中断或结果不明，任务进入“需要核对”。请检查对应 Codex 会话及实际成果，再点击“已检查会话，解除阻塞”。已有回执也可能让系统自动恢复判断。

这些机制减少重复投递和误判，但不能保证 Codex 执行的每个外部操作恰好发生一次。尤其是发送消息、发布、提交等操作，应由任务本身核验结果。额度中断的续跑使用新的投递标记，并提示 Codex 只完成剩余工作。

自然耗尽额度后跨真实重置窗口的完整流程仍待长期实测。当前验证覆盖真实会话发现、任务投递与完成回执，以及通过模拟测试覆盖的额度等待和恢复逻辑。

## 测试

```sh
python3 -m unittest discover -p 'test_*.py' -v
```

测试使用模拟 Codex 适配器或子进程，不向真实会话发送任务。覆盖额度判断、分页回执、投递前失败、模糊投递结果、崩溃恢复、同会话排序和额度中断续跑。浏览器验收覆盖状态筛选、详情展开、草稿恢复和窄屏布局。

## 复用与来源

本项目复用 [Claude + Codex Queue](https://github.com/ravhello/claude-codex-queue) 的 RPC 与环境处理代码，来源固定在提交 `2497b1b7713e0305f8af46b51846685a39c0a3a4`。上游采用 MIT 许可证，原始许可保存在 `vendored/LICENSE`。任务执行依赖用户安装的 [官方 Codex CLI](https://github.com/openai/codex)。

---

# Houchang · Codex Task Queue

Choose an existing Codex conversation in a local web interface, schedule tasks, and run them when quota becomes available. Tasks are stored in SQLite. After installation, the macOS background service continues scheduling when the browser closes.

## macOS app

With Xcode or Command Line Tools installed, run `bash macos/build.sh`. Extract `dist/候场-macOS.zip` and open `候场.app`. The app opens a separate window and shares the web interface's local queue database. It requires Python 3.10+ and a signed-in Codex CLI. The build is signed locally and is not notarized by Apple.

## Features

- Choose “Save as idea” to capture a draft without a conversation or execution time. Edit it later and explicitly queue it when ready.

- Search existing conversations by name, directory, or conversation ID. Review the full ID before submitting.
- Queue tasks immediately or choose an earliest start time. Wait when quota is unavailable.
- Process tasks for each conversation by scheduled time and insertion order. An unfinished task blocks later tasks in that conversation.
- Read Codex receipts using task markers to distinguish waiting, running, completed, and review states.
- Send continuation instructions after a confirmed quota interruption, asking Codex to inspect completed work first.
- Filter tasks by status, expand full details, and cancel waiting tasks.

## Requirements and startup

Verified on macOS with Codex CLI 0.166.0. Requires Python 3.10 or later and an authenticated official Codex CLI installation. Runtime code uses the Python standard library and upstream code included in this repository.

On macOS, run once from the project directory:

```sh
python3 launcher.py
```

You can also double-click `打开任务队列.command` (“Open task queue”). The launcher installs a user-level LaunchAgent, opens the dashboard, and starts the service at future logins. Running it again updates the installed version while retaining queue data.

Open the [local dashboard](http://127.0.0.1:8787). Choose a conversation, check its directory and full ID, enter a task, and add it to the queue.

Double-click `停止后台队列.command` (“Stop background queue”) to stop the service. Run the launcher again to enable it.

For development and debugging, run the service directly:

```sh
python3 server.py --port 8787
```

Direct startup keeps the current process running. After that process stops, the queue resumes checking on the next startup. The service uses POSIX file locks, so native Windows does not support the current implementation. Linux and other platforms have not been verified. The macOS launcher requires `launchctl` and `open`.

## Data and operating conditions

| Content | Location |
| --- | --- |
| Installed program versions, logs, and data | `~/Library/Application Support/task-queue-codex/` |
| Task database in launcher mode | `data/jobs.sqlite` inside that directory |
| Task database with direct startup | `.queue-data/jobs.sqlite` in the project |
| Custom data directory | Set `QUEUE_DATA` for direct server startup; the launcher always uses its installed data directory |
| Login startup configuration | Project configuration under `~/Library/LaunchAgents/` |

The database contains task text, conversation IDs, timestamps, and statuses. Stop the service before backing up the entire data directory. Preserve this directory during upgrades.

Background operation requires a logged-in macOS user, a powered-on computer, and network access. Tasks that become due during sleep, shutdown, or service downtime are checked after operation resumes. The target conversation's Codex permission settings still apply. Approval requests may require human action.

The dashboard listens only on `127.0.0.1`. Quota checks use the local Codex runtime. Waiting for quota does not automatically purchase credits or redeem reset credits.

## Recovery and limitations

Browser submissions use a stable task ID. Repeating the same request reuses its stored record. The service persists the delivery state before sending and updates execution status after receiving a receipt.

A send timeout, process interruption, or uncertain result moves the task to “Needs review.” Inspect the target Codex conversation and actual outputs before choosing “I checked the conversation; unblock.” A later receipt may also allow automatic reconciliation.

These mechanisms reduce duplicate delivery and incorrect status reporting, but they cannot guarantee that every external operation performed by Codex happens exactly once. Tasks involving messages, publication, or commits should verify their own outcomes. Continuation after a quota interruption uses a new delivery marker and asks Codex to finish only the remaining work.

A complete real-world run across natural quota exhaustion and its reset window still requires long-term validation. Current verification covers real conversation discovery, task delivery, and completion receipts, plus simulated quota waiting and recovery.

## Tests

```sh
python3 -m unittest discover -p 'test_*.py' -v
```

Tests use simulated Codex adapters or subprocesses and send no tasks to real conversations. Coverage includes quota checks, paginated receipts, preflight failures, ambiguous delivery, crash recovery, per-conversation ordering, and continuation after quota interruptions. Browser checks cover status filters, expanded details, draft recovery, and narrow layouts.

## Reuse and sources

This project reuses RPC and environment-handling code from [Claude + Codex Queue](https://github.com/ravhello/claude-codex-queue), pinned to commit `2497b1b7713e0305f8af46b51846685a39c0a3a4`. The upstream project uses the MIT license, preserved in `vendored/LICENSE`. Task execution relies on the user's installed [official Codex CLI](https://github.com/openai/codex).
