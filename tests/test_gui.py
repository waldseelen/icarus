"""Unit tests for Icarus GUI HTTP server and REST handlers."""

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from icarus.gui import IcarusRequestHandler
from icarus.protocol import Device


class DummyTransport:
    def __init__(self) -> None:
        self.path = "/dev/hidraw_dummy"
        self.last_cmd = 0x01
        self.features: dict[int, bytearray] = {}
        for p in (1, 2):
            for b in (1, 2):
                cmd = (p << 4) | b
                f = Path(__file__).parent / "data" / f"p{p}_b{b}.bin"
                if f.is_file():
                    self.features[cmd] = bytearray(f.read_bytes())

    def set_feature(self, data: bytes) -> None:
        if len(data) >= 2 and data[0] == 0x05:
            self.last_cmd = data[1]
        elif len(data) >= 2 and data[0] == 0x04:
            self.features[data[1]] = bytearray(data)

    def get_feature(self, report_id: int, size: int) -> bytearray:
        if report_id == 0x05:
            res = bytearray(size)
            res[0] = 0x05
            res[1] = self.last_cmd
            if self.last_cmd == 0x01:
                res[2:6] = b"V901"
            elif self.last_cmd == 0x02:
                res[2] = 0x01
            return res
        if report_id == 0x04:
            if self.last_cmd in self.features:
                return bytearray(self.features[self.last_cmd])
        return bytearray(size)


class TestGuiServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        IcarusRequestHandler.dev = None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), IcarusRequestHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        IcarusRequestHandler.dev = None
        cls.server.shutdown()
        cls.server.server_close()

    def tearDown(self) -> None:
        IcarusRequestHandler.dev = None

    def test_serve_index(self) -> None:
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("GAMEPOWER ICARUS", body)
            self.assertIn("tab-buttons", body)

    def test_serve_style(self) -> None:
        url = f"http://127.0.0.1:{self.port}/assets/style.css"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "text/css")

    def test_serve_macro_assets(self) -> None:
        for asset in ("macro.css", "macro.js"):
            url = f"http://127.0.0.1:{self.port}/assets/{asset}"
            with urllib.request.urlopen(url) as resp:
                self.assertEqual(resp.status, 200)
                ctype = resp.headers.get("Content-Type", "")
                self.assertTrue("css" in ctype or "javascript" in ctype)

    def test_serve_js(self) -> None:
        url = f"http://127.0.0.1:{self.port}/assets/app.js"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("renderPins", body)

    def test_serve_icon(self) -> None:
        url = f"http://127.0.0.1:{self.port}/assets/icon.png"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "image/png")
            data = resp.read()
            self.assertTrue(len(data) > 1000)

    def test_api_status_metadata(self) -> None:
        url = f"http://127.0.0.1:{self.port}/api/status"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("valid_dpis", data)
            self.assertEqual(len(data["valid_dpis"]), 57)
            self.assertIn("rgb_modes", data)
            self.assertEqual(len(data["rgb_modes"]), 11)
            self.assertIn("pins", data)
            self.assertIn("K4", data["pins"])
            self.assertIn("K5", data["pins"])

    def test_api_macros_endpoints(self) -> None:
        url = f"http://127.0.0.1:{self.port}/api/macros"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("macros", data)
            self.assertEqual(len(data["macros"]), 16)

        new_macro = {
            "id": 1,
            "name": "Rapid Burst Click",
            "loop_mode": "UNTIL_RELEASE",
            "repeat_count": 1,
            "events": [
                {"action": "BTN_DOWN", "code": "LEFT", "delay_ms": 15},
                {"action": "BTN_UP", "code": "LEFT", "delay_ms": 25},
            ],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(new_macro).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res.get("success"))
            self.assertEqual(res["macro"]["name"], "Rapid Burst Click")

    def test_api_bind_and_flash_with_mock_device(self) -> None:
        mock_dev = Device(DummyTransport())
        IcarusRequestHandler.dev = mock_dev

        # Test POST /api/bind for K8 Fire key
        bind_url = f"http://127.0.0.1:{self.port}/api/bind"
        bind_payload = {
            "profile": 1,
            "button": "K8",
            "action": "fire",
            "repeat": 5,
            "interval_ms": 20,
        }
        req = urllib.request.Request(
            bind_url,
            data=json.dumps(bind_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res.get("success"))
            self.assertIn("Fire Key", res.get("summary", ""))

        # Test POST /api/macros/flash
        flash_url = f"http://127.0.0.1:{self.port}/api/macros/flash"
        flash_payload = {
            "id": 1,
            "macro": {
                "id": 1,
                "name": "Flash Test",
                "events": [{"action": "KEY_DOWN", "code": "a", "delay_ms": 10}],
            },
        }
        req2 = urllib.request.Request(
            flash_url,
            data=json.dumps(flash_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2) as resp:
            self.assertEqual(resp.status, 200)
            res2 = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res2.get("success"))
            self.assertEqual(res2.get("event_count"), 1)


if __name__ == "__main__":
    unittest.main()
