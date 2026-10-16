import contextlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state"
REGISTRY = "ghcr.io/nicolas-mgt/"
NAMESPACE = "ai-gateway"


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def ssh_command(command, options=()):
    values = {}
    for raw in (ROOT / ".env.ssh").read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            key, value = line.removeprefix("export ").split("=", 1)
            values[key.strip()] = shlex.split(value)[0]
    connection = shlex.split(values["CONN"])
    if connection[0] == "ssh":
        connection = connection[1:]
    STATE.mkdir(exist_ok=True, mode=0o700)
    args = ["ssh", "-o", "ConnectTimeout=12", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={STATE / 'known_hosts'}", *options, *connection, command]
    env = os.environ.copy()
    if values.get("PASS"):
        args = ["sshpass", "-e", *args]
        env["SSHPASS"] = values["PASS"]
    return args, env


def ssh(command, **kwargs):
    args, env = ssh_command(command)
    return run(args, env=env, **kwargs)


def remote(action, **values):
    source = (ROOT / "scripts/remote.py").read_text()
    return ssh("python3 -c " + shlex.quote(source),
               input=json.dumps({"action": action, **values}), capture_output=True).stdout.strip()


def manifest(name, images=None):
    text = (ROOT / f"k8s/{name}.json").read_text()
    for key, value in (images or {}).items():
        if not re.fullmatch(r"ghcr\.io/nicolas-mgt/code-assistant(?:-login)?@sha256:[0-9a-f]{64}", value):
            raise ValueError("Deployment requires an immutable GHCR image digest")
        text = text.replace("$" + key, value)
    return json.loads(text)


def image_state():
    return json.loads((STATE / "images.json").read_text())


def build():
    if run(["git", "status", "--porcelain"], capture_output=True).stdout.strip():
        raise ValueError("Commit changes before building images tagged with the commit ID")
    revision = run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.strip()
    for target, package in [("gateway", "code-assistant"), ("login", "code-assistant-login")]:
        run(["docker", "buildx", "build", "--platform", "linux/amd64", "--load",
             "--label", f"org.opencontainers.image.revision={revision}",
             "-f", f"docker/{target}.Dockerfile", "-t", f"{REGISTRY}{package}:{revision}", "."])
    STATE.mkdir(exist_ok=True, mode=0o700)
    (STATE / "build.json").write_text(json.dumps({"revision": revision}) + "\n")


def push():
    revision = json.loads((STATE / "build.json").read_text())["revision"]
    images = {}
    for key, package in [("GATEWAY_IMAGE", "code-assistant"), ("LOGIN_IMAGE", "code-assistant-login")]:
        tag = f"{REGISTRY}{package}:{revision}"
        run(["docker", "push", "--quiet", tag])
        result = run(["docker", "buildx", "imagetools", "inspect", tag], capture_output=True).stdout
        digest = re.search(r"^Digest:\s+(sha256:[a-f0-9]{64})$", result, re.MULTILINE)
        if not digest:
            raise ValueError(f"Registry did not return a digest for {package}")
        images[key] = f"{REGISTRY}{package}@{digest[1]}"
    (STATE / "images.json").write_text(json.dumps(images, indent=2) + "\n")
    print(json.dumps(images, indent=2))


def deploy():
    images = image_state()
    for key in images:
        if os.environ.get(key):
            images[key] = os.environ[key]
    data = json.dumps(manifest("gateway", images))
    ssh("kubectl apply --dry-run=server -f -", input=data)
    ssh("kubectl apply -f -", input=data)
    ssh("kubectl -n ai-gateway rollout status deployment/ai-gateway --timeout=240s")
    ssh("kubectl -n ai-gateway wait --for=condition=Ready certificate/ai-gateway-tls --timeout=180s")


@contextlib.contextmanager
def login_tunnel():
    command = "kubectl -n ai-gateway port-forward --address 127.0.0.1 pod/ai-login 33000:3000"
    args, env = ssh_command(command, ["-o", "ExitOnForwardFailure=yes", "-L", "127.0.0.1:33000:127.0.0.1:33000"])
    process = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Login SSH tunnel exited")
            try:
                with urllib.request.urlopen("http://127.0.0.1:33000/", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.3)
        else:
            raise RuntimeError("Login desktop did not become available")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def login():
    # Fail before creating a browser if another process owns the local tunnel port.
    with socket.socket() as check:
        check.bind(("127.0.0.1", 33000))
    ssh("kubectl -n ai-gateway create -f -", input=json.dumps(manifest("login", image_state())))
    try:
        ssh("kubectl -n ai-gateway wait --for=condition=Ready pod/ai-login --timeout=300s")
        with login_tunnel():
            print("Login desktop: http://127.0.0.1:33000/ — authenticate only inside the remote browser", flush=True)
            args, env = ssh_command("kubectl -n ai-gateway exec deployment/ai-gateway -- /CLIProxyAPI/CLIProxyAPI --config /etc/ai-gateway/config.json --codex-device-login --no-browser --local-model")
            with subprocess.Popen(args, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                succeeded = False
                for line in process.stdout:
                    # The upstream CLI also exits zero on some login failures.
                    if "device authentication successful!" in line:
                        succeeded = True
                    if "device code:" in line or "failed" in line.lower():
                        print(line.strip(), flush=True)
                status = process.wait()
            if status or not succeeded:
                raise RuntimeError("Authentication did not complete; existing credentials were preserved")
            print("Authentication completed; tokens are stored on the server")
    finally:
        ssh("kubectl -n ai-gateway delete pod ai-login --ignore-not-found --wait=false")


def smoke():
    key = remote("key")
    base = os.environ.get("SMOKE_URL", "http://127.0.0.1:8318").rstrip("/")
    public = base == "https://home.mmgt.dev/ca"
    paths = ("/m", "/r") if public else ("/models", "/responses")
    for auth in (None, "invalid"):
        request = urllib.request.Request(base + paths[0], headers={} if auth is None else {"Authorization": f"Bearer {auth}"})
        try:
            urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise RuntimeError(f"Expected 401, received {error.code}") from error
        else:
            raise RuntimeError("Unauthenticated request was accepted")
    request = urllib.request.Request(base + paths[0], headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        catalog = json.load(response)
    if "assistant" not in {entry["id"] for entry in catalog["data"]}:
        raise RuntimeError("Authenticated endpoint works; alias assistant is missing. Complete login and configure first")
    payload = {"model": "assistant", "input": "Reply with OK only.", "stream": True, "store": False}
    request = urllib.request.Request(base + paths[1], data=json.dumps(payload).encode(),
                                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    completed = False
    text_received = False
    with urllib.request.urlopen(request, timeout=120) as response:
        for line in response:
            if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                continue
            event = json.loads(line[6:])
            if event.get("type") in ("error", "response.failed", "response.incomplete"):
                raise RuntimeError(f"Generation failed: {event.get('type')}")
            text_received |= event.get("type") == "response.output_text.delta" and bool(event.get("delta"))
            completed |= event.get("type") == "response.completed"
    if not completed or not text_received:
        raise RuntimeError("Stream ended without text and successful completion")
    print("Authentication, catalog and streamed generation passed")


def main():
    os.chdir(ROOT)
    action = sys.argv[1]
    if action == "build":
        build()
    elif action == "push":
        push()
    elif action == "bootstrap":
        print(remote("bootstrap", manifest=manifest("bootstrap"),
                     config=json.loads((ROOT / "config/gateway.json").read_text()),
                     pull_secret_source=os.environ.get("PULL_SECRET_SOURCE")))
    elif action == "deploy":
        deploy()
    elif action == "client":
        env = os.environ.copy()
        env.update(AI_GATEWAY_UPSTREAM="https://home.mmgt.dev", AI_GATEWAY_PORT="8318",
                   AI_GATEWAY_NETWORK_PORT="8319")
        run(["caddy", "run", "--config", "client/Caddyfile", "--adapter", "caddyfile"], env=env)
    elif action == "login":
        login()
    elif action == "login-stop":
        ssh("kubectl -n ai-gateway delete pod ai-login --ignore-not-found --wait=false")
    elif action == "models":
        print(remote("models"))
    elif action == "configure":
        context, output = int(os.environ["CONTEXT"]), int(os.environ["OUTPUT"])
        if not 0 < output < context:
            raise ValueError("Require 0 < OUTPUT < CONTEXT")
        client = {"name": "assistant", "display_name": "Assistant", "reasoning_effort": "high", "max_tokens": context,
                  "max_output_tokens": output, "capabilities": {"tools": True, "images": True,
                  "parallel_tool_calls": True, "prompt_cache_key": False, "chat_completions": False}}
        payload_rules = json.loads((ROOT / "config/gateway.json").read_text())["requests"]["payload"]
        print(remote("configure", model=os.environ["MODEL"], client=client, payload_rules=payload_rules))
    elif action == "zed-config":
        model = json.loads(remote("client-model"))
        providers = {}
        for mode, port in [("Network", 8319), ("Remote", 8318)]:
            providers[f"AI Gateway {mode}"] = {
                "api_url": f"http://127.0.0.1:{port}",
                "available_models": [dict(model, display_name=f"assistant-{mode.lower()}", reasoning_effort="high")]}
        settings = {"language_models": {"openai_compatible": providers},
            "agent": {"default_model": {"provider": "AI Gateway Network", "model": "assistant",
                                        "enable_thinking": True, "effort": "high"}}}
        print(json.dumps(settings, indent=2))
    elif action == "key-copy":
        run(["pbcopy"], input=remote("key"))
        print("Gateway key copied. Paste it into AI Gateway credentials in Zed, then clear the clipboard.")
    elif action == "smoke":
        smoke()
    elif action == "status":
        ssh("kubectl -n ai-gateway get pods,deployments,services,pvc,certificates,ingressroutes")
        ssh("kubectl -n ai-gateway logs deployment/ai-gateway --tail=25")
    else:
        raise ValueError(f"Unknown command: {action}")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        print(f"Command failed (exit {error.returncode})", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
