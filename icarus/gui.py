"""Embedded HTTP server and desktop window launcher for Icarus GUI.

Serves the modern responsive HTML5/CSS/JS frontend over stdlib http.server
and provides REST API endpoints for status, config, buttons, and macros.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import os
import shutil
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from icarus import bkm
from icarus.config import VALID_DPIS, RgbEffect
from icarus.fileconfig import (
    CONFIG_FILE,
    apply_to_mouse,
    load_config_file,
    mouse_to_dict,
    pull_from_mouse,
    save_config_file,
)
from icarus.gui_macros import (
    flash_macro_to_device,
    handle_button_bind,
    load_macros,
    save_single_macro,
)
from icarus.hidraw import DeviceNotFoundError
from icarus.protocol import Device
from icarus.scroll import get_scroll_factor, set_scroll_factor

WEB_DIR = Path(__file__).parent / "web"

PIN_DATA = {
    "K1": {"name": "Left Click", "x": 70, "y": 97, "desc": "Primary Left Switch"},
    "K2": {"name": "Right Click", "x": 170, "y": 97, "desc": "Primary Right Switch"},
    "K3": {"name": "Middle Click", "x": 119, "y": 126, "desc": "Scroll Wheel Click"},
    "K4": {"name": "Forward (Front Thumb)", "x": 50, "y": 219, "desc": "Front Thumb Button"},
    "K5": {"name": "Back (Rear Thumb)", "x": 55, "y": 275, "desc": "Rear Thumb Button"},
    "K6": {"name": "DPI +", "x": 132, "y": 166, "desc": "DPI Increment"},
    "K7": {"name": "DPI -", "x": 138, "y": 207, "desc": "DPI Decrement"},
    "K8": {"name": "Fire Key", "x": 25, "y": 186, "desc": "Rapid Fire Burst"},
    "K9": {"name": "Sniper / DPI Lock", "x": 11, "y": 260, "desc": "Sniper Paddle"},
}

RGB_MODES = [e.name for e in RgbEffect]


def safe_get_data(package: str, resource: str) -> bytes | None:
    try:
        import pkgutil

        return pkgutil.get_data(package, resource)
    except (OSError, KeyError):
        return None


class IcarusRequestHandler(BaseHTTPRequestHandler):
    dev: Device | None = None

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[0]).startswith("GET /assets/"):
            return
        super().log_message(format, *args)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._serve_asset("index.html", "text/html; charset=utf-8")
        elif path.startswith("/assets/"):
            self._serve_asset(path[len("/assets/") :])
        elif path == "/api/status":
            self._handle_api_status()
        elif path == "/api/config":
            self._handle_api_config()
        elif path == "/api/macros":
            self._send_json({"macros": load_macros()})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        clen = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(clen) if clen > 0 else b""
        req: dict[str, Any] = {}
        if body and body.strip():
            try:
                parsed = json.loads(body.decode("utf-8"))
                if not isinstance(parsed, dict):
                    self._send_json({"success": False, "error": "Malformed JSON body"}, status=400)
                    return
                req = parsed
            except Exception:
                self._send_json({"success": False, "error": "Malformed JSON body"}, status=400)
                return

        dispatch = {
            "/api/switch-profile": lambda: self._handle_switch_profile(req),
            "/api/set": lambda: self._handle_set_config(req),
            "/api/config": lambda: self._handle_set_config(req),
            "/api/bind": lambda: self._handle_bind(req),
            "/api/macros": lambda: self._handle_save_macro(req),
            "/api/macros/flash": lambda: self._handle_flash_macro(req),
            "/api/import-bkm": lambda: self._handle_import_bkm(req),
            "/api/scroll": lambda: self._handle_scroll(req),
            "/api/pull": self._handle_pull,
            "/api/apply": self._handle_apply,
            "/api/exit": self._handle_exit,
        }

        handler = dispatch.get(path)
        if handler:
            handler()
        elif path.startswith("/api/macros/slot/"):
            try:
                req["id"] = int(path.split("/")[-1])
                self._handle_flash_macro(req)
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid slot ID")
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_asset(self, filename: str, content_type: str | None = None) -> None:
        safe_name = os.path.basename(filename)
        file_path = WEB_DIR / safe_name
        if not file_path.is_file():
            file_path = WEB_DIR / "assets" / safe_name

        data = (
            file_path.read_bytes()
            if file_path.is_file()
            else (safe_get_data("icarus.web", safe_name) or safe_get_data("icarus.web", f"assets/{safe_name}"))
        )
        if not data:
            self.send_error(HTTPStatus.NOT_FOUND, f"Asset not found: {filename}")
            return

        if not content_type:
            content_type, _ = mimetypes.guess_type(safe_name)
            content_type = content_type or "application/octet-stream"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _get_device(self) -> Device | None:
        if self.dev:
            return self.dev
        try:
            self.dev = Device.open()
            return self.dev
        except DeviceNotFoundError:
            return None

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        out = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _handle_api_status(self) -> None:
        dev = self._get_device()
        meta = {"valid_dpis": list(VALID_DPIS), "rgb_modes": RGB_MODES, "pins": PIN_DATA}
        if not dev:
            self._send_json({"connected": False, "device_path": "", "firmware": "", "config": {}, **meta})
            return
        try:
            fw = dev.read_psd()
            cfg_dict = mouse_to_dict(dev)
            dev_path = str(getattr(dev.io, "path", "/dev/hidraw"))
            self._send_json(
                {
                    "connected": True,
                    "device_path": dev_path,
                    "firmware": fw,
                    "config": cfg_dict,
                    **meta,
                }
            )
        except Exception as e:
            if self.dev and hasattr(self.dev, "io") and hasattr(self.dev.io, "close"):
                try:
                    self.dev.io.close()
                except Exception:
                    pass
            self.dev = None
            self._send_json({"connected": False, "error": str(e), **meta})

    def _handle_api_config(self) -> None:
        dev = self._get_device()
        meta = {"valid_dpis": list(VALID_DPIS), "rgb_modes": RGB_MODES, "pins": PIN_DATA}
        if not dev:
            try:
                cfg = load_config_file()
                self._send_json({"config": cfg, **meta})
            except Exception:
                self._send_json({"config": {}, **meta})
            return
        try:
            cfg = mouse_to_dict(dev)
            self._send_json({"config": cfg, **meta})
        except Exception as e:
            self._send_json({"error": str(e), **meta}, status=500)

    def _handle_switch_profile(self, req: dict[str, Any]) -> None:
        try:
            p = int(req.get("profile", 1))
            if p not in (1, 2, 3):
                raise ValueError
        except (ValueError, TypeError):
            self._send_json({"success": False, "error": "Invalid profile ID (must be 1..3)"}, status=400)
            return
        dev = self._get_device()
        if not dev:
            self._send_json({"success": False, "error": "No device"}, status=400)
            return
        try:
            dev.set_active_profile(p)
            self._send_json({"success": True, "active_profile": p})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_set_config(self, req: dict[str, Any]) -> None:
        dev = self._get_device()
        if not dev:
            self._send_json({"success": False, "error": "No device"}, status=400)
            return
        try:
            save_config_file(req)
            logs = apply_to_mouse(dev, CONFIG_FILE)
            self._send_json({"success": True, "logs": logs})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_bind(self, req: dict[str, Any]) -> None:
        dev = self._get_device()
        if not dev:
            self._send_json({"success": False, "error": "No device"}, status=400)
            return
        try:
            res = handle_button_bind(dev, req)
            self._send_json(res)
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_save_macro(self, req: dict[str, Any]) -> None:
        try:
            saved = save_single_macro(req)
            self._send_json({"success": True, "macro": saved})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_flash_macro(self, req: dict[str, Any]) -> None:
        dev = self._get_device()
        if not dev:
            self._send_json({"success": False, "error": "No device"}, status=400)
            return
        try:
            macro_data = req.get("macro")
            if not macro_data:
                slot_id = int(req.get("id", req.get("slot", 1)))
                macros = load_macros()
                macro_data = next((m for m in macros if m.get("id") == slot_id), None)
            if not macro_data:
                self._send_json({"success": False, "error": "Macro not found"}, status=400)
                return
            count = flash_macro_to_device(dev, macro_data)
            self._send_json({"success": True, "slot": macro_data.get("id"), "event_count": count})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_import_bkm(self, req: dict[str, Any]) -> None:
        try:
            p = int(req.get("profile", 1))
            if p not in (1, 2, 3):
                self._send_json({"success": False, "error": "Invalid profile ID (must be 1..3)"}, status=400)
                return
            fpath, b64 = req.get("path"), req.get("data_b64")
            data = Path(fpath).read_bytes() if fpath and Path(fpath).is_file() else (base64.b64decode(b64) if b64 else None)
            if not data:
                self._send_json({"success": False, "error": "No data"}, status=400)
                return
            bkm_prof = bkm.parse_bkm(data)
        except (ValueError, binascii.Error, TypeError, OSError) as e:
            self._send_json({"success": False, "error": f"Invalid BKM input: {e}"}, status=400)
            return

        dev = self._get_device()
        if not dev:
            self._send_json({"success": False, "error": "No device"}, status=400)
            return
        try:
            logs = bkm.import_bkm_to_mouse(dev, bkm_prof, target_profile=p)
            self._send_json({"success": True, "profile": p, "macro_count": len(bkm_prof.macros), "logs": logs})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_pull(self) -> None:
        dev = self._get_device()
        if not dev:
            self._send_json({"success": False, "error": "No device"}, status=400)
            return
        try:
            self._send_json({"success": True, "path": str(pull_from_mouse(dev))})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_apply(self) -> None:
        dev = self._get_device()
        if not dev:
            self._send_json({"success": False, "error": "No device"}, status=400)
            return
        try:
            self._send_json({"success": True, "logs": apply_to_mouse(dev)})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_scroll(self, req: dict[str, Any]) -> None:
        try:
            f = float(req.get("factor", 1.0))
            set_scroll_factor(f)
            self._send_json({"success": True, "scroll_factor": get_scroll_factor()})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=400)

    def _handle_exit(self) -> None:
        self._send_json({"success": True})
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def find_browser_command(url: str) -> list[str] | None:
    profile_dir = Path.home() / ".cache" / "icarus" / "browser"
    profile_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        "brave",
        "brave-browser",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
    ]
    for b in candidates:
        path = shutil.which(b)
        if path:
            return [path, f"--app={url}", f"--user-data-dir={profile_dir}", "--window-size=1120,740", "--class=icarus"]
    return ["xdg-open", url] if shutil.which("xdg-open") else None


def run_gui(host: str = "127.0.0.1", port: int = 8421, open_browser: bool = True) -> None:
    try:
        server = ThreadingHTTPServer((host, port), IcarusRequestHandler)
    except OSError:
        server = ThreadingHTTPServer((host, 0), IcarusRequestHandler)
        port = server.server_port

    url = f"http://{host}:{port}/"
    print(f"Icarus Web GUI listening at {url}")
    print("Press Ctrl+C to stop.")

    if open_browser:
        cmd = find_browser_command(url)
        if cmd:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"Warning: could not launch browser ({e}), open {url} manually")
        else:
            import webbrowser

            webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nIcarus GUI stopped")
