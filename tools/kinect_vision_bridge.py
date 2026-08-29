#!/usr/bin/env python3
"""Low-rate Kinect/USB-camera bridge for NekoSuneAI vision.

This deliberately does not force a Kinect driver into the base Pi image. Kinect
v1/360 can be captured with libfreenect and Kinect v2 with libfreenect2. Point
this bridge at any command that writes one JPEG/PNG frame to a file, then it
posts that frame to NekoSuneAI's authenticated /api/vision/frame endpoint.

Example pattern:
  python tools/kinect_vision_bridge.py \
    --server https://neko.example.com --token "$WEB_DASHBOARD_TOKEN" \
    --frame /tmp/kinect.jpg --interval 5

Your capture tool/driver can refresh /tmp/kinect.jpg independently.
"""
from __future__ import annotations

import argparse
import base64
import time
from pathlib import Path

import requests


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--frame", required=True, help="JPEG/PNG file refreshed by the Kinect capture process")
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--source", default="kinect")
    args = p.parse_args()

    url = args.server.rstrip("/") + "/api/vision/frame"
    headers = {"X-Neko-Token": args.token, "Content-Type": "application/json"}
    path = Path(args.frame)
    previous_mtime = 0.0
    print(f"Kinect vision bridge -> {url}; Ctrl+C to stop")

    try:
        while True:
            try:
                stat = path.stat()
                if stat.st_mtime != previous_mtime:
                    data = path.read_bytes()
                    if 0 < len(data) <= 1_200_000:
                        response = requests.post(
                            url,
                            headers=headers,
                            json={
                                "source": args.source,
                                "image_base64": base64.b64encode(data).decode("ascii"),
                            },
                            timeout=90,
                        )
                        response.raise_for_status()
                        description = response.json().get("description", "")
                        print("Neko sees:", str(description)[:300])
                        previous_mtime = stat.st_mtime
            except FileNotFoundError:
                pass
            except Exception as exc:
                print("vision bridge warning:", exc)
            time.sleep(max(2.0, args.interval))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
