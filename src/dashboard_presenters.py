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
