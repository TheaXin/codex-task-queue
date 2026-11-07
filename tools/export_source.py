"""Build a source-only archive from an explicit public-file allowlist."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ".gitignore", ".gitattributes", "README.md", "LICENSE", "NOTICE.md",
    "SECURITY.md", "CONTRIBUTING.md", "server.py", "adapter.py", "launcher.py",
    "打开任务队列.command", "停止后台队列.command", "tools/export_source.py",
    "macos/App.swift", "macos/Icon.swift", "macos/build.sh",
]
PATTERNS = ["test_*.py", "static/*.html", "static/*.css", "static/*.js",
            "vendored/*.py", "vendored/LICENSE*", "vendored/SOURCE.md", ".github/workflows/*.yml"]


def export():
    paths = [ROOT / name for name in FILES]
    for pattern in PATTERNS:
        paths.extend(sorted(ROOT.glob(pattern)))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Invalid source file: {path.relative_to(ROOT)}")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / "codex-task-queue-source.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            bundle.write(path, "codex-task-queue/" + str(path.relative_to(ROOT)))
    print(archive)
    print(f"{len(paths)} public files")


if __name__ == "__main__":
    export()
