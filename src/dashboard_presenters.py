import json
from typing import Any, Dict, List


def cni_config_spec_display(state: Dict) -> Dict[str, str | bool]:
    """
    Build a compact, educational display state for CNI config-spec evidence.
    """
    cni_evidence = state.get("evidence", {}).get("cni", {})
    node_level = cni_evidence.get("node_level", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    config_spec = summary_versions.get("cni_config_spec_version", "unknown")

    if config_spec not in {"", "unknown"}:
        return {
            "label": config_spec,
            "observed": True,
            "note": "",
        }

    config_dir = node_level.get("config_dir", "/etc/cni/net.d")
    return {
        "label": "not directly observed*",
        "observed": False,
        "note": (
            "cka-coach does not use sudo by design. It cannot see host-level CNI config evidence "
            f"unless you expose a readable path such as `{config_dir}` and start it with `--allow-host-evidence`."
        ),
    }


def cni_status_label(state: Dict) -> str:
    cni_health = state.get("health", {}).get("cni_ok", "unknown")
    return {
        "healthy": "working",
        "degraded": "degraded",
        "unknown": "visibility-limited",
    }.get(cni_health, cni_health)


def cni_summary_text(state: Dict) -> str:
    versions = state.get("versions", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    cni_evidence = state.get("evidence", {}).get("cni", {})

    cni_name = summary_versions.get("cni", versions.get("cni", "")) or "unknown"
    cni_display_name = cni_name.capitalize() if cni_name != "unknown" else "unknown"
    cni_confidence = cni_evidence.get("confidence", "unknown")
    cni_classification_state = cni_evidence.get("classification", {}).get("state", "unknown")
    cluster_footprint = cni_evidence.get("cluster_footprint", {}).get(
        "summary",
        "cluster footprint not directly observed",
    )
    capability_summary = cni_evidence.get("capabilities", {}).get("summary", "unknown")
    node_level_cni = cni_evidence.get("node_level", {}).get("cni", "unknown")
    cluster_level_cni = cni_evidence.get("cluster_level", {}).get("cni", "unknown")
    reconciliation = cni_evidence.get("reconciliation", "unknown")
    health_label = cni_status_label(state)

    text = f"{cni_display_name} | {health_label} | {cni_confidence} confidence"
    if state.get("health", {}).get("cni_ok") == "healthy" and capability_summary == "policy-capable dataplane likely":
        text = f"{cni_display_name} | working | policy-capable | {cni_confidence} confidence"
    elif cni_classification_state not in {"", "unknown", "healthy_calico", "healthy_cilium"}:
        text = f"{cni_display_name} | {cni_classification_state} | {cni_confidence} confidence"

    if (
        reconciliation == "single_source"
        and node_level_cni not in {"", "unknown"}
        and cluster_level_cni in {"", "unknown"}
    ):
        return (
            f"{cni_name or 'unknown'} | {cni_confidence} confidence | "
            f"cluster missing, node config says {node_level_cni}"
        )

    if reconciliation == "conflict":
        return (
            f"{cni_name or 'unknown'} | {cni_classification_state} | "
            f"cluster {cluster_level_cni or 'unknown'} vs node {node_level_cni or 'unknown'}"
        )

    if cluster_footprint not in {"", "cluster footprint not directly observed"} and state.get("health", {}).get("cni_ok") != "healthy":
        text = f"{text} | {cluster_footprint}"

    return text


def _parse_json_text(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def _extract_image_tag(image: str) -> str:
    image_without_digest = image.split("@", 1)[0]
    last_segment = image_without_digest.rsplit("/", 1)[-1]
    if ":" not in last_segment:
        return ""
    return image_without_digest.rsplit(":", 1)[-1].strip()


def _component_definitions() -> List[Dict[str, str]]:
    return [
        {"key": "calico-node", "label": "calico-node", "match": "calico-node"},
        {"key": "calico-kube-controllers", "label": "calico-kube-controllers", "match": "calico-kube-controllers"},
        {"key": "calico-apiserver", "label": "calico-apiserver", "match": "calico-apiserver"},
        {"key": "kube-proxy", "label": "kube-proxy", "match": "kube-proxy"},
        {"key": "goldmane", "label": "Goldmane", "match": "goldmane"},
        {"key": "whisker", "label": "Whisker", "match": "whisker"},
        {"key": "cilium", "label": "cilium", "match": "cilium"},
        {"key": "cilium-operator", "label": "cilium-operator", "match": "cilium-operator"},
        {"key": "cilium-envoy", "label": "cilium-envoy", "match": "cilium-envoy"},
    ]


def _ready_container_count(item: Dict[str, Any]) -> tuple[int, int]:
    statuses = item.get("status", {}).get("containerStatuses", []) or []
    if not statuses:
        return (0, 0)
    ready = sum(1 for status in statuses if status.get("ready"))
    return ready, len(statuses)


def _collect_networking_components(state: Dict) -> Dict[str, Dict[str, Any]]:
    pods_json = _parse_json_text(state.get("runtime", {}).get("pods_json", ""))
    items = pods_json.get("items", []) if isinstance(pods_json, dict) else []

    components: Dict[str, Dict[str, Any]] = {}
    for definition in _component_definitions():
        components[definition["key"]] = {
            "label": definition["label"],
            "present": False,
            "pods": [],
            "namespaces": set(),
            "ready_pods": 0,
            "tags": set(),
        }

    for item in items:
        metadata = item.get("metadata", {}) or {}
        pod_name = metadata.get("name", "")
        namespace = metadata.get("namespace", "")
        ready, total = _ready_container_count(item)
        images = [
            container.get("image", "")
            for container in (item.get("spec", {}).get("containers", []) or [])
            if container.get("image")
        ]
        for definition in _component_definitions():
            if definition["match"] not in pod_name.lower():
                continue
            component = components[definition["key"]]
            component["present"] = True
            component["pods"].append(pod_name)
            component["namespaces"].add(namespace)
            if total == 0 or ready == total:
                component["ready_pods"] += 1
            for image in images:
                tag = _extract_image_tag(image)
                if tag:
                    component["tags"].add(tag)

    return components


def _component_version_row(label: str, tags: set[str], source: str) -> Dict[str, str]:
    if not tags:
        version = "not directly observed"
    elif len(tags) == 1:
        version = next(iter(tags))
    else:
        version = "mixed version evidence"
    return {
        "Component": label,
        "Observed version": version,
        "Source": source,
    }


def _nodes_ready_summary(nodes_text: str) -> str:
    lines = [line for line in nodes_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    if not data_lines:
        return "Node readiness not directly observed"
    ready = 0
    total = 0
    for line in data_lines:
        parts = line.split()
        if len(parts) >= 2:
            total += 1
            if parts[1] == "Ready":
                ready += 1
    return f"Nodes Ready {ready}/{total}" if total else "Node readiness not directly observed"


def _bool_label(value: Any) -> str:
    if value is True:
        return "present"
    if value is False:
        return "absent"
    return "unknown"


def build_networking_panel(state: Dict) -> Dict[str, Any]:
    runtime = state.get("runtime", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    health = state.get("health", {})
    cni_evidence = state.get("evidence", {}).get("cni", {})
    capabilities = cni_evidence.get("capabilities", {})
    policy_presence = cni_evidence.get("policy_presence", {})
    cluster_level = cni_evidence.get("cluster_level", {})
    node_level = cni_evidence.get("node_level", {})
    cluster_footprint = cni_evidence.get("cluster_footprint", {})
    platform_signals = cni_evidence.get("cluster_platform_signals", {}).get("signals", [])
    calico_runtime = cni_evidence.get("calico_runtime", {})
    classification = cni_evidence.get("classification", {})
    cni_version = cni_evidence.get("version", {})
    config_spec_version = cni_evidence.get("config_spec_version", {})

    cni_name = summary_versions.get("cni", "unknown")
    confidence = cni_evidence.get("confidence", "unknown").capitalize()
    status = cni_status_label(state).capitalize()
    classification_label = classification.get("state", "unknown").replace("_", " ")
    policy_supported = _bool_label(capabilities.get("network_policy", None))
    policy_present = {
        "present": "Present",
        "absent": "None detected",
        "unknown": "Unknown",
    }.get(policy_presence.get("status", "unknown"), policy_presence.get("status", "unknown"))

    components = _collect_networking_components(state)
    goldmane_present = components.get("goldmane", {}).get("present", False)
    whisker_present = components.get("whisker", {}).get("present", False)
    if goldmane_present and whisker_present:
        observability = "Goldmane + Whisker available"
    elif goldmane_present:
        observability = "Goldmane available"
    elif whisker_present:
        observability = "Whisker available"
    else:
        observability = "No observability components observed"

    cluster_evidence = []
    if cluster_level.get("cni", "unknown") not in {"", "unknown"}:
        cluster_evidence.append(
            f"Cluster detection identifies {cluster_level.get('cni')} from kube-system pods / daemonsets."
        )
    if cluster_footprint.get("daemonsets"):
        daemonset_bits = []
        for ds in cluster_footprint.get("daemonsets", [])[:3]:
            daemonset_bits.append(f"{ds.get('name')} {ds.get('ready', '?')}/{ds.get('desired', '?')} ready")
        cluster_evidence.append("Daemonsets: " + ", ".join(daemonset_bits))
    if platform_signals:
        cluster_evidence.append("Platform signals: " + ", ".join(platform_signals[:3]))
    if components.get("calico-kube-controllers", {}).get("present"):
        cluster_evidence.append(
            f"calico-kube-controllers running in {', '.join(sorted(components['calico-kube-controllers']['namespaces']))}"
        )
    if components.get("calico-apiserver", {}).get("present"):
        cluster_evidence.append("Calico API server observed")
    if components.get("goldmane", {}).get("present") or components.get("whisker", {}).get("present"):
        cluster_evidence.append(observability)
    if not cluster_evidence:
        cluster_evidence.append("Current cluster-side networking evidence is limited.")

    node_evidence = []
    if node_level.get("cni", "unknown") not in {"", "unknown"}:
        config_detail = node_level.get("selected_file", "") or "recognized config"
        node_evidence.append(
            f"Node config points to {node_level.get('cni')} via {config_detail}."
        )
    else:
        node_evidence.append("Host-level CNI config is not directly observed or not readable.")
    if config_spec_version.get("value", "unknown") not in {"", "unknown"}:
        node_evidence.append(
            f"CNI spec {config_spec_version.get('value')} observed from {config_spec_version.get('file', '(unknown file)')}."
        )
    if calico_runtime.get("status") == "established":
        node_evidence.append(
            f"Direct Calico runtime check shows BGP peers established ({calico_runtime.get('established_peers', 0)})."
        )
    elif calico_runtime.get("status") == "bird_ready_no_established_peer":
        node_evidence.append("Calico runtime check reached BIRD, but no established BGP peers were observed.")
    if classification.get("state") == "stale_interfaces":
        node_evidence.append("Mixed dataplane interfaces are still present on the local node.")
    elif classification.get("state") == "stale_node_config":
        node_evidence.append("Node-level config does not match the current cluster-side CNI footprint.")
    elif not classification.get("notes") and health.get("cni_ok") == "healthy":
        node_evidence.append("No blocking local-node residue is currently highlighted by CNI classification.")

    component_rows = []
    for key in [
        "calico-node",
        "calico-kube-controllers",
        "calico-apiserver",
        "kube-proxy",
        "goldmane",
        "whisker",
        "cilium",
        "cilium-operator",
    ]:
        component = components.get(key, {})
        if not component.get("present") and key not in {"goldmane", "whisker", "calico-apiserver"}:
            continue
        if component.get("present"):
            detail = f"{component.get('ready_pods', 0)} pod(s) ready"
            if component.get("namespaces"):
                detail += f" in {', '.join(sorted(component.get('namespaces', [])))}"
        else:
            detail = "not directly observed"
        component_rows.append(
            {
                "Component": component.get("label", key),
                "Presence": "present" if component.get("present") else "not observed",
                "Detail": detail,
            }
        )

    if "calico ippool present" in [signal.lower() for signal in platform_signals]:
        component_rows.append(
            {
                "Component": "IPPool",
                "Presence": "present",
                "Detail": "Calico IPPool observed from cluster objects",
            }
        )

    version_rows = []
    active_cni_version = cni_version.get("value", "unknown")
    version_rows.append(
        {
            "Component": cni_name.capitalize() if cni_name not in {"", "unknown"} else "Active CNI",
            "Observed version": active_cni_version if active_cni_version not in {"", "unknown"} else "not directly observed",
            "Source": cni_version.get("source", "unknown"),
        }
    )
    for key in ["calico-node", "calico-kube-controllers", "calico-apiserver", "goldmane", "whisker", "kube-proxy"]:
        component = components.get(key, {})
        if component.get("present"):
            version_rows.append(
                _component_version_row(
                    component.get("label", key),
                    component.get("tags", set()),
                    "current pod image tag",
                )
            )

    interpretation = f"{cni_name.capitalize() if cni_name not in {'', 'unknown'} else 'Networking state'}"
    if cni_name not in {"", "unknown"}:
        interpretation = f"{cni_name.capitalize()} is the active CNI"
    if status.lower() == "working":
        interpretation += " and the networking dataplane appears healthy."
    elif status.lower() == "degraded":
        interpretation += " but the networking state is currently degraded."
    elif classification.get("state") == "mixed_or_transitional":
        interpretation += " and the networking state remains mixed."
    else:
        interpretation += " with visibility-limited health."
    if policy_present == "Present":
        interpretation = interpretation[:-1] + ", with policy objects present."
    if goldmane_present or whisker_present:
        interpretation = interpretation[:-1] + f" {observability}."

    overview = {
        "CNI": cni_name.capitalize() if cni_name not in {"", "unknown"} else "Unknown",
        "Confidence": confidence,
        "Status": status,
        "Mode": classification_label.capitalize(),
        "Policy": f"{policy_present} / support {policy_supported}",
        "Observability": observability,
    }

    return {
        "overview": overview,
        "cluster_evidence": cluster_evidence[:4],
        "node_evidence": node_evidence[:4],
        "components": component_rows,
        "versions": version_rows,
        "policy_observability": {
            "Policy support": policy_supported.capitalize(),
            "Policy presence": policy_present,
            "Observability": observability,
            "Node readiness": _nodes_ready_summary(runtime.get("nodes", "")),
        },
        "interpretation": interpretation,
    }
