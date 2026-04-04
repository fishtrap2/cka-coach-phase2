import json
import platform
import shutil
import subprocess
from typing import Dict, Any


def _run_command(command: str) -> str:
    """
    Run a shell command and return stdout as text.

    Design goals:
    - never raise to the caller
    - return stderr text if useful
    - keep collection resilient even if some tools are missing

    This makes the collector safe for student lab environments where
    some commands may not exist or RBAC may be incomplete.
    """
    try:
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()

        if stdout:
            return stdout

        if stderr:
            return stderr

        return ""
    except Exception as exc:
        return f"collector error: {exc}"


def _command_exists(name: str) -> bool:
    """
    Check whether a command exists on PATH.
    """
    return shutil.which(name) is not None


def _safe_kubectl(command: str) -> str:
    """
    Run a kubectl command only if kubectl exists.

    Why:
    - avoids confusing 'command not found' noise
    - keeps the returned state cleaner for ELS mapping
    """
    if not _command_exists("kubectl"):
        return "kubectl not installed or not on PATH"
    return _run_command(command)


def _safe_systemctl(service_name: str) -> str:
    """
    Run systemctl status only if systemctl exists.
    """
    if not _command_exists("systemctl"):
        return "systemctl not available on this host"
    return _run_command(f"systemctl status {service_name} --no-pager")


def _safe_journalctl(service_name: str, lines: int = 50) -> str:
    """
    Return recent logs from journald for a service if available.
    """
    if not _command_exists("journalctl"):
        return "journalctl not available on this host"
    return _run_command(f"journalctl -u {service_name} -n {lines} --no-pager")


def _safe_crictl(command: str) -> str:
    """
    Run a crictl command only if crictl exists.
    """
    if not _command_exists("crictl"):
        return "crictl not installed or not on PATH"
    return _run_command(command)


def _safe_ip(command: str) -> str:
    """
    Run ip command only if available.
    """
    if not _command_exists("ip"):
        return "ip command not installed or not on PATH"
    return _run_command(command)


def _safe_uname() -> str:
    """
    Return kernel information.
    """
    return _run_command("uname -r")


def _safe_runc_version() -> str:
    """
    Return runc version if available.
    """
    if not _command_exists("runc"):
        return "runc not installed or not on PATH"
    return _run_command("runc --version")


def _safe_containerd_version() -> str:
    """
    Try to get containerd version from the binary if available.
    """
    if not _command_exists("containerd"):
        return "containerd binary not installed or not on PATH"
    return _run_command("containerd --version")


def _safe_kubelet_version() -> str:
    """
    Try to get kubelet version if available.
    """
    if not _command_exists("kubelet"):
        return "kubelet binary not installed or not on PATH"
    return _run_command("kubelet --version")


def _safe_kubectl_version_json() -> str:
    """
    Get Kubernetes client/server version JSON if possible.

    This is useful because:
    - dashboard uses k8s_json in expand views
    - agent uses it as API/object evidence
    """
    return _safe_kubectl("kubectl version -o json")


def _safe_kubectl_version_short() -> str:
    """
    Get a compact kubectl version view.
    """
    return _safe_kubectl("kubectl version")


def _detect_cni_name() -> str:
    """
    Best-effort detection of CNI config from /etc/cni/net.d.

    This is a lightweight heuristic, not a full parser.
    """
    if not _command_exists("ls"):
        return "unknown"

    listing = _run_command("ls /etc/cni/net.d/ 2>/dev/null")
    if not listing:
        return "unknown"

    lower = listing.lower()

    # Common CNIs / patterns
    if "cilium" in lower:
        return "cilium"
    if "calico" in lower:
        return "calico"
    if "flannel" in lower:
        return "flannel"
    if "weave" in lower:
        return "weave"
    if "10-" in lower or ".conf" in lower or ".conflist" in lower:
        return listing.splitlines()[0]

    return "unknown"


def _health_flags(runtime: Dict[str, str]) -> Dict[str, Any]:
    """
    Derive a few coarse health flags from collected runtime text.

    These are intentionally simple and student-friendly.
    """
    pods_text = runtime.get("pods", "")
    kubelet_text = runtime.get("kubelet", "")
    containerd_text = runtime.get("containerd", "")

    pods_pending = "Pending" in pods_text
    pods_crashloop = "CrashLoopBackOff" in pods_text

    kubelet_ok = not any(
        bad in kubelet_text.lower()
        for bad in [
            "inactive",
            "failed",
            "could not be found",
            "not found",
        ]
    )

    containerd_ok = not any(
        bad in containerd_text.lower()
        for bad in [
            "inactive",
            "failed",
            "could not be found",
            "not found",
        ]
    )

    return {
        "pods_pending": pods_pending,
        "pods_crashloop": pods_crashloop,
        "kubelet_ok": kubelet_ok,
        "containerd_ok": containerd_ok,
    }


def collect_state() -> Dict[str, Any]:
    """
    Collect structured state for cka-coach.

    Returned shape:
    {
      "runtime": {...},
      "versions": {...},
      "health": {...}
    }

    This shape is intentionally shared across:
    - dashboard.py
    - agent.py
    - main.py

    So this is now the main evidence collection contract for Phase 1.
    """

    # --------------------------
    # Runtime evidence
    # --------------------------
    # These fields are meant to capture "what is happening now" across
    # Kubernetes, node agents, networking, and container runtime.
    runtime = {
        # Pod-level view for L8 application_pods
        "pods": _safe_kubectl("kubectl get pods -A -o wide"),

        # Event / object-level clues for L7 and L5
        "events": _safe_kubectl("kubectl get events -A --sort-by=.lastTimestamp"),

        # Node view is useful for scheduler/controller and node/network questions
        "nodes": _safe_kubectl("kubectl get nodes -o wide"),

        # kubelet belongs primarily to the node_agents_and_networking layer
        "kubelet": _safe_systemctl("kubelet"),

        # container runtime service view
        "containerd": _safe_systemctl("containerd"),

        # container listing from CRI
        "containers": _safe_crictl("crictl ps -a"),

        # generic process inventory used as approximate evidence for lower layers
        "processes": _run_command("ps aux | head -n 80"),

        # network interfaces and addressing
        "network": _safe_ip("ip addr"),

        # routing table
        "routes": _safe_ip("ip route"),
    }

    # --------------------------
    # Version / identity evidence
    # --------------------------
    # These fields are slower-changing metadata that help place the cluster
    # in context and populate table version columns.
    versions = {
        "api": _safe_kubectl_version_short(),
        "k8s_json": _safe_kubectl_version_json(),
        "kernel": _safe_uname(),
        "containerd": _safe_containerd_version(),
        "kubelet": _safe_kubelet_version(),
        "runc": _safe_runc_version(),
        "cni": _detect_cni_name(),
        "python_platform": platform.platform(),
    }

    # --------------------------
    # Derived health
    # --------------------------
    # These are simple booleans inferred from the collected runtime data.
    health = _health_flags(runtime)

    return {
        "runtime": runtime,
        "versions": versions,
        "health": health,
    }


if __name__ == "__main__":
    # Handy for local debugging:
    # python src/state_collector.py
    print(json.dumps(collect_state(), indent=2))
