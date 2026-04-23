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
    classification = cni_evidence.get("classification", {})
    cni_classification_state = classification.get("state", "unknown")
    cluster_footprint = cni_evidence.get("cluster_footprint", {}).get(
        "summary",
        "cluster footprint not directly observed",
    )
    capability_summary = cni_evidence.get("capabilities", {}).get("summary", "unknown")
    node_level_cni = cni_evidence.get("node_level", {}).get("cni", "unknown")
    cluster_level_cni = cni_evidence.get("cluster_level", {}).get("cni", "unknown")
    reconciliation = cni_evidence.get("reconciliation", "unknown")
    health_label = cni_status_label(state)
    parsed_nodes = _parse_node_records(state.get("runtime", {}).get("nodes_json", ""))
    local_node = _normalize_local_node_name(state.get("runtime", {}), parsed_nodes)
    previous_cni = classification.get("previous_detected_cni", "unknown")

    text = f"{cni_display_name} | {health_label} | {cni_confidence} confidence"
    if state.get("health", {}).get("cni_ok") == "healthy" and capability_summary == "policy-capable dataplane likely":
        text = f"{cni_display_name} | working | policy-capable | {cni_confidence} confidence"
    if cni_classification_state == "residual_node_dataplane_state":
        node_label = local_node or "observed node"
        residue_label = previous_cni.capitalize() if previous_cni not in {"", "unknown"} else "previous CNI"
        text = f"{cni_display_name} | working | {node_label} residual {residue_label} artifacts"
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

    if reconciliation == "conflict" and cni_classification_state != "residual_node_dataplane_state":
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


