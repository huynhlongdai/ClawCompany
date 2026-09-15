from app.models import SandboxProfile


PROVIDERS = {
    "mock": {
        "isolation": "simulation",
        "ephemeral": True,
        "network_policy": True,
        "secrets_mount": True,
        "production_ready": False,
        "notes": "Deterministic control-plane simulation only.",
    },
    "docker": {
        "isolation": "container",
        "ephemeral": True,
        "network_policy": True,
        "secrets_mount": True,
        "production_ready": False,
        "notes": "Local container adapter; do not expose Docker socket to the API container.",
    },
    "kubernetes": {
        "isolation": "pod",
        "ephemeral": True,
        "network_policy": True,
        "secrets_mount": True,
        "production_ready": False,
        "notes": "Control-plane contract exists; cluster adapter must be configured separately.",
    },
    "microvm": {
        "isolation": "microvm",
        "ephemeral": True,
        "network_policy": True,
        "secrets_mount": True,
        "production_ready": False,
        "notes": "Provider-neutral contract for Firecracker/Cloud Hypervisor runners; no privileged host runner is bundled.",
    },
}


def providers() -> list[dict]:
    return [{"provider": name, **caps} for name, caps in PROVIDERS.items()]


def describe_profile(profile: SandboxProfile) -> dict:
    base = PROVIDERS.get(profile.provider, {"isolation": "unknown", "production_ready": False})
    return {
        "provider": profile.provider,
        **base,
        "limits": {"cpu": profile.cpu_limit, "memory_mb": profile.memory_mb, "pids": profile.pids_limit,
                   "timeout_seconds": profile.timeout_seconds},
        "network_mode": profile.network_mode,
        "read_only_root": profile.read_only_root,
    }
