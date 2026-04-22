from typing import Dict


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