def _html_escape(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


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


def _observed_networking_namespaces(components: Dict[str, Dict[str, Any]]) -> List[str]:
    namespaces = set()
    for component in components.values():
        namespaces.update(component.get("namespaces", set()))
    return sorted(namespace for namespace in namespaces if namespace)


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


def _parse_node_records(nodes_json_text: str) -> List[Dict[str, Any]]:
    data = _parse_json_text(nodes_json_text)
    items = data.get("items", []) if isinstance(data, dict) else []
    nodes = []
    for item in items:
        metadata = item.get("metadata", {}) or {}
        labels = metadata.get("labels", {}) or {}
        status = item.get("status", {}) or {}
        addresses = status.get("addresses", []) or []
        internal_ip = next(
            (address.get("address", "") for address in addresses if address.get("type") == "InternalIP"),
            "",
        )
        role = "worker"
        if "node-role.kubernetes.io/control-plane" in labels:
            role = "control-plane"
        elif "node-role.kubernetes.io/master" in labels:
            role = "control-plane"
        nodes.append(
            {
                "name": metadata.get("name", ""),
                "role": role,
                "internal_ip": internal_ip,
                "pod_cidr": item.get("spec", {}).get("podCIDR", "") or "",
                "pod_cidrs": item.get("spec", {}).get("podCIDRs", []) or [],
            }
        )
    nodes.sort(key=lambda node: (0 if node["role"] == "control-plane" else 1, node["name"]))
    return nodes


def _parse_ready_node_names(nodes_text: str) -> List[str]:
    ready_nodes = []
    lines = [line for line in nodes_text.splitlines() if line.strip()]
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "Ready":
            ready_nodes.append(parts[0])
    return ready_nodes


def _normalize_local_node_name(runtime: Dict[str, Any], parsed_nodes: List[Dict[str, Any]]) -> str:
    hostname = (runtime.get("hostname", "") or "").strip()
    if not hostname:
        return ""
    node_names = [node.get("name", "") for node in parsed_nodes if node.get("name")]
    if hostname in node_names:
        return hostname
    for node_name in node_names:
        if hostname.startswith(node_name) or node_name.startswith(hostname):
            return node_name
    return hostname


def _running_pod_nodes(pods_json_text: str, matches: List[str]) -> List[str]:
    data = _parse_json_text(pods_json_text)
    items = data.get("items", []) if isinstance(data, dict) else []
    nodes = set()
    for item in items:
        metadata = item.get("metadata", {}) or {}
        pod_name = str(metadata.get("name", "")).lower()
        if not any(match in pod_name for match in matches):
            continue
        status = item.get("status", {}) or {}
        if status.get("phase") != "Running":
            continue
        node_name = str((item.get("spec", {}) or {}).get("nodeName", "")).strip()
        if node_name:
            nodes.add(node_name)
    return sorted(nodes)


def build_node_runtime_layer_evidence(state: Dict[str, Any]) -> Dict[str, List[str]]:
    runtime = state.get("runtime", {})
    health = state.get("health", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    cni_evidence = state.get("evidence", {}).get("cni", {})
    classification = cni_evidence.get("classification", {})

    parsed_nodes = _parse_node_records(runtime.get("nodes_json", ""))
    local_node = _normalize_local_node_name(runtime, parsed_nodes)
    ready_nodes = _parse_ready_node_names(runtime.get("nodes", ""))
    cni_name = summary_versions.get("cni", "unknown")
    previous_cni = classification.get("previous_detected_cni", "unknown")

    node_runtime_map: Dict[str, str] = {}
    lines = [line for line in runtime.get("nodes", "").splitlines() if line.strip()]
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 6:
            node_runtime_map[parts[0]] = parts[-1]

    kube_proxy_nodes = _running_pod_nodes(runtime.get("pods_json", ""), ["kube-proxy"])
    cni_agent_match = ["calico-node"] if cni_name == "calico" else ["cilium"] if cni_name == "cilium" else []
    cni_agent_nodes = _running_pod_nodes(runtime.get("pods_json", ""), cni_agent_match) if cni_agent_match else []

    kubelet_lines: List[str] = []
    for node in ready_nodes:
        if node == local_node and health.get("kubelet_ok") is True:
            kubelet_lines.append(f"{node}: running (host observed)")
        elif node == local_node and health.get("kubelet_ok") is False:
            kubelet_lines.append(f"{node}: issue (host observed)")
        else:
            kubelet_lines.append(f"{node}: Ready (cluster observed)")

    kube_proxy_lines = [f"{node}: kube-proxy running" for node in kube_proxy_nodes] or ["kube-proxy not directly observed"]

    cni_lines: List[str] = []
    for node in cni_agent_nodes:
        if (
            node == local_node
            and classification.get("state") == "residual_node_dataplane_state"
            and previous_cni not in {"", "unknown"}
        ):
            cni_lines.append(f"{node}: {cni_name.capitalize()} active; stale {previous_cni.capitalize()} residuals")
        else:
            cni_lines.append(f"{node}: {cni_name.capitalize()} active")
    if not cni_lines:
        cni_lines.append(f"{cni_name.capitalize() if cni_name not in {'', 'unknown'} else 'CNI'} not directly observed per node")

    containerd_lines: List[str] = []
    for node in [node.get("name", "") for node in parsed_nodes if node.get("name")]:
        runtime_label = node_runtime_map.get(node, "")
        if node == local_node and health.get("containerd_ok") is True:
            detail = runtime_label or "containerd"
            containerd_lines.append(f"{node}: running ({detail})")
        elif runtime_label:
            containerd_lines.append(f"{node}: {runtime_label}")
        else:
            containerd_lines.append(f"{node}: runtime not directly observed")

    oci_lines: List[str] = []
    if local_node:
        runc_version = state.get("versions", {}).get("runc", "") or "runc observed on local node"
        oci_lines.append(f"{local_node}: {runc_version}")

    kernel_lines: List[str] = []
    if local_node:
        kernel_version = state.get("versions", {}).get("kernel", "") or "kernel observed on local node"
        kernel_lines.append(f"{local_node}: {kernel_version}")

    infra_lines: List[str] = [f"{node.get('name')}: VM-backed node" for node in parsed_nodes if node.get("name")]

    return {
        "L4.1": kubelet_lines,
        "L4.2": kube_proxy_lines,
        "L4.3": cni_lines,
        "L3": containerd_lines,
        "L2": oci_lines,
        "L1": kernel_lines,
        "L0": infra_lines,
    }


def _parse_application_pods(pods_json_text: str) -> List[Dict[str, Any]]:
    data = _parse_json_text(pods_json_text)
    items = data.get("items", []) if isinstance(data, dict) else []
    excluded_namespaces = {
        "kube-system",
        "calico-system",
        "tigera-operator",
        "kube-public",
        "kube-node-lease",
    }
    pods = []
    for item in items:
        metadata = item.get("metadata", {}) or {}
        namespace = metadata.get("namespace", "")
        if namespace in excluded_namespaces:
            continue
        status = item.get("status", {}) or {}
        if status.get("phase") != "Running":
            continue
        pod_name = metadata.get("name", "")
        node_name = (item.get("spec", {}) or {}).get("nodeName", "")
        pod_ip = status.get("podIP", "")
        pods.append(
            {
                "namespace": namespace,
                "name": pod_name,
                "node": node_name,
                "pod_ip": pod_ip,
            }
        )
    return pods


def _parse_service_records(services_json_text: str) -> List[Dict[str, Any]]:
    data = _parse_json_text(services_json_text)
    items = data.get("items", []) if isinstance(data, dict) else []
    services = []
    for item in items:
        metadata = item.get("metadata", {}) or {}
        spec = item.get("spec", {}) or {}
        cluster_ip = str(spec.get("clusterIP", "")).strip()
        if not cluster_ip or cluster_ip in {"None", "null"}:
            continue
        services.append(
            {
                "namespace": metadata.get("namespace", ""),
                "name": metadata.get("name", ""),
                "cluster_ip": cluster_ip,
                "type": spec.get("type", "ClusterIP"),
            }
        )
    return services


def _detect_local_underlay_interface(network_text: str) -> str:
    candidate = ""
    for line in network_text.splitlines():
        stripped = line.strip()
        if not stripped or ": " not in stripped:
            continue
        iface_name = stripped.split(": ", 1)[1].split(":", 1)[0].split("@", 1)[0]
        lower = iface_name.lower()
        if lower in {"lo", "docker0"}:
            continue
        if lower.startswith(("cali", "cilium", "lxc", "vxlan", "tunl")):
            continue
        if candidate:
            continue
        candidate = iface_name
    return candidate or "host NIC"


def _local_interface_groups(network_text: str) -> Dict[str, List[str]]:
    groups = {
        "cali": [],
        "cilium": [],
        "vxlan": [],
        "tunl": [],
    }
    for line in network_text.splitlines():
        stripped = line.strip()
        if not stripped or ": " not in stripped:
            continue
        iface_name = stripped.split(": ", 1)[1].split(":", 1)[0].split("@", 1)[0]
        lower = iface_name.lower()
        if lower.startswith("cali"):
            groups["cali"].append(iface_name)
        elif lower.startswith(("cilium_host", "cilium_net", "cilium_vxlan")):
            groups["cilium"].append(iface_name)
        elif lower == "vxlan.calico":
            groups["vxlan"].append(iface_name)
        elif lower == "tunl0":
            groups["tunl"].append(iface_name)
    return {key: sorted(set(value)) for key, value in groups.items()}


def _normalize_encapsulation(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "unknown"
    lower = raw.lower()
    if lower in {"none", "never"}:
        return "None"
    if "vxlan" in lower:
        return "VXLAN CrossSubnet" if "cross" in lower else "VXLAN"
    if "ipip" in lower:
        return "IPIP CrossSubnet" if "cross" in lower else "IPIP"
    return raw


def _networking_mode_summary(state: Dict) -> Dict[str, str]:
    runtime = state.get("runtime", {})
    cni_name = state.get("summary", {}).get("versions", {}).get("cni", "unknown")
    calico_runtime = state.get("evidence", {}).get("cni", {}).get("calico_runtime", {})

    installation_json = _parse_json_text(runtime.get("calico_installations_json", ""))
    ippools_json = _parse_json_text(runtime.get("calico_ippools_json", ""))

    encapsulation = "unknown"
    bgp = "unknown"
    dataplane = "unknown"
    cross_subnet = "unknown"

    installation_items = installation_json.get("items", []) if isinstance(installation_json, dict) else []
    ippool_items = ippools_json.get("items", []) if isinstance(ippools_json, dict) else []

    installation = installation_items[0] if installation_items else {}
    install_spec = installation.get("spec", {}) if isinstance(installation, dict) else {}
    calico_network = install_spec.get("calicoNetwork", {}) if isinstance(install_spec, dict) else {}
    install_ip_pools = calico_network.get("ipPools", []) if isinstance(calico_network, dict) else []

    install_encaps = []
    for pool in install_ip_pools:
        if isinstance(pool, dict) and pool.get("encapsulation"):
            install_encaps.append(_normalize_encapsulation(str(pool.get("encapsulation"))))
    if install_encaps:
        unique = sorted(set(install_encaps))
        encapsulation = unique[0] if len(unique) == 1 else "mixed mode evidence"
        cross_subnet = "Enabled" if any("CrossSubnet" in value for value in unique) else "Disabled"

    bgp_value = calico_network.get("bgp") if isinstance(calico_network, dict) else None
    if isinstance(bgp_value, str) and bgp_value.strip():
        bgp = "Disabled" if bgp_value.strip().lower() == "disabled" else "Enabled"
    elif cni_name == "calico" and calico_runtime.get("status") == "established":
        bgp = "Enabled"

    dataplane_value = (
        calico_network.get("linuxDataplane")
        if isinstance(calico_network, dict) and calico_network.get("linuxDataplane")
        else install_spec.get("linuxDataplane")
    )
    if isinstance(dataplane_value, str) and dataplane_value.strip():
        lower = dataplane_value.strip().lower()
        dataplane = "eBPF" if lower in {"bpf", "ebpf"} else dataplane_value.strip().lower()

    if encapsulation == "unknown" and ippool_items:
        vxlan_modes = sorted(
            {
                str((item.get("spec", {}) or {}).get("vxlanMode", "")).strip()
                for item in ippool_items
                if str((item.get("spec", {}) or {}).get("vxlanMode", "")).strip()
            }
        )
        ipip_modes = sorted(
            {
                str((item.get("spec", {}) or {}).get("ipipMode", "")).strip()
                for item in ippool_items
                if str((item.get("spec", {}) or {}).get("ipipMode", "")).strip()
            }
        )
        if any(mode.lower() != "never" for mode in vxlan_modes):
            active = [mode for mode in vxlan_modes if mode.lower() != "never"]
            encapsulation = _normalize_encapsulation(f"vxlan {active[0]}") if len(active) == 1 else "mixed mode evidence"
            cross_subnet = "Enabled" if any("cross" in mode.lower() for mode in active) else "Disabled"
        elif any(mode.lower() != "never" for mode in ipip_modes):
            active = [mode for mode in ipip_modes if mode.lower() != "never"]
            encapsulation = _normalize_encapsulation(f"ipip {active[0]}") if len(active) == 1 else "mixed mode evidence"
            cross_subnet = "Enabled" if any("cross" in mode.lower() for mode in active) else "Disabled"
        elif vxlan_modes or ipip_modes:
            encapsulation = "None"
            cross_subnet = "Disabled"

    return {
        "Encapsulation": encapsulation,
        "BGP": bgp,
        "Dataplane": dataplane,
        "Cross-subnet mode": cross_subnet,
    }


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
    previous_cni = classification.get("previous_detected_cni", "unknown")
    policy_supported = _bool_label(capabilities.get("network_policy", None))
    policy_present = {
        "present": "Present",
        "absent": "None detected",
        "unknown": "Unknown",
    }.get(policy_presence.get("status", "unknown"), policy_presence.get("status", "unknown"))

    components = _collect_networking_components(state)
    networking_namespaces = _observed_networking_namespaces(components)
    parsed_nodes = _parse_node_records(runtime.get("nodes_json", ""))
    local_node = _normalize_local_node_name(runtime, parsed_nodes)
    ready_node_names = []
    for line in runtime.get("nodes", "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "Ready":
            ready_node_names.append(parts[0])
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
        namespace_text = ", ".join(networking_namespaces[:3]) if networking_namespaces else "current cluster namespaces"
        cluster_evidence.append(
            f"Cluster detection identifies {cluster_level.get('cni')} from current pods, daemonsets, and platform objects across {namespace_text}."
        )
    if cluster_footprint.get("daemonsets"):
        daemonset_bits = []
        for ds in cluster_footprint.get("daemonsets", [])[:3]:
            daemonset_bits.append(f"{ds.get('name')} {ds.get('ready', '?')}/{ds.get('desired', '?')} ready")
        cluster_evidence.append("Daemonsets: " + ", ".join(daemonset_bits))
    if networking_namespaces:
        cluster_evidence.append("Observed networking namespaces: " + ", ".join(networking_namespaces[:4]))
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
    direct_node_config_observed = node_level.get("cni", "unknown") not in {"", "unknown"}
    if node_level.get("cni", "unknown") not in {"", "unknown"}:
        config_detail = node_level.get("selected_file", "") or "recognized config"
        node_label = local_node or "observed node"
        node_evidence.append(f"{node_label} config points to {node_level.get('cni')} via {config_detail}.")
    else:
        node_evidence.append(
            "Direct host-level CNI config is not readable here, so node evidence falls back to node readiness, node-local agents, and runtime state."
        )

    if ready_node_names:
        if len(ready_node_names) == 1:
            node_evidence.append(f"Ready node observed: {ready_node_names[0]}.")
        else:
            node_evidence.append("Ready nodes observed: " + ", ".join(ready_node_names[:4]) + ".")

    node_agent_component = None
    if cni_name == "calico":
        node_agent_component = "calico-node"
    elif cni_name == "cilium":
        node_agent_component = "cilium"
    if node_agent_component and components.get(node_agent_component, {}).get("present"):
        pods_json = _parse_json_text(runtime.get("pods_json", ""))
        items = pods_json.get("items", []) if isinstance(pods_json, dict) else []
        agent_nodes = sorted(
            {
                ((item.get("spec", {}) or {}).get("nodeName", "")).strip()
                for item in items
                if node_agent_component in str((item.get("metadata", {}) or {}).get("name", "")).lower()
                and ((item.get("status", {}) or {}).get("phase", "") == "Running")
                and ((item.get("spec", {}) or {}).get("nodeName", "")).strip()
            }
        )
        if agent_nodes:
            node_evidence.append(
                f"Node-local {node_agent_component} pods are running on {', '.join(agent_nodes[:4])}."
            )

    if health.get("kubelet_ok") is True:
        observed_host = local_node or runtime.get("hostname", "").strip()
        if observed_host:
            node_evidence.append(
                f"Host evidence shows kubelet active on {observed_host}, confirming the node agent is up."
            )
        else:
            node_evidence.append("Host evidence shows kubelet active on the observed node.")

    if health.get("containerd_ok") is True:
        observed_host = local_node or runtime.get("hostname", "").strip() or "observed node"
        node_evidence.append(
            f"Host evidence shows containerd active on {observed_host}; this confirms runtime state rather than CNI identity."
        )

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
    if classification.get("state") == "residual_node_dataplane_state" and previous_cni not in {"", "unknown"}:
        node_label = local_node or "observed node"
        node_evidence.append(
            f"{node_label} still shows stale {previous_cni.capitalize()} interfaces/routes, even though {cni_name.capitalize()} is active."
        )
    elif classification.get("state") == "stale_interfaces":
        node_evidence.append("Mixed dataplane interfaces are still present on the local node.")
    elif classification.get("state") == "stale_node_config":
        node_evidence.append("Node-level config does not match the current cluster-side CNI footprint.")
    elif not classification.get("notes") and health.get("cni_ok") == "healthy":
        node_evidence.append("No blocking local-node residue is currently highlighted by CNI classification.")

    if not direct_node_config_observed and parsed_nodes and len(node_evidence) == 1:
        node_evidence.append("Node-side networking evidence is currently limited to cluster-observed node state.")

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
    if classification.get("state") == "residual_node_dataplane_state" and previous_cni not in {"", "unknown"}:
        node_label = local_node or "observed node"
        interpretation += (
            f" and is healthy at cluster level; {node_label} still has stale "
            f"{previous_cni.capitalize()} residual interfaces/routes."
        )
    elif status.lower() == "working":
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
        "Mode": (
            f"{cni_name.capitalize()} active; {local_node or 'observed node'} residual {previous_cni.capitalize()} artifacts"
            if classification.get("state") == "residual_node_dataplane_state" and previous_cni not in {"", "unknown"}
            else classification_label.capitalize()
        ),
        "Policy": f"{policy_present} / support {policy_supported}",
        "Observability": observability,
    }

    return {
        "overview": overview,
        "mode": _networking_mode_summary(state),
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


def build_network_visual_model(state: Dict) -> Dict[str, Any]:
    runtime = state.get("runtime", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    cni_evidence = state.get("evidence", {}).get("cni", {})
    mode = _networking_mode_summary(state)
    components = _collect_networking_components(state)

    nodes = _parse_node_records(runtime.get("nodes_json", ""))
    app_pods = _parse_application_pods(runtime.get("pods_json", ""))
    services = _parse_service_records(runtime.get("services_json", ""))
    local_hostname = runtime.get("hostname", "").strip()
    local_underlay_nic = _detect_local_underlay_interface(runtime.get("network", ""))
    local_ifaces = _local_interface_groups(runtime.get("network", ""))
    routes_text = runtime.get("routes", "")

    node_map = {node["name"]: {**node, "pods": []} for node in nodes}
    for pod in app_pods:
        if pod["node"] in node_map:
            node_map[pod["node"]]["pods"].append(pod)

    ordered_nodes = [node_map[node["name"]] for node in nodes if node["name"] in node_map]
    overlay_label = " / ".join(
        part
        for part in [
            summary_versions.get("cni", "unknown").capitalize() if summary_versions.get("cni", "unknown") not in {"", "unknown"} else "Unknown CNI",
            mode.get("Encapsulation", "unknown"),
        ]
        if part and part != "unknown"
    ) or "Networking overlay not directly observed"
    if mode.get("Cross-subnet mode", "unknown") not in {"", "unknown", "Disabled"}:
        overlay_label += f" ({mode['Cross-subnet mode']})"

    underlay_ips = [node.get("internal_ip", "") for node in ordered_nodes if node.get("internal_ip")]
    pod_cidrs = sorted(
        {
            node.get("pod_cidr", "")
            for node in ordered_nodes
            if node.get("pod_cidr")
        }
    )
    cluster_pod_network = "unknown"
    ippools_json = _parse_json_text(runtime.get("calico_ippools_json", ""))
    for item in (ippools_json.get("items", []) if isinstance(ippools_json, dict) else []):
        cidr = str((item.get("spec", {}) or {}).get("cidr", "")).strip()
        if cidr:
            cluster_pod_network = cidr
            break

    calico_control = []
    for key in ["calico-kube-controllers", "calico-apiserver", "calico-node"]:
        component = components.get(key, {})
        if component.get("present"):
            calico_control.append(component.get("label", key))
    if "calico ippool present" in [signal.lower() for signal in cni_evidence.get("cluster_platform_signals", {}).get("signals", [])]:
        calico_control.append("IPPool")

    policy_observability = []
    if cni_evidence.get("capabilities", {}).get("network_policy") is True:
        policy_observability.append("Policy-capable dataplane")
    if cni_evidence.get("policy_presence", {}).get("status") == "present":
        policy_observability.append("NetworkPolicy objects present")
    if components.get("goldmane", {}).get("present"):
        policy_observability.append("Goldmane")
    if components.get("whisker", {}).get("present"):
        policy_observability.append("Whisker")

    preferred_services = [
        service
        for service in services
        if service["namespace"] not in {"kube-system", "calico-system", "tigera-operator"}
    ]
    if not preferred_services:
        preferred_services = [
            service
            for service in services
            if service["namespace"] in {"default", "kube-system"}
        ]
    preferred_services = sorted(
        preferred_services,
        key=lambda service: (service["namespace"] != "default", service["namespace"], service["name"]),
    )[:4]

    for node in ordered_nodes:
        node["pods"] = sorted(node.get("pods", []), key=lambda pod: (pod["namespace"], pod["name"]))[:4]
        node["is_local_observed"] = local_hostname == node["name"]
        if node["is_local_observed"]:
            if local_ifaces["cali"]:
                host_link = ", ".join(local_ifaces["cali"][:2])
            elif local_ifaces["cilium"]:
                host_link = ", ".join(local_ifaces["cilium"][:2])
            else:
                host_link = "host-side veth / cali* not directly visible"
            node["kernel_chain"] = [
                "pod netns",
                "eth0 in pod",
                host_link,
                f"{mode.get('Dataplane', 'unknown')} routing / forwarding",
                local_underlay_nic,
            ]
            notes = []
            if local_ifaces["vxlan"]:
                notes.append("Observed vxlan.calico on host")
            if local_ifaces["tunl"]:
                notes.append("tunl0 may exist as non-blocking Linux tunnel plumbing")
            if "proto bird" in routes_text:
                notes.append("Routes include proto bird entries")
            node["kernel_notes"] = notes or ["Host interfaces and routes were observed locally."]
        else:
            node["kernel_chain"] = [
                "pod netns",
                "eth0 in pod",
                "host-side veth / cali*",
                f"{mode.get('Dataplane', 'unknown')} routing / forwarding",
                "node NIC",
            ]
            node["kernel_notes"] = ["Remote node kernel view is shown conceptually from current cluster topology."]

    return {
        "headline": {
            "cni": summary_versions.get("cni", "unknown"),
            "overlay": overlay_label,
            "dataplane": mode.get("Dataplane", "unknown"),
            "pod_network": cluster_pod_network,
        },
        "nodes": ordered_nodes,
        "underlay_ips": underlay_ips,
        "pod_cidrs": pod_cidrs,
        "control_plane_components": calico_control,
        "policy_observability": policy_observability,
        "services": preferred_services,
        "mode": mode,
        "cluster_pod_network": cluster_pod_network,
        "assumptions": [
            "Pod netns / veth flow is shown concretely where local host evidence exists and conceptually on remote nodes.",
            "Overlay and pod network labels come from current CNI / IPPool / Installation evidence when directly observed.",
        ],
    }


def render_network_visual_html(model: Dict[str, Any]) -> str:
    headline = model.get("headline", {})
    nodes = model.get("nodes", [])
    control_plane_components = model.get("control_plane_components", [])
    policy_observability = model.get("policy_observability", [])
    services = model.get("services", [])
    underlay_ips = model.get("underlay_ips", [])
    pod_cidrs = model.get("pod_cidrs", [])

    node_cards = []
    for node in nodes:
        pod_lines = "".join(
            (
                f"<div class='netviz-pod'>"
                f"<div class='netviz-pod-name'>{_html_escape(pod['namespace'])}/{_html_escape(pod['name'])}</div>"
                f"<div class='netviz-pod-ip'>{_html_escape(pod.get('pod_ip', 'pod IP unknown') or 'pod IP unknown')}</div>"
                f"</div>"
            )
            for pod in node.get("pods", [])
        ) or "<div class='netviz-empty'>No application pods highlighted on this node.</div>"

        kernel_chain = "".join(
            f"<div class='netviz-chain-step'>{_html_escape(step)}</div>"
            for step in node.get("kernel_chain", [])
        )
        kernel_notes = "".join(
            f"<li>{_html_escape(note)}</li>" for note in node.get("kernel_notes", [])
        )
        role_label = "control plane" if node.get("role") == "control-plane" else "worker"
        observed_badge = "Local host evidence" if node.get("is_local_observed") else "Cluster topology view"
        node_cards.append(
            f"""
            <div class="netviz-node">
              <div class="netviz-node-head">
                <div>
                  <div class="netviz-node-name">{_html_escape(node.get('name', 'node'))}</div>
                  <div class="netviz-node-meta">{_html_escape(role_label)} • {_html_escape(node.get('internal_ip', 'IP unknown'))}</div>
                  <div class="netviz-node-meta">pod CIDR: {_html_escape(node.get('pod_cidr', 'unknown'))}</div>
                </div>
                <div class="netviz-badge">{_html_escape(observed_badge)}</div>
              </div>
              <div class="netviz-subtitle">Workload pod placement</div>
              <div class="netviz-pods">{pod_lines}</div>
              <div class="netviz-subtitle">Kernel / namespace reality</div>
              <div class="netviz-chain">{kernel_chain}</div>
              <ul class="netviz-notes">{kernel_notes}</ul>
            </div>
            """
        )

    control_bits = "".join(
        f"<span class='netviz-chip'>{_html_escape(item)}</span>" for item in control_plane_components
    ) or "<span class='netviz-chip'>No control-plane networking components directly observed</span>"
    policy_bits = "".join(
        f"<span class='netviz-chip netviz-chip-side'>{_html_escape(item)}</span>" for item in policy_observability
    ) or "<span class='netviz-chip netviz-chip-side'>No policy / observability components directly observed</span>"
    underlay_label = " ↔ ".join(_html_escape(ip) for ip in underlay_ips) or "node IPs not directly observed"
    pod_cidr_label = ", ".join(_html_escape(cidr) for cidr in pod_cidrs) or _html_escape(model.get("cluster_pod_network", "unknown"))
    service_network_label = (
        ", ".join(_html_escape(service.get("cluster_ip", "")) for service in services[:3] if service.get("cluster_ip"))
        or "ClusterIP examples not directly observed"
    )

    def _simple_node_label(node: Dict[str, Any], fallback: str) -> str:
        if node.get("role") == "control-plane":
            return "CP"
        if node:
            return "Worker"
        return fallback

    def _icon_card(symbol: str, title: str, subtitle: str = "", extra_class: str = "") -> str:
        return (
            f"<div class='netviz-icon-card {extra_class}'>"
            f"<div class='netviz-icon-symbol'>{_html_escape(symbol)}</div>"
            f"<div class='netviz-icon-title'>{_html_escape(title)}</div>"
            f"<div class='netviz-icon-subtitle'>{_html_escape(subtitle)}</div>"
            f"</div>"
        )

    left_node = nodes[0] if nodes else {}
    right_node = nodes[1] if len(nodes) > 1 else {}
    left_node_label = _simple_node_label(left_node, "Node")
    right_node_label = _simple_node_label(right_node, "Node")
    left_node_icon = _icon_card("node", left_node_label, left_node.get("internal_ip", "IP unknown"))
    right_node_icon = _icon_card("node", right_node_label, right_node.get("internal_ip", "IP unknown"))
    policy_icon = _icon_card("policy", "Policy plane", "Goldmane / Whisker", "netviz-policy-card")

    service_icons = "".join(
        _icon_card(
            "svc",
            service.get("name", "service"),
            service.get("cluster_ip", "ClusterIP unknown"),
        )
        for service in services[:3]
    ) or "<div class='netviz-empty'>No ClusterIP services highlighted.</div>"
    left_pod_icons = "".join(
        _icon_card("pod", pod.get("name", "pod"), pod.get("pod_ip", "pod IP unknown") or "pod IP unknown")
        for pod in left_node.get("pods", [])[:2]
    ) or "<div class='netviz-empty'>No highlighted pods.</div>"
    right_pod_icons = "".join(
        _icon_card("pod", pod.get("name", "pod"), pod.get("pod_ip", "pod IP unknown") or "pod IP unknown")
        for pod in right_node.get("pods", [])[:2]
    ) or "<div class='netviz-empty'>No highlighted pods.</div>"

    left_node_html = node_cards[0] if node_cards else ""
    right_node_html = node_cards[1] if len(node_cards) > 1 else ""
    extra_nodes_html = "".join(node_cards[2:]) if len(node_cards) > 2 else ""

    return f"""
    <style>
      .netviz-root {{
        background: #11151b;
        border: 1px solid #2d3748;
        border-radius: 12px;
        padding: 14px;
        color: #e5e7eb;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      }}
      .netviz-strip {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin-bottom: 12px;
      }}
      .netviz-box {{
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 10px;
        background: #151a22;
      }}
      .netviz-label {{
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #94a3b8;
        margin-bottom: 4px;
      }}
      .netviz-value {{
        font-size: 15px;
        font-weight: 700;
        color: #f8fafc;
      }}
      .netviz-bands {{
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 12px;
        margin-bottom: 12px;
      }}
      .netviz-band-title {{
        font-size: 12px;
        font-weight: 700;
        color: #bfdbfe;
        margin-bottom: 8px;
      }}
      .netviz-chip {{
        display: inline-block;
        border: 1px solid #35506b;
        border-radius: 999px;
        padding: 4px 8px;
        margin: 0 6px 6px 0;
        background: #17212b;
        font-size: 12px;
      }}
      .netviz-chip-side {{
        border-color: #3f5f52;
        background: #15221d;
      }}
      .netviz-overlay {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        border: 1px dashed #60a5fa;
        border-radius: 10px;
        padding: 10px 12px;
        margin-bottom: 12px;
        background: #0f1724;
      }}
      .netviz-overlay-arrow {{
        flex: 1;
        border-top: 2px solid #60a5fa;
        position: relative;
        height: 2px;
      }}
      .netviz-overlay-arrow::after {{
        content: "";
        position: absolute;
        right: -1px;
        top: -5px;
        border-left: 8px solid #60a5fa;
        border-top: 6px solid transparent;
        border-bottom: 6px solid transparent;
      }}
      .netviz-main {{
        display: grid;
        grid-template-columns: minmax(240px, 1fr) minmax(240px, 1fr) minmax(240px, 1fr);
        gap: 14px;
        align-items: start;
      }}
      .netviz-addressing {{
        margin-top: 16px;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 12px;
        background: #141922;
      }}
      .netviz-addressing-title {{
        font-size: 13px;
        font-weight: 700;
        color: #bfdbfe;
        margin-bottom: 8px;
      }}
      .netviz-layer-diagram {{
        display: grid;
        gap: 10px;
      }}
      .netviz-layer {{
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 10px;
        background: #151a22;
      }}
      .netviz-layer-row {{
        display: grid;
        grid-template-columns: 140px 1fr;
        gap: 10px;
        align-items: center;
      }}
      .netviz-layer-name {{
        font-size: 12px;
        font-weight: 700;
        color: #cbd5e1;
      }}
      .netviz-layer-network {{
        font-size: 12px;
        color: #94a3b8;
        margin-top: 2px;
      }}
      .netviz-icons {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
      }}
      .netviz-icon-group {{
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .netviz-icon-card {{
        border: 1px solid #475569;
        border-radius: 10px;
        padding: 8px 10px;
        background: #101723;
        min-width: 96px;
        text-align: center;
      }}
      .netviz-icon-symbol {{
        font-size: 18px;
        line-height: 1;
      }}
      .netviz-icon-title {{
        font-size: 12px;
        color: #f8fafc;
        margin-top: 4px;
      }}
      .netviz-icon-subtitle {{
        font-size: 11px;
        color: #93c5fd;
        margin-top: 2px;
      }}
      .netviz-connector {{
        flex: 1;
        border-top: 2px solid #64748b;
        min-width: 18px;
        opacity: 0.8;
      }}
      .netviz-policy-card {{
        border-color: #35506b;
        background: #121924;
      }}
      .netviz-node {{
        border: 1px solid #334155;
        border-radius: 12px;
        background: #151a22;
        padding: 12px;
        width: 100%;
        box-sizing: border-box;
      }}
      .netviz-node-head {{
        display: flex;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 10px;
      }}
      .netviz-node-name {{
        font-size: 16px;
        font-weight: 700;
        color: #f8fafc;
      }}
      .netviz-node-meta {{
        font-size: 12px;
        color: #94a3b8;
      }}
      .netviz-badge {{
        border: 1px solid #475569;
        border-radius: 999px;
        padding: 4px 8px;
        height: fit-content;
        font-size: 11px;
        color: #cbd5e1;
      }}
      .netviz-subtitle {{
        font-size: 12px;
        font-weight: 700;
        color: #cbd5e1;
        margin: 8px 0 6px;
      }}
      .netviz-pods {{
        display: grid;
        gap: 6px;
      }}
      .netviz-pod {{
        border-left: 3px solid #34d399;
        background: #111827;
        border-radius: 8px;
        padding: 7px 9px;
      }}
      .netviz-pod-name {{
        font-size: 12px;
        color: #f8fafc;
      }}
      .netviz-pod-ip {{
        font-size: 12px;
        color: #93c5fd;
      }}
      .netviz-empty {{
        font-size: 12px;
        color: #94a3b8;
      }}
      .netviz-chain {{
        display: flex;
        align-items: stretch;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .netviz-chain-step {{
        position: relative;
        border: 1px solid #475569;
        border-radius: 8px;
        background: #101723;
        padding: 8px 10px;
        font-size: 12px;
        color: #e2e8f0;
      }}
      .netviz-chain-step:not(:last-child)::after {{
        content: "→";
        position: absolute;
        right: -12px;
        top: 50%;
        transform: translateY(-50%);
        color: #60a5fa;
        font-weight: 700;
      }}
      .netviz-notes {{
        margin: 8px 0 0 16px;
        padding: 0;
        color: #94a3b8;
        font-size: 12px;
      }}
      .netviz-sideplane {{
        border: 1px solid #35506b;
        border-radius: 12px;
        background: #121924;
        padding: 12px;
        min-height: 100%;
      }}
      .netviz-sideplane-title {{
        font-size: 13px;
        font-weight: 700;
        color: #bfdbfe;
        margin-bottom: 8px;
      }}
      .netviz-footnote {{
        margin-top: 10px;
        font-size: 12px;
        color: #94a3b8;
      }}
      .netviz-extra-nodes {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 12px;
        margin-top: 14px;
      }}
    </style>
    <div class="netviz-root">
      <div class="netviz-strip">
        <div class="netviz-box"><div class="netviz-label">Active CNI</div><div class="netviz-value">{_html_escape(headline.get('cni', 'unknown'))}</div></div>
        <div class="netviz-box"><div class="netviz-label">Overlay</div><div class="netviz-value">{_html_escape(headline.get('overlay', 'unknown'))}</div></div>
        <div class="netviz-box"><div class="netviz-label">Dataplane</div><div class="netviz-value">{_html_escape(headline.get('dataplane', 'unknown'))}</div></div>
        <div class="netviz-box"><div class="netviz-label">Cluster pod network</div><div class="netviz-value">{_html_escape(headline.get('pod_network', 'unknown'))}</div></div>
      </div>
      <div class="netviz-bands">
        <div class="netviz-box">
          <div class="netviz-band-title">Control / configuration plane</div>
          {control_bits}
        </div>
        <div class="netviz-box">
          <div class="netviz-band-title">Addressing context</div>
          <div class="netviz-chip">Underlay node IPs: {underlay_label}</div>
          <div class="netviz-chip">Per-node pod CIDRs: {pod_cidr_label}</div>
        </div>
      </div>
      <div class="netviz-overlay">
        <div>
          <div class="netviz-label">Overlay / node-to-node packet path</div>
          <div class="netviz-value">{_html_escape(headline.get('overlay', 'unknown'))}</div>
        </div>
        <div class="netviz-overlay-arrow"></div>
        <div>
          <div class="netviz-label">Underlay transport</div>
          <div class="netviz-value">{underlay_label}</div>
        </div>
      </div>
      <div class="netviz-main">
        <div>{left_node_html}</div>
        <div class="netviz-sideplane">
          <div class="netviz-sideplane-title">Policy + observability plane</div>
          {policy_bits}
          <div class="netviz-footnote">This plane sits between nodes and pods to show where policy intent and flow visibility overlay the dataplane without changing CNI identity.</div>
        </div>
        <div>{right_node_html}</div>
      </div>
      {"<div class='netviz-extra-nodes'>" + extra_nodes_html + "</div>" if extra_nodes_html else ""}
      <div class="netviz-addressing">
        <div class="netviz-addressing-title">Network addressing diagram</div>
        <div class="netviz-layer-diagram">
          <div class="netviz-layer">
            <div class="netviz-layer-row">
              <div>
                <div class="netviz-layer-name">Services network</div>
                <div class="netviz-layer-network">{service_network_label}</div>
              </div>
              <div class="netviz-icons">{service_icons}</div>
            </div>
          </div>
          <div class="netviz-layer">
            <div class="netviz-layer-row">
              <div>
                <div class="netviz-layer-name">Pod network</div>
                <div class="netviz-layer-network">{pod_cidr_label}</div>
              </div>
              <div class="netviz-icons">
                <div class="netviz-icon-group">{left_pod_icons}</div>
                <div class="netviz-connector"></div>
                {policy_icon}
                <div class="netviz-connector"></div>
                <div class="netviz-icon-group">{right_pod_icons}</div>
              </div>
            </div>
          </div>
          <div class="netviz-layer">
            <div class="netviz-layer-row">
              <div>
                <div class="netviz-layer-name">Node network</div>
                <div class="netviz-layer-network">{underlay_label}</div>
              </div>
              <div class="netviz-icons">
                {left_node_icon}
                <div class="netviz-connector"></div>
                <div class="netviz-icon-card netviz-policy-card">
                  <div class="netviz-icon-symbol">flow</div>
                  <div class="netviz-icon-title">Observed flow plane</div>
                  <div class="netviz-icon-subtitle">{_html_escape(headline.get('overlay', 'unknown'))}</div>
                </div>
                <div class="netviz-connector"></div>
                {right_node_icon}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="netviz-footnote">
        { _html_escape(model.get("assumptions", [""])[0]) }<br/>
        { _html_escape(model.get("assumptions", ["", ""])[1]) }
      </div>
    </div>
    """
