import json
import platform
import shutil
import subprocess
from typing import Dict, Any, List


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


def _parse_cni_listing(listing: str) -> List[str]:
    """
    Normalize a raw /etc/cni/net.d listing into a filename list.
    """
    return [line.strip() for line in listing.splitlines() if line.strip()]


def _empty_pod_cni_detection() -> Dict[str, Any]:
    return {
        "cni": "unknown",
        "matched_pods": [],
        "selected_pod": "",
        "confidence": "low",
    }


def _select_cni_match(filenames: List[str]) -> Dict[str, str]:
    """
    Choose the best available CNI signal from discovered config filenames.
    """
    recognized_patterns = [
        ("cilium", "cilium"),
        ("calico", "calico"),
        ("flannel", "flannel"),
        ("weave", "weave"),
    ]

    for filename in filenames:
        lower = filename.lower()
        for pattern, cni_name in recognized_patterns:
            if pattern in lower:
                return {
                    "cni": cni_name,
                    "selected_file": filename,
                    "confidence": "high",
                }

    for filename in filenames:
        lower = filename.lower()
        if lower.endswith(".conf") or lower.endswith(".conflist") or "10-" in lower:
            return {
                "cni": filename,
                "selected_file": filename,
                "confidence": "medium",
            }

    selected_file = filenames[0] if filenames else ""
    return {
        "cni": "unknown",
        "selected_file": selected_file,
        "confidence": "low",
    }


def _detect_cni() -> Dict[str, Any]:
    """
    Best-effort detection of CNI config from /etc/cni/net.d.

    This is a lightweight heuristic, not a full parser.
    """
    if not _command_exists("ls"):
        return {
            "cni": "unknown",
            "filenames": [],
            "selected_file": "",
            "confidence": "low",
        }

    listing = _run_command("ls /etc/cni/net.d/ 2>/dev/null")
    filenames = _parse_cni_listing(listing)
    if not filenames:
        return {
            "cni": "unknown",
            "filenames": [],
            "selected_file": "",
            "confidence": "low",
        }

    result = _select_cni_match(filenames)
    result["filenames"] = filenames
    return result


def _detect_cni_from_pods(pods_text: str) -> Dict[str, Any]:
    """
    Best-effort cluster-level CNI detection from kube-system pod names.
    """
    if not pods_text or "kubectl not installed" in pods_text.lower():
        return _empty_pod_cni_detection()

    kube_system_pods = []
    for line in pods_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "kube-system":
            kube_system_pods.append(parts[1])

    if not kube_system_pods:
        return _empty_pod_cni_detection()

    recognized_patterns = [
        ("cilium", "cilium"),
        ("calico", "calico"),
        ("flannel", "flannel"),
        ("weave", "weave"),
        ("canal", "canal"),
    ]

    best_match = {
        "cni": "unknown",
        "matched_pods": [],
        "selected_pod": "",
        "confidence": "low",
    }

    for pattern, cni_name in recognized_patterns:
        matched = [pod for pod in kube_system_pods if pattern in pod.lower()]
        if len(matched) > len(best_match["matched_pods"]):
            best_match = {
                "cni": cni_name,
                "matched_pods": matched,
                "selected_pod": matched[0],
                "confidence": "high",
            }

    return best_match


def _source_support_score(detection: Dict[str, Any]) -> int:
    """
    Rank evidence sources for simple conflict resolution.
    """
    if detection.get("cni", "unknown") == "unknown":
        return 0

    confidence = detection.get("confidence", "low")
    if "matched_pods" in detection:
        return {"high": 20, "medium": 10, "low": 0}.get(confidence, 0) + len(
            detection.get("matched_pods", [])
        )

    return {"high": 20, "medium": 10, "low": 0}.get(confidence, 0) + len(
        detection.get("filenames", [])
    )


def _reconcile_cni_detection(
    node_level: Dict[str, Any], cluster_level: Dict[str, Any]
) -> Dict[str, str]:
    """
    Combine node-level and cluster-level CNI signals into one summary.
    """
    node_cni = node_level.get("cni", "unknown")
    cluster_cni = cluster_level.get("cni", "unknown")

    node_known = node_cni not in {"", "unknown"}
    cluster_known = cluster_cni not in {"", "unknown"}

    if node_known and cluster_known and node_cni == cluster_cni:
        return {
            "cni": node_cni,
            "confidence": "high",
            "reconciliation": "agree",
        }

    if node_known and not cluster_known:
        return {
            "cni": node_cni,
            "confidence": "medium",
            "reconciliation": "single_source",
        }

    if cluster_known and not node_known:
        return {
            "cni": cluster_cni,
            "confidence": "medium",
            "reconciliation": "single_source",
        }

    if node_known and cluster_known:
        node_score = _source_support_score(node_level)
        cluster_score = _source_support_score(cluster_level)

        if cluster_score > node_score:
            chosen = cluster_cni
        else:
            # Tie-break to node-level to preserve the existing filename-first behavior.
            chosen = node_cni

        return {
            "cni": chosen,
            "confidence": "medium",
            "reconciliation": "conflict",
        }

    return {
        "cni": "unknown",
        "confidence": "low",
        "reconciliation": "unknown",
    }


