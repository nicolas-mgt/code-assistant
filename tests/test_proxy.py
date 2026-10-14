import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.do_POST()

    def do_POST(self):
        self.server.requests.append(self.path)
        mode = parse_qs(urlsplit(self.path).query).get("mode", [""])[0]
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(429 if mode == "error" else 200)
        self.send_header("Content-Type", "text/event-stream" if mode == "stream" else "application/json")
        if mode == "error":
            self.send_header("Retry-After", "12")
        self.end_headers()
        if mode == "stream":
            try:
                while True:
                    self.wfile.write(b'data: {"delta":"hello"}\n\n')
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                self.server.cancelled.set()
        else:
            self.wfile.write(json.dumps({"path": self.path, "method": self.command,
                "body": body.decode(), "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type")}).encode())


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        cls.backend.requests = []
        cls.backend.cancelled = threading.Event()
        cls.thread = threading.Thread(target=cls.backend.serve_forever, daemon=True)
        cls.thread.start()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = dict(os.environ, AI_GATEWAY_UPSTREAM=f"http://127.0.0.1:{cls.backend.server_port}",
                   AI_GATEWAY_PORT=str(cls.port))
        cls.log = tempfile.TemporaryFile()
        cls.proxy = subprocess.Popen(["caddy", "run", "--config", str(ROOT / "client/Caddyfile"),
                                      "--adapter", "caddyfile"], env=env, stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.05)
        cls.tearDownClass()
        raise RuntimeError("Caddy did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proxy.terminate()
        cls.proxy.wait(timeout=10)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.log.close()

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers={
            "Authorization": "Bearer test-gateway-key", "Content-Type": "application/json"})
        return connection, connection.getresponse()

    def test_routes_preserve_request(self):
        for method, path, expected in [("GET", "/models", "/ca/m"),
                ("POST", "/chat/completions", "/ca/c/c"), ("POST", "/responses", "/ca/r")]:
            with self.subTest(path=path):
                body = None if method == "GET" else '{"input":"zażółć","stream":true}'
                encoded = body.encode() if body else None
                conn, response = self.request(method, path + "?tag=a%2Fb&tag=c", encoded)
                self.assertEqual(response.status, 200)
                echoed = json.load(response)
                self.assertEqual(echoed["path"], expected + "?tag=a%2Fb&tag=c")
                self.assertEqual(echoed["method"], method)
                self.assertEqual(echoed["body"], body or "")
                self.assertEqual(echoed["authorization"], "Bearer test-gateway-key")
                self.assertEqual(echoed["content_type"], "application/json")
                conn.close()

    def test_unknown_paths_and_methods_are_not_forwarded(self):
        before = len(self.backend.requests)
        for method, path in [("GET", "/responses"), ("POST", "/models"), ("GET", "/v0/management"),
                             ("POST", "/responses/compact"), ("GET", "/models/"), ("GET", "/anything")]:
            conn, response = self.request(method, path)
            self.assertEqual(response.status, 404)
            response.read()
            conn.close()
        self.assertEqual(len(self.backend.requests), before)

    def test_provider_error_is_preserved(self):
        conn, response = self.request("POST", "/responses?mode=error", b"{}")
        self.assertEqual(response.status, 429)
        self.assertEqual(response.getheader("Retry-After"), "12")
        self.assertEqual(json.load(response)["path"], "/ca/r?mode=error")
        conn.close()

    def test_stream_arrives_before_completion_and_cancels(self):
        self.backend.cancelled.clear()
        started = time.monotonic()
        conn, response = self.request("POST", "/responses?mode=stream", b"{}")
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
        self.assertEqual(response.readline(), b'data: {"delta":"hello"}\n')
        self.assertLess(time.monotonic() - started, 2)
        response.close()
        conn.close()
        self.assertTrue(self.backend.cancelled.wait(5), "Upstream kept running after client cancellation")

    def test_ingress_maps_to_backend_paths(self):
        resources = json.loads((ROOT / "k8s/gateway.json").read_text())["items"]
        middleware = {item["metadata"]["name"]: item["spec"]["replacePath"]["path"]
                      for item in resources if item["kind"] == "Middleware"}
        ingress = next(item for item in resources if item["kind"] == "IngressRoute")
        expected = {"/ca/m": ("GET", "/v1/models"), "/ca/c/c": ("POST", "/v1/chat/completions"),
                    "/ca/r": ("POST", "/v1/responses")}
        self.assertEqual(len(ingress["spec"]["routes"]), len(expected))
        for route in ingress["spec"]["routes"]:
            path = next(path for path in expected if f"Path(`{path}`)" in route["match"])
            method, target = expected[path]
            self.assertIn(f"Method(`{method}`)", route["match"])
            self.assertIn("Host(`home.mmgt.dev`)", route["match"])
            self.assertEqual(middleware[route["middlewares"][0]["name"]], target)


if __name__ == "__main__":
    unittest.main()
