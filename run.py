"""One-command launcher. All dependencies and model artifacts stay in this project."""

import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("Use Python 3.12 or newer; 3.12 is tested.")
    environment = ROOT / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    requirement = ROOT / "requirements.txt"
    stamp = environment / "requirements.sha256"
    digest = hashlib.sha256(requirement.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text() != digest:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirement)], check=True
        )
        stamp.write_text(digest)
    from provider import health
    from setup_model import setup

    model_process = None
    log = None
    try:
        if "--fixtures-only" not in sys.argv and not health():
            model = setup()
            if os.name == "nt":
                binary = next((ROOT / "runtime" / "llama").rglob("llama-server.exe"))
            else:
                binary = shutil.which("llama-server")
                if not binary:
                    raise SystemExit(
                        "Install llama.cpp and put llama-server on PATH, or use --fixtures-only."
                    )
            key = ROOT / "runtime" / "model.key"
            if not key.exists():
                key.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            log = (ROOT / "runtime" / "model-server.log").open("a", encoding="utf-8")
            model_process = subprocess.Popen(
                [
                    str(binary),
                    "-m",
                    str(model),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8093",
                    "-c",
                    "4096",
                    "-t",
                    "4",
                    "--parallel",
                    "1",
                    "--no-ui",
                    "--api-key-file",
                    str(key),
                    "--cors-origins",
                    "http://127.0.0.1:4183",
                ],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for _ in range(60):
                if health():
                    break
                if model_process.poll() is not None:
                    raise RuntimeError(
                        "Model server exited; see runtime/model-server.log"
                    )
                time.sleep(1)
            else:
                raise RuntimeError(
                    "Model did not become ready; see runtime/model-server.log"
                )
        print("Open http://127.0.0.1:4183 — stop with Ctrl+C", flush=True)
        subprocess.run(
            [
                str(python),
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                "4183",
            ],
            cwd=ROOT,
            check=True,
        )
    except KeyboardInterrupt:
        pass
    finally:
        if model_process:
            model_process.terminate()
            try:
                model_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                model_process.kill()
        if log:
            log.close()


if __name__ == "__main__":
    main()
