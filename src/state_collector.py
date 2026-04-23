import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, List


DEFAULT_CNI_CONFIG_DIR = "/etc/cni/net.d"


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


def _safe_iptables_save() -> str:
    """
    Return local iptables-save output when available.
    """
    if _command_exists("iptables-save"):
        return _run_command("iptables-save")
    if _command_exists("iptables"):
        return _run_command("iptables -S")
    return "iptables tooling not installed or not on PATH"


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
        "matched_daemonsets": [],
        "platform_signals": [],
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


def _select_cni_match_from_content(config_content: str, selected_file: str) -> Dict[str, str]:
    """
    Choose a best-effort CNI signal from readable config content.

    This is intentionally lightweight and only upgrades detection when the
    config content itself clearly points to a known plugin.
    """
    if not config_content.strip():
        return {
            "cni": "unknown",
            "selected_file": selected_file,
            "confidence": "low",
        }

    lower = config_content.lower()
    explicit_patterns = [
        ("cilium", "cilium"),
        ("calico", "calico"),
        ("flannel", "flannel"),
        ("weave", "weave"),
    ]

    for pattern, cni_name in explicit_patterns:
        if pattern in lower:
            return {
                "cni": cni_name,
                "selected_file": selected_file,
                "confidence": "high",
            }

    return {
        "cni": "unknown",
        "selected_file": selected_file,
        "confidence": "low",
    }


def _resolve_cni_config_dir(allow_host_evidence: bool = False) -> Dict[str, Any]:
    """
    Resolve which CNI config directory cka-coach should inspect.

    By default, cka-coach stays least-privilege and uses the standard
    in-environment path only. A user-provided override is honored only when
    host-evidence mode is explicitly enabled.
    """
    configured_dir = os.environ.get("CKA_COACH_CNI_CONFIG_DIR", "").strip()
    using_override = bool(configured_dir and allow_host_evidence)

    return {
        "directory": configured_dir if using_override else DEFAULT_CNI_CONFIG_DIR,
        "directory_source": "env_override" if using_override else "default",
        "host_evidence_enabled": allow_host_evidence,
        "configured_override": configured_dir,
        "configured_override_ignored": bool(configured_dir and not allow_host_evidence),
    }


def _inspect_cni_config_dir(allow_host_evidence: bool = False) -> Dict[str, Any]:
    """
    Inspect the configured CNI config directory without using sudo.
    """
    resolution = _resolve_cni_config_dir(allow_host_evidence)
    directory = resolution["directory"]

    if not os.path.exists(directory):
        return {
            **resolution,
            "directory_status": "directory_missing",
            "filenames": [],
        }

    if not os.path.isdir(directory):
        return {
            **resolution,
            "directory_status": "directory_missing",
            "filenames": [],
        }

    try:
        filenames = sorted(
            entry for entry in os.listdir(directory) if entry and not entry.startswith(".")
        )
    except PermissionError:
        return {
            **resolution,
            "directory_status": "unreadable",
            "filenames": [],
        }
    except OSError:
        return {
            **resolution,
            "directory_status": "unreadable",
            "filenames": [],
        }

    if not filenames:
        return {
            **resolution,
            "directory_status": "readable_empty",
            "filenames": [],
        }

    return {
        **resolution,
        "directory_status": "readable",
        "filenames": filenames,
    }


def _detect_cni(allow_host_evidence: bool = False) -> Dict[str, Any]:
    """
    Best-effort detection of CNI config from /etc/cni/net.d.

    This is a lightweight heuristic, not a full parser.
    """
    inspection = _inspect_cni_config_dir(allow_host_evidence)
    filenames = inspection.get("filenames", [])
    if not filenames:
        return {
            "cni": "unknown",
            "filenames": [],
            "selected_file": "",
            "confidence": "low",
            "config_dir": inspection.get("directory", DEFAULT_CNI_CONFIG_DIR),
            "config_dir_source": inspection.get("directory_source", "default"),
            "directory_status": inspection.get("directory_status", "directory_missing"),
            "host_evidence_enabled": inspection.get("host_evidence_enabled", False),
            "configured_override_ignored": inspection.get("configured_override_ignored", False),
        }

    result = _select_cni_match(filenames)
    if result.get("cni", "unknown") not in {"unknown"} and result.get("confidence") == "high":
        result["filenames"] = filenames
        result["config_dir"] = inspection.get("directory", DEFAULT_CNI_CONFIG_DIR)
        result["config_dir_source"] = inspection.get("directory_source", "default")
        result["directory_status"] = inspection.get("directory_status", "readable")
        result["host_evidence_enabled"] = inspection.get("host_evidence_enabled", False)
        result["configured_override_ignored"] = inspection.get("configured_override_ignored", False)
        return result

    for filename in filenames:
        lower = filename.lower()
        if not (lower.endswith(".conf") or lower.endswith(".conflist")):
            continue

        config_content = _read_selected_cni_config(
            filename,
            inspection.get("directory", DEFAULT_CNI_CONFIG_DIR),
        )
        content_match = _select_cni_match_from_content(config_content, filename)
        if content_match.get("cni", "unknown") != "unknown":
            result = content_match
            break

    result["filenames"] = filenames
    result["config_dir"] = inspection.get("directory", DEFAULT_CNI_CONFIG_DIR)
    result["config_dir_source"] = inspection.get("directory_source", "default")
    result["directory_status"] = inspection.get("directory_status", "readable")
    result["host_evidence_enabled"] = inspection.get("host_evidence_enabled", False)
    result["configured_override_ignored"] = inspection.get("configured_override_ignored", False)
    return result


