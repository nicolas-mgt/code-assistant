import base64
import json
import secrets
import subprocess
import sys
import urllib.error
import urllib.request

NAMESPACE = "ai-gateway"


def kubectl(*args, data=None, quiet=False):
    result = subprocess.run(
        ["kubectl", "-n", NAMESPACE, *args],
        input=json.dumps(data) if data is not None else None,
        text=True, capture_output=True,
    )
    if result.returncode:
        # kubectl errors can include an entire Secret submitted on stdin.
        raise RuntimeError(f"kubectl {args[0]} failed" + ("; secret payload withheld" if quiet else f": {result.stderr}"))
    return result.stdout


def get(kind, name):
    value = kubectl("get", kind, name, "--ignore-not-found", "-o", "json")
    return json.loads(value) if value.strip() else None


def secret(name, values):
    return {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": NAMESPACE},
            "type": "Opaque", "stringData": values}


def config():
    value = get("secret", "ai-gateway-config")
    if value is None:
        raise RuntimeError("Run make bootstrap first")
    return json.loads(base64.b64decode(value["data"]["config.json"]))


def save_config(value):
    kubectl("apply", "--server-side", "--field-manager=code-assistant", "-f", "-",
            data=secret("ai-gateway-config", {"config.json": json.dumps(value)}), quiet=True)


def api(path, payload=None):
    address = get("service", "ai-gateway")["spec"]["clusterIP"]
    key = config()["access"]["api-keys"][0]
    request = urllib.request.Request(
        f"http://{address}:8317/v1/{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def bootstrap(request):
    kubectl("apply", "-f", "-", data=request["manifest"])
    if not get("secret", "ghcr-pull"):
        source = request.get("pull_secret_source")
        if not source:
            raise RuntimeError("Set PULL_SECRET_SOURCE=namespace/name to reuse a server-side registry credential")
        source_namespace, source_name = source.split("/", 1)
        original = json.loads(kubectl("get", "secret", source_name, "-n", source_namespace, "-o", "json", quiet=True))
        if original["type"] != "kubernetes.io/dockerconfigjson":
            raise RuntimeError("Source is not a registry pull secret")
        pull = {"apiVersion": "v1", "kind": "Secret",
                "metadata": {"name": "ghcr-pull", "namespace": NAMESPACE},
                "type": original["type"], "data": original["data"]}
        kubectl("create", "-f", "-", data=pull, quiet=True)
    if not get("secret", "ai-gateway-config"):
        value = request["config"]
        value["access"]["api-keys"] = [secrets.token_urlsafe(32)]
        save_config(value)
    print("Bootstrap complete; existing keys and persistent data preserved")


def configure(request):
    model = request["model"]
    available = {entry["id"] for entry in api("models")["data"]}
    value = config()
    old = value["oauth"].get("model-alias", {}).get("codex", [])
    available.update(entry["name"] for entry in old)
    if model not in available:
        raise RuntimeError("Model is not in the authenticated catalog; run make models")
    value["oauth"]["model-alias"] = {"codex": [
        {"name": model, "alias": "assistant", "fork": False, "force-mapping": True}
    ]}
    value.setdefault("requests", {})["payload"] = request["payload_rules"]
    save_config(value)
    client = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "ai-gateway-client", "namespace": NAMESPACE},
              "data": {"model.json": json.dumps(request["client"])}}
    kubectl("apply", "-f", "-", data=client)
    kubectl("rollout", "restart", "deployment/ai-gateway")
    print(kubectl("rollout", "status", "deployment/ai-gateway", "--timeout=180s").strip())


def main():
    request = json.load(sys.stdin)
    action = request["action"]
    if action == "bootstrap":
        bootstrap(request)
    elif action == "configure":
        configure(request)
    elif action == "key":
        print(config()["access"]["api-keys"][0])
    elif action == "models":
        print(json.dumps(api("models"), indent=2))
    elif action == "client-model":
        value = get("configmap", "ai-gateway-client")
        if not value:
            raise RuntimeError("Run make configure MODEL=... CONTEXT=... OUTPUT=... first")
        print(value["data"]["model.json"])
    else:
        raise RuntimeError(f"Unknown action: {action}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, urllib.error.URLError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
