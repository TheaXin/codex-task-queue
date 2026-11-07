"""Install or refresh the per-user macOS worker and open its local dashboard."""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LABEL = "local.codex-task-queue"
DOMAIN = f"gui/{os.getuid()}"
URL = "http://127.0.0.1:8787"
RUNTIME = Path.home() / "Library/Application Support/task-queue-codex"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def launchctl(*args, check=True):
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, check=check)


def install(*, open_browser=True):
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    # Migrate legacy personal installs without embedding a personal label.
    agents = Path.home() / "Library/LaunchAgents"
    for legacy in agents.glob("local.*.codex-task-queue.plist"):
        try:
            config = plistlib.loads(legacy.read_bytes())
        except (OSError, plistlib.InvalidFileException):
            continue
        if config.get("WorkingDirectory") != str(RUNTIME):
            continue
        old_label = config.get("Label")
        if not isinstance(old_label, str) or old_label == LABEL:
            continue
        launchctl("bootout", f"{DOMAIN}/{old_label}", check=False)
        backup = RUNTIME / "legacy-launchagents"
        backup.mkdir(exist_ok=True)
        legacy.replace(backup / (str(time.time_ns()) + ".plist"))
    files = [ROOT / name for name in ("server.py", "adapter.py", "LICENSE", "NOTICE.md", "vendored/LICENSE",
                                      "vendored/codex_rpc.py",
                                      "vendored/SOURCE.md")]
    files += sorted(p for p in (ROOT / "static").rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())
    release = RUNTIME / "versions" / digest.hexdigest()[:16]
    for src in files:
        dest = release / src.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or src.read_bytes() != dest.read_bytes():
            shutil.copyfile(src, dest)
    config = dict(Label=LABEL, ProgramArguments=[sys.executable, str(release / "server.py")],
                  WorkingDirectory=str(RUNTIME), RunAtLoad=True, KeepAlive=True,
                  ThrottleInterval=15, EnvironmentVariables={"PATH": os.environ["PATH"], "QUEUE_DATA": str(RUNTIME / "data")},
                  StandardErrorPath=str(RUNTIME / "service.log"))
    data = plistlib.dumps(config)
    changed = not PLIST.exists() or PLIST.read_bytes() != data
    if changed:
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        tmp = PLIST.with_suffix(".new")
        tmp.write_bytes(data)
        tmp.replace(PLIST)
        launchctl("bootout", f"{DOMAIN}/{LABEL}", check=False)
    if changed or launchctl("print", f"{DOMAIN}/{LABEL}", check=False).returncode:
        for attempt in range(20):
            result = launchctl("bootstrap", DOMAIN, str(PLIST), check=False)
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(result.stderr.decode(errors="replace"))

    for _ in range(40):
        try:
            with urllib.request.urlopen(URL + "/api/state", timeout=3) as res:
                state = json.load(res)
            if "jobs" in state and "threads" in state:
                if open_browser:
                    subprocess.run(["open", URL], check=True)
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise SystemExit(f"服务未就绪，请查看 {RUNTIME / 'service.log'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-open", action="store_true")
    install(open_browser=not parser.parse_args().no_open)
