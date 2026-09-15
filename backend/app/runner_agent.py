"""Pull-based remote runner agent for v14.

The default executor is `noop`. Set CC_RUNNER_EXECUTOR=local_process only on a machine
that is already an isolated disposable runner. This module is not a sandbox by itself.
"""
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
import httpx

API = os.getenv("CC_RUNNER_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
KEY = os.getenv("CC_RUNNER_API_KEY", "")
ORG = int(os.getenv("CC_RUNNER_ORG_ID", "1"))
POOL = int(os.getenv("CC_RUNNER_POOL_ID", "1"))
NODE_KEY = os.getenv("CC_RUNNER_NODE_KEY", "remote-runner-v14")
PROVIDER = os.getenv("CC_RUNNER_PROVIDER", "remote")
CAPS = [x.strip() for x in os.getenv("CC_RUNNER_CAPABILITIES", "linux").split(",") if x.strip()]
CAPACITY = max(1, int(os.getenv("CC_RUNNER_CAPACITY", "1")))
POLL = max(1.0, float(os.getenv("CC_RUNNER_POLL_SECONDS", "2")))
EXECUTOR = os.getenv("CC_RUNNER_EXECUTOR", "noop")
ALLOWED = {x.strip() for x in os.getenv("CC_RUNNER_ALLOWED_EXECUTABLES", "python,python3,pytest,node,npm").split(",") if x.strip()}
ROOT = Path(os.getenv("CC_RUNNER_WORK_ROOT", "./runner-work")).expanduser().resolve()
TIMEOUT = max(1, int(os.getenv("CC_RUNNER_COMMAND_TIMEOUT_SECONDS", "900")))
TRANSPORT = os.getenv("CC_RUNNER_TRANSPORT_VERSION", "v15").lower()
CLIENT_CERT = os.getenv("CC_RUNNER_CLIENT_CERT", "")
CLIENT_KEY = os.getenv("CC_RUNNER_CLIENT_KEY", "")
CA_BUNDLE = os.getenv("CC_RUNNER_CA_BUNDLE", "")


def headers():
    if not KEY:
        raise RuntimeError("CC_RUNNER_API_KEY is required")
    return {"X-API-Key": KEY, "Content-Type": "application/json"}


def register(client: httpx.Client) -> int:
    r = client.post(f"{API}/v14/runner-nodes/register", headers=headers(), json={
        "organization_id": ORG, "pool_id": POOL, "node_key": NODE_KEY, "provider": PROVIDER,
        "endpoint": f"pull://{NODE_KEY}", "capabilities": CAPS, "labels": {"executor": EXECUTOR}, "capacity": CAPACITY,
    }); r.raise_for_status(); return int(r.json()["id"])


def heartbeat(client: httpx.Client, node_id: int):
    if TRANSPORT == "v15":
        r = client.post(f"{API}/v15/runner/{node_id}/heartbeat", headers=headers())
    else:
        r = client.post(f"{API}/v14/runner-nodes/{node_id}/heartbeat", headers=headers(), json={"status":"online","capabilities":CAPS})
    r.raise_for_status()


def execute(job: dict) -> tuple[dict, str]:
    payload = json.loads(job.get("payload_json") or "{}")
    if EXECUTOR == "noop":
        return {"executor":"noop","accepted":True,"payload_keys":sorted(payload.keys())}, ""
    if EXECUTOR != "local_process":
        return {}, f"Unsupported runner executor: {EXECUTOR}"
    argv = payload.get("argv") or []
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        return {}, "payload.argv must be a non-empty string array"
    if Path(argv[0]).name not in ALLOWED:
        return {}, f"Executable is not allowlisted: {argv[0]}"
    rel = str(payload.get("cwd") or ".")
    cwd = (ROOT / rel).resolve()
    if cwd != ROOT and ROOT not in cwd.parents:
        return {}, "Working directory escapes runner root"
    cwd.mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.getenv("PATH", ""), "HOME": str(ROOT), "LANG": "C.UTF-8"}
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, shell=False, capture_output=True, text=True, timeout=TIMEOUT)
        return {"exit_code":p.returncode,"stdout":p.stdout[-20000:],"stderr":p.stderr[-20000:]}, "" if p.returncode == 0 else f"exit_code={p.returncode}"
    except Exception as exc:
        return {}, str(exc)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    client_kwargs = {"timeout": 20}
    if CLIENT_CERT and CLIENT_KEY:
        client_kwargs["cert"] = (CLIENT_CERT, CLIENT_KEY)
    if CA_BUNDLE:
        client_kwargs["verify"] = CA_BUNDLE
    with httpx.Client(**client_kwargs) as client:
        node_id = register(client); last_hb = 0.0
        print(f"ClawCompany runner {NODE_KEY} registered as node #{node_id}; executor={EXECUTOR}", flush=True)
        while True:
            now = time.time()
            if now - last_hb > 15:
                heartbeat(client, node_id); last_hb = now
            if TRANSPORT == "v15":
                r = client.get(f"{API}/v15/runner/{node_id}/jobs/next", headers=headers())
            else:
                r = client.get(f"{API}/v14/runner-jobs/next", params={"node_id":node_id}, headers=headers())
            r.raise_for_status()
            job = r.json()
            if not job:
                time.sleep(POLL); continue
            result, error = execute(job)
            if TRANSPORT == "v15":
                done = client.post(f"{API}/v15/runner/{node_id}/jobs/{job['id']}/complete", headers=headers(), json={"result":result,"error":error})
            else:
                done = client.post(f"{API}/v14/runner-jobs/{job['id']}/complete", headers=headers(), json={"result":result,"error":error})
            done.raise_for_status()


if __name__ == "__main__":
    main()
