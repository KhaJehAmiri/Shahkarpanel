#!/usr/bin/env python3
"""Shahkar web installer wizard — serves UI, collects config, streams progress."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

INSTALLER_DIR = Path(__file__).resolve().parent
CONFIG_PATH: Path | None = None
PROGRESS_PATH: Path | None = None


def _public_ip() -> str:
    try:
        import urllib.request

        return urllib.request.urlopen("https://api.ipify.org", timeout=6).read().decode().strip()
    except Exception:
        pass
    try:
        out = subprocess.check_output(["hostname", "-I"], text=True, stderr=subprocess.DEVNULL)
        parts = out.strip().split()
        return parts[0] if parts else "127.0.0.1"
    except Exception:
        return "127.0.0.1"


def detect_preflight() -> dict:
    ram_mb = 4096
    swap_mb = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    ram_mb = int(line.split()[1]) // 1024
                elif line.startswith("SwapTotal:"):
                    swap_mb = int(line.split()[1]) // 1024
    except OSError:
        pass
    docker_ok = subprocess.run(["docker", "version"], capture_output=True, timeout=10).returncode == 0
    git_ok = subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    hostname = "server"
    try:
        hostname = subprocess.check_output(["hostname"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        pass
    low_mem = ram_mb < 3500
    return {
        "public_ip": _public_ip(),
        "hostname": hostname,
        "ram_mb": ram_mb,
        "swap_mb": swap_mb,
        "low_memory": low_mem,
        "docker_installed": docker_ok,
        "git_installed": git_ok,
        "recommended_skip_node_build": low_mem,
    }


def _safe_static(rel: str) -> Path | None:
    candidate = (INSTALLER_DIR / rel.lstrip("/")).resolve()
    try:
        candidate.relative_to(INSTALLER_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


class WizardHandler(BaseHTTPRequestHandler):
    server_version = "ShahkarInstaller/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[installer] %s\n" % (fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/preflight":
            return self._json(200, detect_preflight())
        if route == "/api/progress":
            if PROGRESS_PATH and PROGRESS_PATH.is_file():
                try:
                    return self._json(200, json.loads(PROGRESS_PATH.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    pass
            return self._json(200, {"step": "waiting", "pct": 0, "msg": "", "done": False})
        if route in ("/", "/index.html"):
            return self._static(INSTALLER_DIR / "index.html", "text/html; charset=utf-8")
        ext = route.rsplit(".", 1)[-1].lower() if "." in route else ""
        mime = {
            "css": "text/css; charset=utf-8",
            "js": "application/javascript; charset=utf-8",
            "svg": "image/svg+xml",
            "png": "image/png",
            "woff2": "font/woff2",
        }.get(ext, "application/octet-stream")
        static = _safe_static(route)
        if static:
            return self._static(static, mime)
        self.send_error(404)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route != "/api/config":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return self._json(400, {"error": "Invalid JSON"})
        if not CONFIG_PATH:
            return self._json(500, {"error": "Config path not configured"})
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if PROGRESS_PATH:
            PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
            PROGRESS_PATH.write_text(
                json.dumps({"step": "queued", "pct": 2, "msg": "Install queued…", "done": False}),
                encoding="utf-8",
            )
        return self._json(200, {"ok": True})


def main() -> None:
    global CONFIG_PATH, PROGRESS_PATH
    parser = argparse.ArgumentParser(description="Shahkar web installer")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", required=True, help="Path to write install config JSON")
    parser.add_argument("--progress", required=True, help="Path for install progress JSON")
    args = parser.parse_args()
    CONFIG_PATH = Path(args.config)
    PROGRESS_PATH = Path(args.progress)

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), WizardHandler)
    print(f"Shahkar installer UI → http://0.0.0.0:{args.port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
