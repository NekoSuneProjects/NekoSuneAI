#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_URL = "https://huggingface.co/onnxmodelzoo/emotion-ferplus-8/resolve/main/emotion-ferplus-8.onnx?download=true"
DEFAULT_OUT = Path("data/models/emotion-ferplus-8.onnx")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the optional lightweight FER+ facial-expression model.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Override model URL, e.g. your own INT8 FER+ ONNX build")
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading FER+ model to {output} ...")
    req = Request(args.url, headers={"User-Agent": "NekoSuneAI-local-affect/1"})
    sha = hashlib.sha256()
    total = 0
    with urlopen(req, timeout=120) as response, output.open("wb") as f:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            f.write(block)
            sha.update(block)
            total += len(block)
    if total < 1_000_000:
        output.unlink(missing_ok=True)
        raise RuntimeError("Downloaded file is unexpectedly small; model download likely failed")
    print(f"Installed {total / 1024 / 1024:.1f} MiB; sha256={sha.hexdigest()}")
    print("Set LOCAL_AFFECT_MODEL to this path if it is not /app/data/models/emotion-ferplus-8.onnx.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