def _read_selected_cni_config(
    selected_file: str,
    config_dir: str = DEFAULT_CNI_CONFIG_DIR,
) -> str:
    """
    Read the selected CNI config file content when directly observable.
    """
    if not selected_file:
        return ""

    file_path = os.path.join(config_dir, selected_file)
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


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
        ("cilium", ["cilium", "cilium-envoy", "cilium-operator"]),
        ("calico", ["calico-node", "calico-kube-controllers", "calico-typha", "calico-apiserver", "calico"]),
        ("flannel", ["flannel"]),
        ("weave", ["weave"]),
        ("canal", ["canal"]),
    ]

    best_match = {
        "cni": "unknown",
        "matched_pods": [],
        "selected_pod": "",
        "confidence": "low",
    }

    for cni_name, patterns in recognized_patterns:
        matched = [
            pod
            for pod in kube_system_pods
            if any(pattern in pod.lower() for pattern in patterns)
        ]
        if len(matched) > len(best_match["matched_pods"]):
            best_match = {
                "cni": cni_name,
                "matched_pods": matched,
                "selected_pod": matched[0],
                "confidence": "high",
            }

    return best_match


def _detect_cni_from_daemonsets(daemonsets_text: str) -> Dict[str, Any]:
    result = _empty_pod_cni_detection()
    if not daemonsets_text or "kubectl not installed" in daemonsets_text.lower():
        return result

    recognized_patterns = [
        ("cilium", ["cilium", "cilium-envoy"]),
        ("calico", ["calico-node", "calico-typha"]),
        ("flannel", ["flannel"]),
        ("weave", ["weave"]),
        ("canal", ["canal"]),
    ]

    lines = [line for line in daemonsets_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    best_match = dict(result)
    for cni_name, patterns in recognized_patterns:
        matched = []
        for line in data_lines:
            parts = line.split()
            if not parts:
                continue
            ds_name = parts[0]
            if any(pattern in ds_name.lower() for pattern in patterns):
                matched.append(ds_name)
        if len(matched) > len(best_match["matched_daemonsets"]):
            best_match = {
                "cni": cni_name,
                "matched_pods": [],
                "matched_daemonsets": matched,
                "platform_signals": [],
                "selected_pod": "",
                "confidence": "high",
            }
    return best_match


def _detect_cni_from_platform_objects(
    tigera_status_text: str,
    installations_text: str,
    ippools_text: str,
) -> Dict[str, Any]:
    result = _empty_pod_cni_detection()
    signals = []

    lower_tigera = tigera_status_text.lower()
    if tigera_status_text.strip() and "no resources found" not in lower_tigera and "kubectl not installed" not in lower_tigera:
        if "calico" in lower_tigera or "apiserver" in lower_tigera or "goldmane" in lower_tigera or "whisker" in lower_tigera:
            signals.append("tigerastatus present")

    lower_install = installations_text.lower()
    if installations_text.strip() and "no resources found" not in lower_install and "kubectl not installed" not in lower_install:
        signals.append("tigera installation present")

    lower_ippool = ippools_text.lower()
    if ippools_text.strip() and "no resources found" not in lower_ippool and "kubectl not installed" not in lower_ippool:
        signals.append("calico ippool present")

    if signals:
        return {
            "cni": "calico",
            "matched_pods": [],
            "matched_daemonsets": [],
            "platform_signals": signals,
            "selected_pod": "",
            "confidence": "high",
        }

    return result


def _detect_cni_from_cluster_state(runtime: Dict[str, str]) -> Dict[str, Any]:
    pod_detection = _detect_cni_from_pods(runtime.get("pods", ""))
    daemonset_detection = _detect_cni_from_daemonsets(runtime.get("daemonsets", ""))
    platform_detection = _detect_cni_from_platform_objects(
        runtime.get("tigera_status", ""),
        runtime.get("calico_installations", ""),
        runtime.get("calico_ippools", ""),
    )

    candidates = [d for d in [pod_detection, daemonset_detection, platform_detection] if d.get("cni", "unknown") != "unknown"]
    if not candidates:
        return _empty_pod_cni_detection()

    merged: Dict[str, Dict[str, Any]] = {}
    for detection in candidates:
        cni_name = detection["cni"]
        entry = merged.setdefault(
            cni_name,
            {
                "cni": cni_name,
                "matched_pods": [],
                "matched_daemonsets": [],
                "platform_signals": [],
                "selected_pod": "",
                "confidence": "medium",
            },
        )
        entry["matched_pods"].extend(detection.get("matched_pods", []))
        entry["matched_daemonsets"].extend(detection.get("matched_daemonsets", []))
        entry["platform_signals"].extend(detection.get("platform_signals", []))
        if not entry["selected_pod"] and detection.get("selected_pod"):
            entry["selected_pod"] = detection["selected_pod"]
        if detection.get("confidence") == "high":
            entry["confidence"] = "high"

    best = max(
        merged.values(),
        key=lambda item: (
            len(set(item["matched_pods"])),
            len(set(item["matched_daemonsets"])),
            len(set(item["platform_signals"])),
            1 if item.get("confidence") == "high" else 0,
        ),
    )
    best["matched_pods"] = sorted(set(best["matched_pods"]))
    best["matched_daemonsets"] = sorted(set(best["matched_daemonsets"]))
    best["platform_signals"] = sorted(set(best["platform_signals"]))
    return best


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
        ) + len(detection.get("matched_daemonsets", [])) * 3 + len(detection.get("platform_signals", [])) * 3

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
        cluster_confidence = "high" if _source_support_score(cluster_level) >= 23 else "medium"
        return {
            "cni": cluster_cni,
            "confidence": cluster_confidence,
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
            "summary": "policy-capable dataplane likely",
            "policy_support": "platform likely supports network policy features",
            "observability": "enhanced platform telemetry may be available",
            "network_policy": True,
            "policy_model": "Kubernetes + Cilium policy features likely",
        },
        "calico": {
            "summary": "policy-capable dataplane likely",
            "policy_support": "platform likely supports network policy features",
            "observability": "platform telemetry may be available",
            "network_policy": True,
            "policy_model": "Kubernetes + Calico extensions",
        },
        "canal": {
            "summary": "policy-capable combined deployment likely",
            "policy_support": "platform likely supports network policy features",
            "observability": "platform-dependent telemetry may be available",
            "network_policy": True,
            "policy_model": "Kubernetes + Calico extensions likely",
        },
        "flannel": {
            "summary": "basic pod networking dataplane inferred",
            "policy_support": "network policy support is not indicated by current detection alone",
            "observability": "basic networking visibility inferred",
            "network_policy": None,
            "policy_model": "unknown",
        },
        "weave": {
            "summary": "overlay networking dataplane inferred",
            "policy_support": "network policy support may exist but is not verified from current detection alone",
            "observability": "basic platform visibility inferred",
            "network_policy": None,
            "policy_model": "unknown",
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
        "network_policy": None,
        "policy_model": "unknown",
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


def _summarize_cni_cluster_footprint(
    cni_name: str,
    cluster_level: Dict[str, Any],
    daemonsets_text: str,
) -> Dict[str, Any]:
    """
    Summarize a small auditable cluster-side footprint for the detected CNI.
    """
    matched_pods = cluster_level.get("matched_pods", [])
    matched_daemonsets = cluster_level.get("matched_daemonsets", [])
    platform_signals = cluster_level.get("platform_signals", [])
    operator_present = any("operator" in pod.lower() for pod in matched_pods)
    operator_only_footprint = bool(matched_pods) and all("operator" in pod.lower() for pod in matched_pods)

    result = {
        "operator_present": operator_present,
        "daemonset_count": 0,
        "daemonsets": [],
        "platform_signals": platform_signals,
        "summary": "cluster footprint not directly observed",
    }

    if cni_name in {"", "unknown"}:
        return result

    if not daemonsets_text.strip() or "kubectl not installed" in daemonsets_text.lower():
        if operator_only_footprint:
            result["summary"] = "operator present"
        elif matched_pods:
            result["summary"] = "pods present; daemonset footprint not directly observed"
        elif platform_signals:
            result["summary"] = "platform signals present; daemonset footprint not directly observed"
        return result

    lines = [line for line in daemonsets_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    matching_daemonsets = []
    for line in data_lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        ds_name = parts[0]
        if cni_name not in ds_name.lower() and ds_name not in matched_daemonsets:
            continue
        matching_daemonsets.append({
            "name": ds_name,
            "desired": parts[1],
            "ready": parts[3],
            "available": parts[5],
        })

    result["daemonset_count"] = len(matching_daemonsets)
    result["daemonsets"] = matching_daemonsets

    summary_bits = []
    if operator_present:
        summary_bits.append("operator present")
    if matching_daemonsets:
        summary_bits.append(f"daemonsets={len(matching_daemonsets)}")
    if platform_signals:
        summary_bits.append(f"platform_signals={len(platform_signals)}")

    if summary_bits:
        result["summary"] = ", ".join(summary_bits)
    elif matched_pods:
        result["summary"] = "pods present; no matching daemonsets observed"
    elif platform_signals:
        result["summary"] = "platform signals present; no matching daemonsets observed"

    return result


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


def _extract_image_tag(image: str) -> str:
    """
    Extract an explicit image tag when present.
    """
    if not image:
        return ""

    image_without_digest = image.split("@", 1)[0]
    last_segment = image_without_digest.rsplit("/", 1)[-1]
    if ":" not in last_segment:
        return ""

    return image_without_digest.rsplit(":", 1)[-1].strip()


def _detect_cni_version_from_pod_images(
    cni_name: str,
    cluster_level: Dict[str, Any],
    kube_system_pods_json: str,
) -> Dict[str, Any]:
    """
    Detect a CNI version only when directly evidenced by kube-system pod image tags.
    """
    if cni_name in {"", "unknown"} or not kube_system_pods_json.strip():
        return {
            "value": "unknown",
            "source": "insufficient_cluster_image_evidence",
            "pod": "",
            "image": "",
        }

    try:
        data = json.loads(kube_system_pods_json)
    except Exception:
        return {
            "value": "unknown",
            "source": "unparseable_cluster_image_evidence",
            "pod": "",
            "image": "",
        }

    matched_pods = set(cluster_level.get("matched_pods", []))
    relevant_images = []

    for item in data.get("items", []):
        metadata = item.get("metadata", {})
        pod_name = metadata.get("name", "")
        if matched_pods and pod_name not in matched_pods:
            continue
        if not matched_pods and cni_name not in pod_name.lower():
            continue

        spec = item.get("spec", {})
        containers = spec.get("containers", []) + spec.get("initContainers", [])
        for container in containers:
            image = container.get("image", "")
            tag = _extract_image_tag(image)
            if tag:
                relevant_images.append({
                    "pod": pod_name,
                    "image": image,
                    "tag": tag,
                })

    distinct_tags = sorted({entry["tag"] for entry in relevant_images})
    if len(distinct_tags) != 1 or not relevant_images:
        return {
            "value": "unknown",
            "source": "no_single_trustworthy_image_tag",
            "pod": "",
            "image": "",
        }

    selected = relevant_images[0]
    return {
        "value": distinct_tags[0],
        "source": "kube_system_pod_image_tag",
        "pod": selected["pod"],
        "image": selected["image"],
    }


def _parse_calico_bird_protocols(output: str) -> Dict[str, Any]:
    """
    Parse direct Calico BIRD protocol output into a small health summary.
    """
    lower = output.lower()
    if not output.strip() or "kubectl not installed" in lower:
        return {
            "status": "unknown",
            "bird_ready": False,
            "established_peers": 0,
            "protocol_lines": [],
            "summary": "direct Calico runtime evidence not collected",
        }

    protocol_lines = []
    established_peers = 0
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "bgp" in stripped.lower():
            protocol_lines.append(stripped)
            if "Established" in stripped:
                established_peers += 1

    bird_ready = "bird" in lower and "ready" in lower
    if established_peers > 0:
        return {
            "status": "established",
            "bird_ready": bird_ready,
            "established_peers": established_peers,
            "protocol_lines": protocol_lines,
            "summary": f"BGP peers established={established_peers}",
        }
    if bird_ready:
        return {
            "status": "bird_ready_no_established_peer",
            "bird_ready": True,
            "established_peers": 0,
            "protocol_lines": protocol_lines,
            "summary": "BIRD is ready but no established BGP peers were observed",
        }

    return {
        "status": "unknown",
        "bird_ready": False,
        "established_peers": 0,
        "protocol_lines": protocol_lines,
        "summary": "direct Calico runtime evidence not collected",
    }


def _collect_calico_runtime_evidence(cluster_level: Dict[str, Any]) -> Dict[str, Any]:
    """
    Collect direct Calico runtime evidence from a calico-node pod when available.
    """
    if cluster_level.get("cni", "unknown") != "calico":
        return {
            "status": "not_applicable",
            "pod": "",
            "bird_ready": False,
            "established_peers": 0,
            "protocol_lines": [],
            "summary": "not applicable for current CNI",
            "source": "not_applicable",
            "raw_output": "",
        }

    calico_node_pod = next(
        (pod for pod in cluster_level.get("matched_pods", []) if "calico-node" in pod.lower()),
        "",
    )
    if not calico_node_pod:
        return {
            "status": "unknown",
            "pod": "",
            "bird_ready": False,
            "established_peers": 0,
            "protocol_lines": [],
            "summary": "no calico-node pod was available for direct runtime evidence",
            "source": "no_calico_node_pod",
            "raw_output": "",
        }

    output = _safe_kubectl(
        f"kubectl -n kube-system exec {calico_node_pod} -- birdcl show protocols"
    )
    parsed = _parse_calico_bird_protocols(output)
    return {
        **parsed,
        "pod": calico_node_pod,
        "source": "kubectl_exec_birdcl",
        "raw_output": output,
    }


def _parse_nodes_taints(nodes_json: str) -> List[Dict[str, str]]:
    """
    Parse node taints from kubectl get nodes -o json output.
    """
    if not nodes_json.strip():
        return []

    try:
        data = json.loads(nodes_json)
    except Exception:
        return []

    taints = []
    for item in data.get("items", []):
        node_name = item.get("metadata", {}).get("name", "")
        for taint in item.get("spec", {}).get("taints", []) or []:
            taints.append(
                {
                    "node": node_name,
                    "key": taint.get("key", ""),
                    "value": taint.get("value", ""),
                    "effect": taint.get("effect", ""),
                }
            )
    return taints


def _detect_stale_cni_taints(nodes_json: str, current_cni: str) -> Dict[str, Any]:
    """
    Detect leftover taints from a previous CNI.
    """
    taints = _parse_nodes_taints(nodes_json)
    stale = []
    previous = "unknown"
    for taint in taints:
        key = taint.get("key", "").lower()
        if "node.cilium.io/" in key and current_cni != "cilium":
            stale.append(taint)
            previous = "cilium"

    return {
        "detected": bool(stale),
        "previous_cni": previous,
        "taints": stale,
        "summary": (
            f"stale taints detected ({len(stale)})"
            if stale
            else "no stale CNI taints detected"
        ),
    }


def _detect_stale_cni_interfaces(network_text: str, current_cni: str) -> Dict[str, Any]:
    """
    Detect leftover node interfaces from a previous CNI.
    """
    stale = []
    previous = "unknown"
    informational = []
    for line in network_text.splitlines():
        stripped = line.strip()
        if not stripped or ": " not in stripped:
            continue
        iface_name = stripped.split(": ", 1)[1].split(":", 1)[0].split("@", 1)[0]
        lower = iface_name.lower()
        if lower.startswith(("cilium_host", "cilium_net", "cilium_vxlan")) and current_cni != "cilium":
            stale.append(iface_name)
            previous = "cilium"
        elif (lower.startswith("cali") or lower == "vxlan.calico") and current_cni != "calico":
            stale.append(iface_name)
            previous = "calico"
        elif lower == "tunl0":
            informational.append(iface_name)

    return {
        "detected": bool(stale),
        "previous_cni": previous,
        "interfaces": sorted(set(stale)),
        "informational_interfaces": sorted(set(informational)),
        "summary": (
            f"stale interfaces detected ({', '.join(sorted(set(stale)))})"
            if stale
            else (
                "non-blocking tunnel interfaces detected (tunl0)"
                if informational
                else "no stale CNI interfaces detected"
            )
        ),
    }


def _load_cni_provenance(configmap_json: str) -> Dict[str, Any]:
    """
    Load optional CNI provenance metadata from a ConfigMap.
    """
    missing = {
        "available": False,
        "source": "configmap_missing",
        "current_detected_cni": "unknown",
        "previous_detected_cni": "unknown",
        "last_cleaned_at": "",
        "cleaned_by": "",
        "last_install_observed_at": "",
        "evidence_basis": "no provenance ConfigMap was found",
    }

    lower = configmap_json.lower()
    if not configmap_json.strip() or "notfound" in lower or "not found" in lower:
        return missing

    try:
        data = json.loads(configmap_json)
    except Exception:
        return {
            **missing,
            "source": "configmap_unparseable",
            "evidence_basis": "provenance ConfigMap could not be parsed",
        }

    cm_data = data.get("data", {}) or {}
    return {
        "available": True,
        "source": "kube_system_configmap",
        "current_detected_cni": cm_data.get("current_detected_cni", "unknown"),
        "previous_detected_cni": cm_data.get("previous_detected_cni", "unknown"),
        "last_cleaned_at": cm_data.get("last_cleaned_at", ""),
        "cleaned_by": cm_data.get("cleaned_by", ""),
        "last_install_observed_at": cm_data.get("last_install_observed_at", ""),
        "evidence_basis": cm_data.get(
            "evidence_basis",
            "loaded from kube-system/cka-coach-provenance",
        ),
    }


def _summarize_cni_event_history(events_text: str, current_cni: str) -> Dict[str, Any]:
    """
    Summarize CNI-related event history as historical context, not primary current-state proof.
    """
    if not events_text.strip() or "kubectl not installed" in events_text.lower():
        return {
            "summary": "no relevant CNI event history collected",
            "relevant_lines": [],
            "basis": "historical_context",
        }

    patterns = []
    if current_cni == "calico":
        patterns = ["calico-node", "calico-kube-controllers", "bird", "bgp"]
    elif current_cni == "cilium":
        patterns = ["cilium", "cilium-envoy", "cilium-operator"]
    else:
        patterns = ["calico", "cilium", "flannel", "weave", "canal"]

    relevant_lines = []
    for line in events_text.splitlines():
        lower = line.lower()
        if any(pattern in lower for pattern in patterns):
            relevant_lines.append(line.strip())
        if len(relevant_lines) >= 5:
            break

    if not relevant_lines:
        summary = "no recent CNI-specific events matched the current evidence"
    else:
        summary = f"historical CNI-related events observed={len(relevant_lines)}"

    return {
        "summary": summary,
        "relevant_lines": relevant_lines,
        "basis": "historical_context",
    }


def _classify_cni_state(
    runtime: Dict[str, str],
    versions: Dict[str, str],
    evidence: Dict[str, Any],
    health: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Classify the current CNI state into one normalized educational label.
    """
    health = health or {}
    cni_text = versions.get("cni", "unknown")
    node_level = evidence.get("node_level", {})
    cluster_level = evidence.get("cluster_level", {})
    cluster_footprint = evidence.get("cluster_footprint", {})
    calico_runtime = evidence.get("calico_runtime", {})
    platform_signals = cluster_footprint.get("platform_signals", [])
    migration_note = evidence.get("migration_note", "")
    node_cni = node_level.get("cni", "unknown")
    cluster_cni = cluster_level.get("cni", "unknown")
    reconciliation = evidence.get("reconciliation", "unknown")
    nodes_ready = _all_nodes_ready(runtime.get("nodes", ""))
    pods_text = runtime.get("pods", "").lower()
    pods_running = bool(pods_text.strip()) and "pending" not in pods_text and "crashloopbackoff" not in pods_text
    stale_taints = _detect_stale_cni_taints(runtime.get("nodes_json", ""), cni_text)
    stale_interfaces = _detect_stale_cni_interfaces(runtime.get("network", ""), cni_text)

    notes = []
    previous_detected_cni = "unknown"
    if stale_taints.get("detected"):
        previous_detected_cni = stale_taints.get("previous_cni", "unknown")
        notes.append("Leftover taints from a previous CNI are still present.")
    if stale_interfaces.get("detected"):
        if previous_detected_cni == "unknown":
            previous_detected_cni = stale_interfaces.get("previous_cni", "unknown")
        notes.append("Leftover node interfaces from a previous CNI are still present.")
    elif stale_interfaces.get("informational_interfaces"):
        notes.append("tunl0 is present as a non-blocking Linux IP-in-IP tunnel device and is not treated as required cleanup.")
    if reconciliation == "conflict":
        if previous_detected_cni == "unknown" and node_cni not in {"", "unknown"} and cluster_cni not in {"", "unknown"}:
            previous_detected_cni = node_cni if node_cni != cni_text else cluster_cni
        notes.append("Node-level and cluster-level CNI signals do not match.")

    strong_calico = (
        cni_text == "calico"
        and cluster_cni == "calico"
        and (
            any(ds.get("name") == "calico-node" for ds in cluster_footprint.get("daemonsets", []))
            or any("calico-node" in pod.lower() for pod in cluster_level.get("matched_pods", []))
            or bool(platform_signals)
        )
        and (calico_runtime.get("status") == "established" or bool(platform_signals))
    )
    strong_cilium = (
        cni_text == "cilium"
        and cluster_cni == "cilium"
        and any(ds.get("name") == "cilium" for ds in cluster_footprint.get("daemonsets", []))
    )
    residual_previous_cni = (
        cni_text in {"calico", "cilium"}
        and cluster_cni == cni_text
        and previous_detected_cni not in {"", "unknown", cni_text}
        and (stale_interfaces.get("detected") or stale_taints.get("detected"))
    )
    named_plugin_present = any(
        cni in {"calico", "cilium"} for cni in {cni_text, node_cni, cluster_cni}
    )

    if residual_previous_cni and (strong_calico or strong_cilium):
        state = "residual_node_dataplane_state"
        reason = (
            f"{cni_text.capitalize()} is active at cluster level, but leftover {previous_detected_cni} "
            "node dataplane artifacts remain on the observed node."
        )
    elif node_cni not in {"", "unknown"} and cluster_cni not in {"", "unknown"} and node_cni != cluster_cni:
        state = "stale_node_config"
        reason = (
            f"Cluster evidence indicates {cluster_cni}, but node-level config still references {node_cni}."
        )
    elif node_cni in {"calico", "cilium"} and cluster_cni in {"", "unknown"}:
        state = "stale_node_config"
        reason = (
            f"Current cluster footprint does not confirm an active {node_cni} installation, "
            f"but node-level CNI config still points to {node_cni}."
        )
    elif stale_taints.get("detected"):
        state = "stale_taint"
        reason = "Current cluster state does not match CNI-specific taints that remain on nodes."
    elif stale_interfaces.get("detected"):
        state = "stale_interfaces"
        reason = "Current cluster state does not match leftover CNI-specific interfaces still present on nodes."
    elif strong_calico:
        state = "healthy_calico"
        reason = "Calico daemonset/runtime evidence is present with no conflicting CNI signal."
    elif strong_cilium:
        state = "healthy_cilium"
        reason = "Cilium daemonset/operator evidence is present with no conflicting CNI signal."
    elif reconciliation in {"conflict", "single_source"}:
        state = "mixed_or_transitional"
        reason = migration_note or "Evidence suggests an in-progress migration or only partially verified CNI state."
    elif cni_text in {"", "unknown"} and node_cni in {"", "unknown"} and cluster_cni in {"", "unknown"}:
        if nodes_ready is True and pods_running:
            state = "generic_cni"
            reason = "Networking appears functional, but no strong Calico or Cilium signature was detected."
        else:
            state = "no_cni"
            reason = "No cluster-level or node-level CNI signals were detected."
    elif cni_text not in {"", "unknown"} and cni_text not in {"calico", "cilium"}:
        state = "generic_cni"
        reason = "A non-specific or generic CNI signal was detected without strong Calico or Cilium evidence."
    elif named_plugin_present:
        state = "mixed_or_transitional"
        reason = "A named CNI plugin is indicated by some evidence, but current cluster and node signals do not cleanly agree."
    else:
        state = "generic_cni"
        reason = "Available networking evidence is functional but does not fit a stronger normalized CNI state."

    return {
        "state": state,
        "reason": reason,
        "notes": notes,
        "previous_detected_cni": previous_detected_cni,
        "stale_taint": stale_taints,
        "stale_interfaces": stale_interfaces,
        "health_status": health.get("cni_ok", "unknown"),
        "confidence": evidence.get("confidence", "low"),
    }


def _detect_cni_config_spec_version(
    config_content: str,
    selected_file: str,
) -> Dict[str, str]:
    """
    Detect the CNI config spec version from directly observed config content.
    """
    if not selected_file or not config_content.strip():
        return {
            "value": "unknown",
            "source": "missing_cni_config_content",
            "file": selected_file or "",
        }

    try:
        data = json.loads(config_content)
    except Exception:
        return {
            "value": "unknown",
            "source": "unparseable_cni_config_content",
            "file": selected_file,
        }

    config_version = str(data.get("cniVersion", "")).strip()
    if not config_version:
        return {
            "value": "unknown",
            "source": "cni_config_version_not_present",
            "file": selected_file,
        }

    return {
        "value": config_version,
        "source": "selected_cni_config_content",
        "file": selected_file,
    }


def _detect_cni_name() -> str:
    """
    Backward-compatible string-only CNI detector.
    """
    return _detect_cni().get("cni", "unknown")


def _all_nodes_ready(nodes_text: str) -> bool | None:
    """
    Return True when all listed nodes are Ready, False when any are not, else None.
    """
    lowered = nodes_text.lower()
    if not nodes_text.strip() or "kubectl not installed" in lowered:
        return None

    lines = [line for line in nodes_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    if not data_lines:
        return None

    statuses = []
    for line in data_lines:
        parts = line.split()
        if len(parts) >= 2:
            statuses.append(parts[1])

    if not statuses:
        return None

    if all(status == "Ready" for status in statuses):
        return True

    return False


def _has_kubelet_cleanup_noise(kubelet_text: str) -> bool:
    """
    Detect cleanup/history messages that should not by themselves mark kubelet unhealthy.
    """
    cleanup_patterns = [
        "container not found",
        "not found in pod's containers",
        "deletecontainer",
        "removecontainer",
        "orphaned pod",
        "volume paths are still present",
        "podsandbox not found",
        "failed to get container status",
        "stale status",
        "already removed",
    ]

    return any(pattern in kubelet_text for pattern in cleanup_patterns)


def _has_containerd_cleanup_noise(containerd_text: str) -> bool:
    """
    Detect cleanup/history messages that should not by themselves mark containerd unhealthy.
    """
    cleanup_patterns = [
        "not found",
        "already removed",
        "failed to delete",
        "cleanup",
        "remove container",
        "remove task",
        "failed to get task",
        "shim disconnected",
        "stale status",
    ]

    return any(pattern in containerd_text for pattern in cleanup_patterns)


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
    cni_cluster_footprint = cni_evidence.get("cluster_footprint", {})
    cni_classification = cni_evidence.get("classification", {})
    calico_runtime = cni_evidence.get("calico_runtime", {})
    platform_signals = cni_cluster_footprint.get("platform_signals", [])
    cni_node_level = cni_evidence.get("node_level", {})
    cni_cluster_level = cni_evidence.get("cluster_level", {})
    nodes_ready_now = _all_nodes_ready(runtime.get("nodes", ""))

    pods_pending = "pending" in pods_text
    pods_crashloop = "crashloopbackoff" in pods_text

    # kubelet
    kubelet_cleanup_noise = _has_kubelet_cleanup_noise(kubelet_text)
    kubelet_service_active = "active (running)" in kubelet_text or "running" in kubelet_text
    kubelet_service_failed = (
        ("inactive" in kubelet_text or "failed" in kubelet_text)
        and not kubelet_service_active
    )
    kubelet_network_plugin_not_ready = (
        "networkpluginnotready" in kubelet_text
        or "network plugin is not ready" in kubelet_text
    ) and nodes_ready_now is not True

    if "systemctl not available" in kubelet_text:
        kubelet_ok = None
    elif "not installed" in kubelet_text or "not on path" in kubelet_text:
        kubelet_ok = None
    elif kubelet_service_failed:
        kubelet_ok = False
    elif (
        kubelet_service_active
        and nodes_ready_now is True
        and pods_pending is False
        and pods_crashloop is False
        and not kubelet_network_plugin_not_ready
    ):
        kubelet_ok = True
    elif kubelet_service_active:
        kubelet_ok = True
    else:
        kubelet_ok = None

    kubelet_transitional_note = ""
    if kubelet_ok is True and kubelet_cleanup_noise:
        kubelet_transitional_note = (
            "Recent kubelet output includes cleanup/history messages for removed containers, "
            "orphaned volumes, or stale status lookups. Current service and node readiness still indicate kubelet is functioning."
        )

    # containerd
    containerd_cleanup_noise = _has_containerd_cleanup_noise(containerd_text)
    containerd_service_active = "active (running)" in containerd_text or "running" in containerd_text
    containerd_service_failed = (
        ("inactive" in containerd_text or "failed" in containerd_text)
        and not containerd_service_active
    )

    if "systemctl not available" in containerd_text:
        containerd_ok = None
    elif "not installed" in containerd_text or "not on path" in containerd_text:
        containerd_ok = None
    elif containerd_service_failed:
        containerd_ok = False
    elif (
        containerd_service_active
        and nodes_ready_now is True
        and pods_pending is False
        and pods_crashloop is False
    ):
        containerd_ok = True
    elif containerd_service_active:
        containerd_ok = True
    else:
        containerd_ok = None

    containerd_transitional_note = ""
    if containerd_ok is True and containerd_cleanup_noise:
        containerd_transitional_note = (
            "Recent containerd output includes cleanup/history messages for removed containers, "
            "tasks, or stale status lookups. Current service and node readiness still indicate containerd is functioning."
        )

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
    expected_cni_daemonsets = {
        "cilium": {"cilium"},
        "calico": {"calico-node"},
    }
    observed_cni_daemonsets = {
        ds.get("name", "")
        for ds in cni_cluster_footprint.get("daemonsets", [])
        if ds.get("name")
    }
    expected_daemonsets = expected_cni_daemonsets.get(cni_text, set())
    daemonset_evidence_direct = "not directly observed" not in cni_cluster_footprint.get(
        "summary",
        "",
    )
    missing_expected_daemonset = bool(
        daemonset_evidence_direct
        and expected_daemonsets
        and not (observed_cni_daemonsets & expected_daemonsets)
    )
    override_config_conflict = (
        cni_reconciliation == "conflict"
        and cni_node_level.get("config_dir_source") == "env_override"
        and cni_cluster_level.get("cni", "unknown") == cni_text
    )
    strong_live_cluster_cni_evidence = bool(
        expected_daemonsets
        and (observed_cni_daemonsets & expected_daemonsets)
    ) or (cni_text == "calico" and calico_runtime.get("status") == "established") or bool(platform_signals)
    residual_previous_cni = (
        cni_text in {"calico", "cilium"}
        and cni_cluster_level.get("cni", "unknown") == cni_text
        and cni_classification.get("previous_detected_cni", "unknown") not in {"", "unknown", cni_text}
        and (
            cni_classification.get("stale_interfaces", {}).get("detected")
            or cni_classification.get("stale_taint", {}).get("detected")
        )
    )

    if cni_text in {"", "unknown"}:
        cni_ok = "unknown"
    elif override_config_conflict and strong_live_cluster_cni_evidence:
        cni_ok = "unknown"
    elif residual_previous_cni and strong_live_cluster_cni_evidence:
        cni_ok = "healthy"
    elif cni_reconciliation == "conflict":
        cni_ok = "degraded"
    elif cni_text == "calico" and calico_runtime.get("status") == "established":
        cni_ok = "healthy"
    elif cni_reconciliation == "single_source" and strong_live_cluster_cni_evidence:
        cni_ok = "healthy"
    elif missing_expected_daemonset:
        cni_ok = "unknown"
    elif cni_reconciliation == "agree":
        cni_ok = "healthy"
    elif cni_reconciliation == "single_source":
        cni_ok = "unknown"
    else:
        cni_ok = "unknown"

    return {
        "pods_pending": pods_pending,
        "pods_crashloop": pods_crashloop,
        "pods_ok": pods_ok,
        "api_access_ok": api_access_ok,
        "events_ok": events_ok,
        "nodes_ok": nodes_ok,
        "kubelet_ok": kubelet_ok,
        "kubelet_cleanup_noise": kubelet_cleanup_noise,
        "kubelet_transitional_note": kubelet_transitional_note,
        "containerd_ok": containerd_ok,
        "containerd_cleanup_noise": containerd_cleanup_noise,
        "containerd_transitional_note": containerd_transitional_note,
        "runc_ok": runc_ok,
        "kernel_ok": kernel_ok,
        "cni_ok": cni_ok,
    }


def collect_state(
    allow_host_evidence: bool = False,
    include_logs: bool = False,
) -> Dict[str, Any]:
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
        "hostname": _run_command("hostname"),

        # Pod-level view for L8 application_pods
        "pods": _safe_kubectl("kubectl get pods -A -o wide"),
        "pods_json": _safe_kubectl("kubectl get pods -A -o json"),
        "services_json": _safe_kubectl("kubectl get svc -A -o json"),

        # Event / object-level clues for L7 and L5
        "events": _safe_kubectl("kubectl get events -A --sort-by=.lastTimestamp"),

        # Node view is useful for scheduler/controller and node/network questions
        "nodes": _safe_kubectl("kubectl get nodes -o wide"),
        "nodes_json": _safe_kubectl("kubectl get nodes -o json"),

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

        # local iptables/ipset clues for dataplane residue checks
        "iptables": _safe_iptables_save(),

        # cluster policy objects
        "network_policies": _safe_kubectl("kubectl get networkpolicy -A"),

        # cluster daemonsets / deployments for networking footprint summaries
        "daemonsets": _safe_kubectl("kubectl get daemonsets -A"),
        "deployments": _safe_kubectl("kubectl get deployments -A"),

        # operator-managed Calico/Tigera signals
        "tigera_status": _safe_kubectl("kubectl get tigerastatus"),
        "calico_installations": _safe_kubectl("kubectl get installation.operator.tigera.io -A"),
        "calico_installations_json": _safe_kubectl("kubectl get installation.operator.tigera.io -A -o json"),
        "calico_ippools": _safe_kubectl("kubectl get ippools.crd.projectcalico.org -A"),
        "calico_ippools_json": _safe_kubectl("kubectl get ippools.crd.projectcalico.org -A -o json"),

        # detailed kube-system pod data used for direct image-tag evidence
        "kube_system_pods_json": _safe_kubectl("kubectl get pods -n kube-system -o json"),

        # optional provenance metadata stored in-cluster
        "cni_provenance_configmap": _safe_kubectl(
            "kubectl get configmap cka-coach-provenance -n kube-system -o json"
        ),
    }

    if include_logs:
        runtime["kubelet_logs"] = _safe_journalctl("kubelet", lines=80)
        runtime["containerd_logs"] = _safe_journalctl("containerd", lines=80)

    # --------------------------
    # Version / identity evidence
    # --------------------------
    # These fields are slower-changing metadata that help place the cluster
    # in context and populate table version columns.
    node_cni_detection = _detect_cni(allow_host_evidence=allow_host_evidence)
    cluster_cni_detection = _detect_cni_from_cluster_state(runtime)
    combined_cni_detection = _reconcile_cni_detection(
        node_cni_detection,
        cluster_cni_detection,
    )
    policy_presence = _summarize_network_policy_presence(runtime.get("network_policies", ""))
    capabilities = _infer_cni_capabilities(combined_cni_detection.get("cni", "unknown"))
    cluster_footprint = _summarize_cni_cluster_footprint(
        combined_cni_detection.get("cni", "unknown"),
        cluster_cni_detection,
        runtime.get("daemonsets", ""),
    )
    calico_runtime = _collect_calico_runtime_evidence(cluster_cni_detection)
    cni_version = _detect_cni_version_from_pod_images(
        combined_cni_detection.get("cni", "unknown"),
        cluster_cni_detection,
        runtime.get("kube_system_pods_json", ""),
    )
    cni_config_content = _read_selected_cni_config(
        node_cni_detection.get("selected_file", ""),
        node_cni_detection.get("config_dir", DEFAULT_CNI_CONFIG_DIR),
    )
    cni_config_spec_version = _detect_cni_config_spec_version(
        cni_config_content,
        node_cni_detection.get("selected_file", ""),
    )
    migration_note = _build_cni_migration_note(
        combined_cni_detection.get("reconciliation", "unknown"),
        node_cni_detection,
        cluster_cni_detection,
    )
    event_history = _summarize_cni_event_history(
        runtime.get("events", ""),
        combined_cni_detection.get("cni", "unknown"),
    )
    provenance = _load_cni_provenance(runtime.get("cni_provenance_configmap", ""))

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
            "cni_version": cni_version.get("value", "unknown"),
            "cni_config_spec_version": cni_config_spec_version.get("value", "unknown"),
        },
        "cni_classification": "unknown",
    }

    evidence = {
        "cni": {
            "cni": combined_cni_detection.get("cni", "unknown"),
            "confidence": combined_cni_detection.get("confidence", "low"),
            "reconciliation": combined_cni_detection.get("reconciliation", "unknown"),
            "capabilities": capabilities,
            "cluster_footprint": cluster_footprint,
            "cluster_platform_signals": {
                "signals": cluster_cni_detection.get("platform_signals", []),
                "summary": (
                    f"platform signals={len(cluster_cni_detection.get('platform_signals', []))}"
                    if cluster_cni_detection.get("platform_signals")
                    else "no platform signals collected"
                ),
            },
            "calico_runtime": calico_runtime,
            "policy_presence": policy_presence,
            "version": cni_version,
            "config_spec_version": cni_config_spec_version,
            "config_content": cni_config_content,
            "migration_note": migration_note,
            "event_history": event_history,
            "provenance": provenance,
            "node_level": node_cni_detection,
            "cluster_level": cluster_cni_detection,
        },
    }

    # --------------------------
    # Derived health
    # --------------------------
    # These are simple derived health/status flags inferred from the collected data.
    health = _health_flags(runtime, versions, evidence)
    classification = _classify_cni_state(runtime, versions, evidence["cni"], health)
    evidence["cni"]["classification"] = classification
    summary["cni_classification"] = classification.get("state", "unknown")

    if provenance.get("available") and provenance.get("current_detected_cni", "unknown") in {"", "unknown"}:
        provenance["current_detected_cni"] = versions.get("cni", "unknown")
    if (
        not provenance.get("available")
        and classification.get("previous_detected_cni", "unknown") not in {"", "unknown"}
    ):
        provenance["previous_detected_cni"] = classification.get("previous_detected_cni", "unknown")
        provenance["evidence_basis"] = (
            f"best-effort inference from current evidence: {classification.get('reason', 'unknown')}"
        )
    if versions.get("cni", "unknown") not in {"", "unknown"} and not provenance.get("last_install_observed_at"):
        provenance["last_install_observed_at"] = datetime.now(timezone.utc).isoformat()

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
