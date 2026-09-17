"""Fetch pinned official artifacts into this project; verify SHA-256 before use."""

import hashlib
import os
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
MODEL_NAME = "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
MODEL_REV = "f86cb2c1fa58255f8052cc32aeede1b7482d4361"
MODEL_SHA = "cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046"
BINARY_SHA = "617529171621548ada99e7b4f4f6234aab76129a674d3594dec4cfdfebb3ebec"
BINARY_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11026/llama-b11026-bin-win-cpu-x64.zip"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, target, digest):
    if target.exists() and sha(target) == digest:
        print(f"Verified cached {target.name}", flush=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    print(f"Downloading {target.name} from the official publisher...", flush=True)
    with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as out:
        count = 0
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            count += len(chunk)
            if count % (32 * 1024 * 1024) == 0:
                print(f"  {count // (1024 * 1024)} MiB", flush=True)
    if sha(part) != digest:
        raise RuntimeError("Checksum mismatch; downloaded artifact will not be used")
    part.replace(target)
    print(f"Checksum verified: {target.name}", flush=True)


def setup():
    model = RUNTIME / "models" / MODEL_NAME
    download(
        f"https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/{MODEL_REV}/{MODEL_NAME}",
        model,
        MODEL_SHA,
    )
    if os.name == "nt":
        archive = RUNTIME / "llama-b11026.zip"
        download(BINARY_URL, archive, BINARY_SHA)
        directory = (RUNTIME / "llama").resolve()
        directory.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                target = (directory / member.filename).resolve()
                if not target.is_relative_to(directory):
                    raise RuntimeError("Unsafe archive member")
            z.extractall(directory)
        print("Local inference runtime ready.", flush=True)
    else:
        print(
            "Model ready. Install llama.cpp separately and put llama-server on PATH.",
            flush=True,
        )
    return model


if __name__ == "__main__":
    setup()
