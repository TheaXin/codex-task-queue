"""Local durable Codex dispatcher. No remote exposure or shell evaluation."""

from contextlib import contextmanager
import argparse
import fcntl
import json
import os
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("QUEUE_DATA", str(ROOT / ".queue-data")))
quota = "有到期任务时检查额度"
next_quota_check = 0
threads = []
guard = threading.Lock()


from adapter import Adapter, InvalidTarget, PreflightError

adapter = Adapter()


@contextmanager
def db():
    c = sqlite3.connect(DATA / "jobs.sqlite", timeout=10)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()


def update_job(job_id, **fields):
    with db() as c:
        c.execute(
            "update jobs set " + ",".join(k + "=?" for k in fields) + " where id=?",
            (*fields.values(), job_id),
        )


def update_active_job(job_id, **fields):
    with db() as c:
        c.execute(
            "update jobs set " + ",".join(k + "=?" for k in fields)
            + " where id=? and status in ('running','review')",
            (*fields.values(), job_id),
        )


def dispatch():
    global quota, next_quota_check
    with db() as c:
        active = c.execute(
            "select * from jobs where status in ('running','review') and turn_id is not null"
        ).fetchall()
    for running in active:
        try:
            result = adapter.result(running["thread_id"], running["turn_id"])
        except Exception as exc:
            update_active_job(running["id"], detail="等待执行回执：" + str(exc)[:180])
            continue
        if result == "completed":
            update_active_job(running["id"], status="delivered", detail="执行完成")
        elif result == "quota":
            update_active_job(
                running["id"],
                status="waiting_quota",
                detail="额度恢复后自动继续未完成工作",
            )
        elif result in {"failed", "interrupted"}:
            update_active_job(
                running["id"],
                status="review",
                detail="执行中断，请核对目标会话：" + result,
            )
        elif result == "running":
            update_active_job(running["id"], status="running", detail="Codex 正在执行")
        elif time.time() - running["attempt_at"] > 900:
            update_active_job(
                running["id"],
                status="review",
                detail="暂未找到投递回执，请核对目标会话",
            )
    with db() as c:
        job = c.execute(
            """select * from jobs j where status in ('queued','waiting_quota') and due<=? and retry_at<=?
            and not exists(select 1 from jobs s where s.thread_id=j.thread_id and s.id!=j.id and s.status in ('review','sending','running','waiting_quota'))
            and (j.status='waiting_quota' or not exists(select 1 from jobs p where p.thread_id=j.thread_id and p.status='queued' and (p.due<j.due or (p.due=j.due and p.rowid<j.rowid))))
            order by due,rowid limit 1""",
            (time.time(), time.time()),
        ).fetchone()
    if not job or time.time() < next_quota_check:
        return
    limits = adapter.quota()
    quota = limits["reason"]
    if not limits["allowed"]:
        next_quota_check = limits.get("retry_at") or time.time() + 60
        return
    recovering = job["status"] == "waiting_quota"
    attempt = str(uuid.uuid4()) if recovering else job["id"]
    prompt = job["prompt"]
    if recovering:
        prompt = (
            "请继续本会话中队列任务 "
            + job["id"]
            + " 因额度耗尽而中断的工作。先核对会话记录和实际成果，只完成尚未完成的部分。"
            "对已提交、发送、发布或其他不可重复操作，先核实结果，无法确定时暂停并说明，避免重复执行。"
        )
    with db() as c:
        if not c.execute(
            "update jobs set status='sending',turn_id=?,attempt_at=? where id=? and status=?",
            (attempt, time.time(), job["id"], job["status"]),
        ).rowcount:
            return
    try:
        turn = adapter.submit(job["thread_id"], prompt, attempt)
        if not turn:
            raise RuntimeError("缺少执行回执")
        update_job(job["id"], status="running", turn_id=turn, detail="Codex 已接收")
    except InvalidTarget as exc:
        update_job(job["id"], status="review", turn_id=None, detail=str(exc))
    except PreflightError as exc:
        update_job(
            job["id"],
            status=job["status"],
            retry_at=int(time.time() + 60),
            turn_id=job["turn_id"],
            attempt_at=job["attempt_at"],
            detail=str(exc)[:200],
        )
    except Exception as exc:
        update_job(
            job["id"],
            status="review",
            detail="投递未确认，正在核对目标会话：" + str(exc)[:200],
        )


