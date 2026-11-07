"""MIT-derived Codex RPC transport, scoped to native macOS/POSIX.
See LICENSE and SOURCE.md for provenance and adaptation details.
"""
import contextlib
import fcntl
import json
import os
import re
import queue as queue_module
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_CODEX_APP_SERVER_LOCK = threading.RLock()

@contextlib.contextmanager
def _state_file_lock(thread_lock, state_path):
    with thread_lock:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

CODEX_EXTERNAL_AUTH_ENV_VARS = {
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
}

def safe_json_loads(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None

def truncate(value: str | None, length: int = 90) -> str:
    if not value:
        return ""
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= length:
        return compact
    return compact[: length - 1] + "..."

def _codex_app_server_request_unlocked(
    codex_exe: Path,
    method: str,
    params: dict[str, Any],
    timeout: int = 45,
    *,
    codex_home: Path | None = None,
) -> dict[str, Any]:
    command = [str(codex_exe), "app-server", "--listen", "stdio://"]
    process_env = codex_subprocess_env(
        codex_home,
        windows=False,
    )
    process_env["RUST_LOG"] = "warn"
    process_env["RUST_LOG_STYLE"] = "never"
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=process_env,
    )
    responses: queue_module.Queue[dict[str, Any]] = queue_module.Queue()
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            value = safe_json_loads(line)
            if value:
                responses.put(value)

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line.rstrip())
            if len(stderr_lines) > 50:
                del stderr_lines[:-50]

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()

    def send(message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise ValueError("stdin di Codex app-server non disponibile.")
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def wait_for(request_id: int, deadline: float) -> dict[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = truncate(" ".join(stderr_lines), 500) or "timeout"
                raise ValueError(f"Codex app-server non ha risposto a {method}: {detail}")
            try:
                value = responses.get(timeout=remaining)
            except queue_module.Empty as exc:
                detail = truncate(" ".join(stderr_lines), 500) or "timeout"
                raise ValueError(f"Codex app-server non ha risposto a {method}: {detail}") from exc
            if value.get("id") == request_id:
                return value

    deadline = time.monotonic() + timeout
    try:
        send({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "claude-codex-queue", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        })
        initialize = wait_for(1, deadline)
        if isinstance(initialize.get("error"), dict):
            raise ValueError(f"Inizializzazione Codex app-server fallita: {initialize['error']}")
        send({"method": "initialized"})
        request_id = 2
        if method == "thread/rollback":
            thread_id = params.get("threadId")
            if not isinstance(thread_id, str) or not thread_id:
                raise ValueError("thread/rollback richiede un threadId valido.")
            send(
                {
                    "id": request_id,
                    "method": "thread/resume",
                    "params": {"threadId": thread_id},
                }
            )
            resumed = wait_for(request_id, deadline)
            resume_error = resumed.get("error")
            if isinstance(resume_error, dict):
                message = (
                    resume_error.get("message")
                    if isinstance(resume_error.get("message"), str)
                    else json.dumps(resume_error)
                )
                raise ValueError(f"Codex thread/resume prima del rollback non riuscito: {message}")
            request_id += 1
        send({"id": request_id, "method": method, "params": params})
        response = wait_for(request_id, deadline)
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    error = response.get("error")
    if isinstance(error, dict):
        message = error.get("message") if isinstance(error.get("message"), str) else json.dumps(error)
        raise ValueError(f"Codex {method} non riuscito: {message}")
    value = response.get("result")
    if not isinstance(value, dict):
        raise ValueError(f"Risposta Codex {method} non valida.")
    return value

def codex_app_server_request(
    codex_exe: Path,
    method: str,
    params: dict[str, Any],
    timeout: int = 45,
    *,
    codex_home: Path | None = None,
) -> dict[str, Any]:
    lock_root = codex_home or Path(tempfile.gettempdir()) / "claude-codex-queue"
    lock_state = lock_root / ".claude-codex-queue-app-server"
    with _state_file_lock(_CODEX_APP_SERVER_LOCK, lock_state):
        return _codex_app_server_request_unlocked(
            codex_exe,
            method,
            params,
            timeout,
            codex_home=codex_home,
        )

def codex_turn_user_prompt(turn: dict[str, Any]) -> str | None:
    items = turn.get("items") if isinstance(turn.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "userMessage":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None
        parts: list[str] = []
        for entry in content:
            if not isinstance(entry, dict):
                return None
            if entry.get("type") != "text" or not isinstance(entry.get("text"), str):
                return None
            parts.append(entry["text"])
        return "\n".join(parts) if parts else None
    return None

def codex_subprocess_env(
    codex_home: Path | None = None,
    *,
    windows: bool = False,
) -> dict[str, str]:
    env = os.environ.copy()
    for name in CODEX_EXTERNAL_AUTH_ENV_VARS:
        env.pop(name, None)
    if codex_home is not None:
        env["CODEX_HOME"] = str(codex_home)
    return env