def _infer_cni_capabilities(cni_name: str) -> Dict[str, str]:
    """
    Infer a small, cautious capability summary from the detected CNI name.
    """
    capability_map = {
        "cilium": {
            "summary": "policy-aware dataplane",
            "policy_support": "likely supported by platform",
            "observability": "enhanced platform telemetry likely available",
        },
        "calico": {
            "summary": "policy-aware dataplane",
            "policy_support": "likely supported by platform",
            "observability": "platform telemetry likely available",
        },
        "canal": {
            "summary": "policy-aware combined deployment",
            "policy_support": "likely supported by platform",
            "observability": "platform-dependent telemetry may be available",
        },
        "flannel": {
            "summary": "basic pod networking dataplane",
            "policy_support": "not indicated by current detection alone",
            "observability": "basic networking visibility inferred",
        },
        "weave": {
            "summary": "overlay networking dataplane",
            "policy_support": "possible but not verified from current detection alone",
            "observability": "basic platform visibility inferred",
        },
    }

    inferred = capability_map.get(cni_name, None)
    if inferred:
        return {
            **inferred,
            "inference_basis": "detected_cni_name",
        }

    return {
        "summary": "unknown",
        "policy_support": "unknown",
        "observability": "unknown",
        "inference_basis": "insufficient_cni_evidence",
    }