def loop():
    global quota
    while True:
        try:
            dispatch()
        except Exception as e:
            quota = "等待 Codex 连接或额度信息：" + str(e)[:160]
        time.sleep(30)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data, mime="application/json"):
        body = (
            json.dumps(data, ensure_ascii=False).encode()
            if mime == "application/json"
            else data
        )
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def trusted(self):
        return self.headers.get("Host") in {
            f"localhost:{self.server.server_port}",
            f"127.0.0.1:{self.server.server_port}",
        }

    def do_GET(self):
        global threads
        if not self.trusted():
            return self.reply(403, {})
        if self.path == "/":
            return self.reply(
                200, (ROOT / "static" / "index.html").read_bytes(), "text/html"
            )
        if (
            self.path in ("/static/app.js", "/static/style.css")
            and (ROOT / self.path[1:]).exists()
        ):
            return self.reply(
                200,
                (ROOT / self.path[1:]).read_bytes(),
                "text/javascript" if self.path.endswith(".js") else "text/css",
            )
        if self.path != "/api/state":
            return self.reply(404, {})
        try:
            error = ""
            with guard:
                if time.time() - getattr(self.server, "refreshed", 0) > 60:
                    try:
                        threads = adapter.threads()
                    except Exception as exc:
                        error = str(exc) or "无法读取会话"
                    if not error:
                        self.server.refreshed = time.time()
            with db() as c:
                jobs = [
                    dict(r) for r in c.execute("select * from jobs order by rowid desc")
                ]
            self.reply(200, dict(threads=threads, jobs=jobs, quota=error or quota))
        except Exception as e:
            self.reply(503, {"error": str(e)})

    def do_POST(self):
        if (
            not self.trusted()
            or self.headers.get("Origin") != "http://" + self.headers["Host"]
            or self.headers.get_content_type() != "application/json"
        ):
            return self.reply(403, {})
        try:
            n = int(self.headers["Content-Length"])
            if not 0 < n <= 128000:
                raise ValueError("任务过长")
            data = json.loads(self.rfile.read(n))
            key = str(uuid.UUID(data["id"]))
            with db() as c:
                if self.path == "/api/drafts":
                    prompt = data["prompt"]
                    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 30000:
                        raise ValueError("请填写灵感内容")
                    saved = c.execute(
                        """insert into jobs(id,thread_id,prompt,due,status,detail)
                           values(?,'',?,0,'draft','')
                           on conflict(id) do update set prompt=excluded.prompt where jobs.status='draft'""",
                        (key, prompt),
                    )
                    if not saved.rowcount:
                        raise ValueError("这条灵感已离开草稿")
                elif self.path == "/api/jobs":
                    tid = str(uuid.UUID(data["thread_id"]))
                    prompt = data["prompt"]
                    due = data["due"]
                    if type(due) is not int or not 0 <= due <= 253402300799:
                        raise ValueError("最早执行时间无效")
                    if (
                        not isinstance(prompt, str)
                        or not prompt.strip()
                        or len(prompt) > 30000
                        or tid not in {r["id"] for r in threads}
                    ):
                        raise ValueError("请重新选择会话并填写任务")
                    c.execute(
                        "update jobs set thread_id=?, prompt=?, due=?, status='queued' where id=? and status='draft'",
                        (tid, prompt, due, key),
                    )
                    c.execute(
                        "insert or ignore into jobs(id,thread_id,prompt,due,status,detail) values(?,?,?,?,'queued','')",
                        (key, tid, prompt, due),
                    )
                    existing = c.execute(
                        "select thread_id,prompt,due from jobs where id=?", (key,)
                    ).fetchone()
                    if tuple(existing) != (tid, prompt, due):
                        raise ValueError("任务编号冲突")
                elif self.path == "/api/ack":
                    if not c.execute(
                        "update jobs set status='reviewed',detail='已人工核对' where id=? and status='review'",
                        (key,),
                    ).rowcount:
                        raise ValueError("当前任务无需核对")
                elif self.path == "/api/cancel":
                    if not c.execute(
                        "update jobs set status='cancelled' where id=? and status in ('queued','waiting_quota','draft')",
                        (key,),
                    ).rowcount:
                        raise ValueError("任务已离开等待队列")
                else:
                    return self.reply(404, {})
            self.reply(200, {"id": key})
        except Exception as e:
            self.reply(400, {"error": str(e)})


def initialize():
    with db() as c:
        c.execute(
            "create table if not exists jobs(id text primary key,thread_id text not null,prompt text not null,due integer not null,status text not null,detail text not null,turn_id text)"
        )
        columns = {row[1] for row in c.execute("pragma table_info(jobs)")}
        if "attempt_at" not in columns:
            c.execute("alter table jobs add column attempt_at real not null default 0")
        if "retry_at" not in columns:
            c.execute("alter table jobs add column retry_at real not null default 0")
        c.execute(
            "update jobs set status='review',detail='服务在投递时中断，请核对目标会话' where status='sending'"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    os.umask(0o077)
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (DATA / "lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    initialize()
    http = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=loop, daemon=True).start()
    http.serve_forever()
