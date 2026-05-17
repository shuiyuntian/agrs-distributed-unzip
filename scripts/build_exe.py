#!/usr/bin/env python3
"""
将 Master 和 Worker 打包为独立的单 EXE 文件
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist_exe"

MASTER_HIDDEN_IMPORTS = [
    "aiosqlite",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "jinja2",
    "markupsafe",
    "uvicorn",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "websockets",
    "httptools",
    "click",
    "colorama",
    "yaml",
    "cffi",
    "cryptography",
    "ecdsa",
    "rsa",
    "pyasn1",
    "idna",
    "charset_normalizer",
    "certifi",
    "urllib3",
    "requests",
    "typing_extensions",
    "typing_inspection",
    "annotated_types",
    "anyio",
    "h11",
    "python_dotenv",
    "watchfiles",
    "python_multipart",
    "psutil",
    "sqlite3",
    # passlib handlers (dynamically imported)
    "passlib.handlers.bcrypt",
    "passlib.handlers.pbkdf2",
    "passlib.handlers.sha2_crypt",
    "passlib.handlers.sha1_crypt",
    "passlib.handlers.md5_crypt",
    "passlib.handlers.des_crypt",
    "passlib.handlers.digests",
    "passlib.handlers.misc",
    "passlib.handlers.scrypt",
    "passlib.handlers.argon2",
    "passlib.handlers.django",
    "passlib.handlers.ldap_digests",
]

WORKER_HIDDEN_IMPORTS = [
    "requests",
    "psutil",
    "zipfile",
    "tarfile",
    "gzip",
    "subprocess",
]


def run_pyinstaller(entry_script, name, hidden_imports, datas=None, paths=None):
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconfirm",
        "--clean",
        "--name", name,
        "--distpath", str(DIST_DIR),
        "--workpath", str(DIST_DIR / "build"),
        "--specpath", str(DIST_DIR / "spec"),
    ]
    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])
    if datas:
        for src, dst in datas:
            sep = ";" if sys.platform == "win32" else ":"
            cmd.extend(["--add-data", f"{src}{sep}{dst}"])
    if paths:
        for p in paths:
            cmd.extend(["--paths", p])
    cmd.append(str(entry_script))
    print(f"\n[BUILD] {name} ...")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode == 0


def build_master():
    entry = PROJECT_ROOT / "master" / "main.py"
    datas = [(str(PROJECT_ROOT / "master" / "static"), "master/static")]
    paths = [str(PROJECT_ROOT)]
    return run_pyinstaller(entry, "master", MASTER_HIDDEN_IMPORTS, datas, paths)


def build_worker():
    entry = PROJECT_ROOT / "worker" / "worker.py"
    paths = [str(PROJECT_ROOT)]
    return run_pyinstaller(entry, "worker", WORKER_HIDDEN_IMPORTS, None, paths)


def main():
    print("=" * 60)
    print("  打包为独立 EXE")
    print("=" * 60)
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    success_master = build_master()
    success_worker = build_worker()
    print("\n" + "=" * 60)
    if success_master and success_worker:
        print("  打包成功！")
        for f in sorted(DIST_DIR.glob("*.exe")):
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f} ({size_mb:.1f} MB)")
    else:
        print("  打包失败，请查看上方错误信息")
    print("=" * 60)


if __name__ == "__main__":
    main()
