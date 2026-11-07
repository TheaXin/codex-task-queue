"""Local adapter for the user's installed Codex, reusing the MIT upstream RPC client."""
import shutil
import subprocess
import uuid
from pathlib import Path

from vendored.codex_rpc import codex_app_server_request, codex_subprocess_env, codex_turn_user_prompt


class PreflightError(RuntimeError):
    """The queue command has not started. Retrying cannot duplicate delivery."""


class InvalidTarget(PreflightError):
    """The selected UUID is invalid, archived, or unavailable."""


class Adapter:
    def __init__(self):
        self.cli = Path(shutil.which("codex") or Path.home() / ".local/bin/codex")

    def rpc(self, method, params):
        return codex_app_server_request(self.cli, method, params)

    def pages(self, method, params):
        cursor = None
        while True:
            page = self.rpc(method, dict(params, cursor=cursor))
            if not isinstance(page.get("data"), list):
                raise RuntimeError("Codex 返回了无法核验的分页结果")
            yield from page["data"]
            cursor = page.get("nextCursor")
            if not cursor:
                break

    def threads(self):
        rows = self.pages("thread/list", {"limit": 100, "sortKey": "updated_at", "archived": False,
                          "sourceKinds": ["cli", "vscode", "appServer", "exec"]})
        return [{"id": row["id"], "title": row.get("name") or row.get("preview", "")[:72] or "未命名会话",
                 "cwd": row["cwd"]} for row in rows if row.get("modelProvider") == "openai"]

    def quota(self):
        info = self.rpc("account/rateLimits/read", {})
        limit = info.get("rateLimits") or {}
        windows = [w for w in (limit.get("primary"), limit.get("secondary")) if isinstance(w, dict)]
        exhausted = [w for w in windows if w.get("usedPercent", 100) >= 100]
        allowed = (info.get("ordinaryUsageAllowed") is True and bool(windows) and not exhausted
                   and not limit.get("spendControlReached") and not limit.get("rateLimitReachedType"))
        return {"allowed": bool(allowed), "reason": "额度可用" if allowed else "等待 Codex 确认额度可用",
                "retry_at": max((w.get("resetsAt") or 0 for w in exhausted), default=None)}

    def submit(self, thread_id, prompt, job_id):
        try:
            if str(uuid.UUID(thread_id)) != thread_id or str(uuid.UUID(job_id)) != job_id:
                raise ValueError()
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidTarget("无效的会话或任务编号") from exc
        try:
            available = any(row["id"] == thread_id for row in self.threads())
        except Exception as exc:
            raise PreflightError("暂时无法核对目标会话") from exc
        if not available:
            raise InvalidTarget("目标会话已归档或不可用")
        env = codex_subprocess_env()
        try:
            subprocess.run([self.cli, "app-server", "daemon", "start"], env=env, check=True,
                           capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise PreflightError("Codex 后台服务暂时无法启动") from exc
        tag = f"[队列任务 {job_id}]"
        p = subprocess.run([self.cli, "queue", "--thread", thread_id, "--message",
                            tag + "\n" + prompt, "--resume"], env=env, capture_output=True,
                           text=True, timeout=60)
        if p.returncode or "warn" in (p.stdout + p.stderr).lower():
            raise RuntimeError("Codex 未确认送达，请核对目标会话")
        return job_id

    def result(self, thread_id, turn_id):
        tag = f"[队列任务 {turn_id}]\n"
        turns = self.pages("thread/turns/list", {"threadId": thread_id, "limit": 12,
                           "sortDirection": "desc", "itemsView": "full"})
        for turn in turns:
            if not (codex_turn_user_prompt(turn) or "").startswith(tag):
                continue
            error = (turn.get("error") or {}).get("codexErrorInfo")
            if error in ("usageLimitExceeded", "rateLimitExceeded"):
                return "quota"
            return {"inProgress": "running", "completed": "completed", "failed": "failed",
                    "interrupted": "interrupted"}.get(turn.get("status"), "unknown")
        return "unknown"