def _summarize_network_policy_presence(policies_text: str) -> Dict[str, Any]:
    """
    Summarize whether NetworkPolicy objects are present in the cluster.
    """
    lower = policies_text.lower()
    if not policies_text.strip() or "kubectl not installed" in lower:
        return {
            "status": "unknown",
            "count": 0,
            "namespaces": [],
        }

    if "no resources found" in lower:
        return {
            "status": "absent",
            "count": 0,
            "namespaces": [],
        }

    lines = [line for line in policies_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    namespaces = sorted({line.split()[0] for line in data_lines if line.split()})

    return {
        "status": "present" if data_lines else "absent",
        "count": len(data_lines),
        "namespaces": namespaces,
    }


def _build_cni_migration_note(
    reconciliation: str,
    node_level: Dict[str, Any],
    cluster_level: Dict[str, Any],
) -> str:
    """
    Build a short evidence-based note about reconciliation or possible migration.
    """
    if reconciliation == "agree":
        return "Cluster-level and node-level evidence agree on the current CNI."
    if reconciliation == "single_source":
        return "Only one evidence source identifies the current CNI, so the result remains partially unverified."
    if reconciliation == "conflict":
        return (
            f"Mixed CNI evidence detected: cluster-level suggests {cluster_level.get('cni', 'unknown')} "
            f"while node-level suggests {node_level.get('cni', 'unknown')}. A migration or partial rollout may be in progress."
        )
    return "Not enough evidence is available to identify the current CNI confidently."


def _detect_cni_name() -> str:
    """
    Backward-compatible string-only CNI detector.
    """
    return _detect_cni().get("cni", "unknown")


def _health_flags(
    runtime: Dict[str, str],
    versions: Dict[str, str],
    evidence: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Derive health flags from collected runtime + version text.

    Most layers use:
    True  = confirmed healthy
    False = confirmed unhealthy
    None  = unknown / visibility-limited

    CNI currently uses:
    healthy / degraded / unknown
    """

    pods_text = runtime.get("pods", "").lower()
    events_text = runtime.get("events", "").lower()
    nodes_text = runtime.get("nodes", "").lower()
    kubelet_text = runtime.get("kubelet", "").lower()
    containerd_text = runtime.get("containerd", "").lower()

    api_text = versions.get("api", "").lower()
    runc_text = versions.get("runc", "").lower()
    kernel_text = versions.get("kernel", "").lower()
    cni_text = versions.get("cni", "").lower()
    cni_evidence = (evidence or {}).get("cni", {})
    cni_reconciliation = cni_evidence.get("reconciliation", "unknown")

    pods_pending = "pending" in pods_text
    pods_crashloop = "crashloopbackoff" in pods_text

    # kubelet
    if "systemctl not available" in kubelet_text:
        kubelet_ok = None
    elif "not installed" in kubelet_text or "not on path" in kubelet_text:
        kubelet_ok = None
    elif "inactive" in kubelet_text or "failed" in kubelet_text:
        kubelet_ok = False
    elif "active (running)" in kubelet_text or "running" in kubelet_text:
        kubelet_ok = True
    else:
        kubelet_ok = None

    # containerd
    if "systemctl not available" in containerd_text:
        containerd_ok = None
    elif "not installed" in containerd_text or "not on path" in containerd_text:
        containerd_ok = None
    elif "inactive" in containerd_text or "failed" in containerd_text:
        containerd_ok = False
    elif "active (running)" in containerd_text or "running" in containerd_text:
        containerd_ok = True
    else:
        containerd_ok = None

    # pods
    if "kubectl not installed" in pods_text:
        pods_ok = None
    elif "no resources found" in pods_text:
        pods_ok = True
    elif "pending" in pods_text or "crashloopbackoff" in pods_text:
        pods_ok = False
    elif pods_text.strip():
        pods_ok = True
    else:
        pods_ok = None

    # API / kubectl access
    if "kubectl not installed" in api_text:
        api_access_ok = None
    elif "client version" in api_text and "server version" in api_text:
        api_access_ok = True
    else:
        api_access_ok = None

    # events
    if "kubectl not installed" in events_text:
        events_ok = None
    elif events_text.strip():
        events_ok = True
    else:
        events_ok = None

    # nodes
    if "kubectl not installed" in nodes_text:
        nodes_ok = None
    elif nodes_text.strip():
        nodes_ok = True
    else:
        nodes_ok = None

    # runc
    if "not installed" in runc_text or "not on path" in runc_text:
        runc_ok = None
    elif "runc version" in runc_text:
        runc_ok = True
    else:
        runc_ok = None

    # kernel
    kernel_ok = True if kernel_text.strip() else None

    # cni
    if cni_text in {"", "unknown"}:
        cni_ok = "unknown"
    elif cni_reconciliation == "agree":
        cni_ok = "healthy"
    elif cni_reconciliation in {"single_source", "conflict"}:
        cni_ok = "degraded"
    else:
        cni_ok = "degraded"

    return {
        "pods_pending": pods_pending,
        "pods_crashloop": pods_crashloop,
        "pods_ok": pods_ok,
        "api_access_ok": api_access_ok,
        "events_ok": events_ok,
        "nodes_ok": nodes_ok,
        "kubelet_ok": kubelet_ok,
        "containerd_ok": containerd_ok,
        "runc_ok": runc_ok,
        "kernel_ok": kernel_ok,
        "cni_ok": cni_ok,
    }


def collect_state() -> Dict[str, Any]:
    """
    Collect structured state for cka-coach.

    Returned shape:
    {
      "runtime": {...},
      "summary": {...},
      "evidence": {...},
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

        # cluster policy objects
        "network_policies": _safe_kubectl("kubectl get networkpolicy -A"),
    }

    # --------------------------
    # Version / identity evidence
    # --------------------------
    # These fields are slower-changing metadata that help place the cluster
    # in context and populate table version columns.
    node_cni_detection = _detect_cni()
    cluster_cni_detection = _detect_cni_from_pods(runtime.get("pods", ""))
    combined_cni_detection = _reconcile_cni_detection(
        node_cni_detection,
        cluster_cni_detection,
    )
    policy_presence = _summarize_network_policy_presence(runtime.get("network_policies", ""))
    capabilities = _infer_cni_capabilities(combined_cni_detection.get("cni", "unknown"))
    migration_note = _build_cni_migration_note(
        combined_cni_detection.get("reconciliation", "unknown"),
        node_cni_detection,
        cluster_cni_detection,
    )

    versions = {
        "api": _safe_kubectl_version_short(),
        "k8s_json": _safe_kubectl_version_json(),
        "kernel": _safe_uname(),
        "containerd": _safe_containerd_version(),
        "kubelet": _safe_kubelet_version(),
        "runc": _safe_runc_version(),
        "cni": combined_cni_detection.get("cni", "unknown"),
        "python_platform": platform.platform(),
    }

    summary = {
        "versions": {
            "cni": versions.get("cni", "unknown"),
        }
    }

    evidence = {
        "cni": {
            "cni": combined_cni_detection.get("cni", "unknown"),
            "confidence": combined_cni_detection.get("confidence", "low"),
            "reconciliation": combined_cni_detection.get("reconciliation", "unknown"),
            "capabilities": capabilities,
            "policy_presence": policy_presence,
            "migration_note": migration_note,
            "node_level": node_cni_detection,
            "cluster_level": cluster_cni_detection,
        },
    }

    # --------------------------
    # Derived health
    # --------------------------
    # These are simple derived health/status flags inferred from the collected data.
    health = _health_flags(runtime, versions, evidence)

    return {
        "runtime": runtime,
        "summary": summary,
        "evidence": evidence,
        "versions": versions,
        "health": health,
    }


if __name__ == "__main__":
    # Handy for local debugging:
    # python src/state_collector.py
    print(json.dumps(collect_state(), indent=2))
