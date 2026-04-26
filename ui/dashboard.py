import streamlit as st
import sys
import os
import json
from datetime import datetime

# Allow imports from ../src
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from state_collector import collect_state
from dashboard_presenters import (
    build_node_runtime_layer_evidence,
    build_networking_panel,
    build_network_visual_model,
    cni_config_spec_display,
    cni_status_label,
    cni_summary_text,
    render_network_visual_html,
)
from agent import ask_llm
from command_boundaries import format_boundary_commands_html, format_boundary_commands_text
from els_model import ELS_LAYERS
from lessons import (
    append_coach_audit,
    build_lesson_run,
    default_lesson_progress,
    ensure_initial_lesson_audit,
    lesson_catalog,
    step_status_badge,
    step_status_icon,
)

ALLOW_HOST_EVIDENCE = "--allow-host-evidence" in sys.argv[1:]

st.set_page_config(layout="wide")
st.title("🧠 CKA Coach — ELS Console")
st.subheader("Everything Lives Somewhere...")
st.caption("A layered Kubernetes learning console powered by structured evidence, the ELS model, and AI explanation.")

# --------------------------
# Retro Styling
# --------------------------
# We render the ELS layer table as custom HTML so we can keep the
# retro terminal aesthetic and fine-grained layout control.
table_html = """
<style>
body {
    background-color: black;
    color: #00ff00;
    font-family: monospace;
}

.els-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
}

.els-table th, .els-table td {
    border: 1px solid #00ff00;
    padding: 6px;
    vertical-align: top;
    font-size: 12px;
    color: #00ff00;
    word-wrap: break-word;
    overflow-wrap: break-word;
}

.els-table th {
    background-color: #001100;
    text-align: left;
}

.layer-name {
    font-weight: bold;
}

.small {
    font-size: 11px;
    opacity: 0.9;
}

.detail-note {
    font-size: 12px;
    color: #475569;
}

.cmd-group {
    margin-bottom: 6px;
}

.cmd-boundary {
    font-weight: bold;
    color: #8aff8a;
    margin-bottom: 2px;
}

.cmd-item {
    padding-left: 10px;
    white-space: pre-wrap;
}

.family-legend {
    display: flex;
    gap: 12px;
    margin: 8px 0 10px;
    flex-wrap: wrap;
    font-size: 12px;
}

.family-chip {
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid #1f2937;
}

.family-blue {
    background: #0b2a4a;
    color: #93c5fd;
}

.family-green {
    background: #12351d;
    color: #86efac;
}

.family-orange {
    background: #4a2a0b;
    color: #fdba74;
}

.family-alert {
    background: #4a2323;
    color: #fca5a5;
}

.plane-separator td {
    height: 10px;
    padding: 0;
    border: none;
    background: #05070b;
}

.plane-label-cell {
    width: 34px;
    min-width: 34px;
    text-align: center;
    padding: 0;
}

.plane-label {
    writing-mode: vertical-rl;
    text-orientation: mixed;
    transform: rotate(180deg);
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 0.4px;
    margin: 0 auto;
    line-height: 1.1;
}

.plane-blue {
    color: #93c5fd;
}

.plane-green {
    color: #86efac;
}

.plane-orange {
    color: #fdba74;
}
</style>
"""

# --------------------------
# Controls
# --------------------------
# These are lightweight dashboard controls.
# Auto Refresh is currently just a placeholder toggle for future expansion.
col1, col2, col3 = st.columns([1, 1, 2])

auto_refresh = col1.checkbox("Auto Refresh", value=False)
interval = col2.slider("Refresh Interval (sec)", 2, 30, 5)

if col3.button("Refresh Now"):
    st.rerun()

# --------------------------
# Helpers
# --------------------------
def clean_json(response: str) -> str:
    """
    Strip markdown code fences from a model response if they exist.

    The agent now tries to return raw JSON only, but this helper is still
    useful as a defensive fallback for older/bad responses.
    """
    if "```" in response:
        parts = response.split("```")
        if len(parts) > 1:
            response = parts[1].replace("json", "").strip()
    return response


def normalize_explanation_output(explanation):
    """
    Normalize ask_llm() output into a dashboard-friendly dict.

    Supports:
    - dict output (preferred current path)
    - JSON string output
    - fenced ```json ... ``` output
    - raw text fallback
    """
    if isinstance(explanation, dict):
        return explanation

    if not isinstance(explanation, str):
        return {"error": f"Unexpected response type: {type(explanation).__name__}"}

    cleaned = clean_json(explanation)

    try:
        return json.loads(cleaned)
    except Exception:
        return {"raw_text": explanation}


def render_guided_plan(plan):
    for idx, step in enumerate(plan, start=1):
        title = step.get("title", f"Step {idx}")
        st.markdown(f"**Step {idx}: {title}**")
        st.markdown(f"Why: {step.get('why', '')}")
        commands = step.get("commands", [])
        if commands:
            st.markdown("Commands:")
            for command in commands:
                st.code(command, language="bash")
        st.markdown(f"Interpretation: {step.get('interpretation', '')}")


def render_lesson_step_tracker(steps, current_step_index: int):
    for idx, step in enumerate(steps, start=1):
        status = step.get("status", "not_started")
        prefix = "👉 " if idx - 1 == current_step_index and status != "completed" else ""
        st.markdown(
            f"{prefix}{step_status_icon(status)} **Step {idx}: {step.get('title', '')}**"
            f"  \n{step_status_badge(status)}"
        )


def lesson_table_value(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def layer_family(key: str) -> str:
    if key in {"L9", "L8", "L7"}:
        return "blue"
    if key in {"L6", "L5", "L4.5"}:
        return "green"
    return "orange"


def summarize_current_evidence(state: dict, key: str) -> str:
    summary = summarize(state)
    current, _ = summary.get(key, ("...", True))
    return current


def render_networking_kv_cards(
    title: str,
    items: dict,
    columns: int,
    value_as_markdown: bool = True,
):
    st.markdown(f"**{title}**")
    entries = list(items.items())
    for start in range(0, len(entries), columns):
        row_items = entries[start : start + columns]
        row_cols = st.columns(columns)
        for idx, column in enumerate(row_cols):
            with column:
                if idx < len(row_items):
                    label, value = row_items[idx]
                    with st.container(border=True):
                        st.caption(label)
                        if value_as_markdown:
                            st.markdown(f"**{value}**")
                        else:
                            st.write(value)
                else:
                    st.empty()


def summarize(state: dict) -> dict:
    """
    Build the "Current" summary values shown in the ELS table.

    This is not the full ELS reasoning engine. It is simply a compact
    operator-style summary of the current collected cluster state.
    """
    runtime = state.get("runtime", {})
    health = state.get("health", {})
    versions = state.get("versions", {})
    summary_state = state.get("summary", {})
    summary_versions = summary_state.get("versions", {})
    node_layer_evidence = build_node_runtime_layer_evidence(state)

    pods_text = runtime.get("pods", "")
    pod_lines = [l for l in pods_text.splitlines() if l.strip()]
    data_lines = pod_lines[1:] if len(pod_lines) > 1 else []

    total_pods = len(data_lines)
    namespace_counts = {}
    for line in data_lines:
        parts = line.split()
        if not parts:
            continue
        namespace = parts[0]
        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1
    pending_pods = sum(1 for l in data_lines if " Pending " in f" {l} ")
    crashloop_pods = sum(1 for l in data_lines if "CrashLoopBackOff" in l)
    operator_pods = []
    for line in data_lines:
        parts = line.split()
        if len(parts) >= 2 and "operator" in parts[1].lower():
            operator_pods.append(parts[1])

    daemonsets_text = runtime.get("daemonsets", "")
    daemonset_lines = [line for line in daemonsets_text.splitlines() if line.strip()]
    daemonset_data_lines = daemonset_lines[1:] if len(daemonset_lines) > 1 else []
    daemonset_names = [line.split()[1] for line in daemonset_data_lines if len(line.split()) >= 2]
    daemonset_count = len(daemonset_names)
    daemonset_preview = ", ".join(daemonset_names[:3]) if daemonset_names else "none directly observed"
    deployments_text = runtime.get("deployments", "")
    deployment_lines = [line for line in deployments_text.splitlines() if line.strip()]
    deployment_data_lines = deployment_lines[1:] if len(deployment_lines) > 1 else []
    deployment_names = [line.split()[1] for line in deployment_data_lines if len(line.split()) >= 2]
    deployment_count = len(deployment_names)
    deployment_preview = ", ".join(deployment_names[:4]) if deployment_names else "none directly observed"
    operator_preview = ", ".join(operator_pods[:3]) if operator_pods else "none directly observed"
    namespace_summary = ", ".join(
        f"{namespace} {count}"
        for namespace, count in sorted(namespace_counts.items())
    ) or "no namespaces observed"

    kubelet_ok = health.get("kubelet_ok", None)
    kubelet_transitional_note = health.get("kubelet_transitional_note", "")
    containerd_ok = health.get("containerd_ok", None)
    containerd_transitional_note = health.get("containerd_transitional_note", "")

    cni_name = summary_versions.get("cni", versions.get("cni", ""))
    kernel_ver = versions.get("kernel", "")
    kubelet_ver = versions.get("kubelet", "")
    runc_ver = versions.get("runc", "")
    api_ver = versions.get("api", "")
    cni_evidence = state.get("evidence", {}).get("cni", {})
    cluster_footprint = cni_evidence.get("cluster_footprint", {}).get("summary", "cluster footprint not directly observed")
    policy_status = cni_evidence.get("policy_presence", {}).get("status", "unknown")
    cni_confidence = cni_evidence.get("confidence", "unknown")
    cni_classification_state = cni_evidence.get("classification", {}).get("state", "unknown")
    node_level_cni = cni_evidence.get("node_level", {}).get("cni", "unknown")
    cluster_level_cni = cni_evidence.get("cluster_level", {}).get("cni", "unknown")
    reconciliation = cni_evidence.get("reconciliation", "unknown")
    policy_label = {
        "present": "present",
        "absent": "none detected",
        "unknown": "unknown",
    }.get(policy_status, policy_status)

    cni_summary_line = cni_summary_text(state)
    kubelet_text = "<br>".join(node_layer_evidence.get("L4.1", [])) or "kubelet status unknown"
    kube_proxy_text = "<br>".join(node_layer_evidence.get("L4.2", [])) or "kube-proxy not directly observed"
    cni_text = cni_summary_line
    cni_node_lines = node_layer_evidence.get("L4.3", [])
    if cni_node_lines:
        cni_text = f"{cni_summary_line}<br>{'<br>'.join(cni_node_lines)}"
    containerd_text = "<br>".join(node_layer_evidence.get("L3", [])) or "containerd status unknown"
    oci_text = "<br>".join(node_layer_evidence.get("L2", [])) or (runc_ver or "runc version unknown")
    kernel_text = "<br>".join(node_layer_evidence.get("L1", [])) or f"kernel {kernel_ver or 'unknown'}"
    infra_text = "<br>".join(node_layer_evidence.get("L0", [])) or "VM / virtual hardware"

    return {
        "L9": ("User workloads present", True),
        "L8": (
            f"{total_pods} pods | {namespace_summary}"
            + (f" | Pending={pending_pods}" if pending_pods else "")
            + (f" | CrashLoop={crashloop_pods}" if crashloop_pods else ""),
            not (health.get("pods_pending", False) or health.get("pods_crashloop", False)),
        ),
        "L7": ("Desired-state objects in API", True),
        "L4.5": (f"API server / etcd | {api_ver or 'unknown'}", True),
        "L6": (
            f"Operators: {operator_preview}"
            + (f" | count={len(operator_pods)}" if operator_pods else ""),
            True,
        ),
        "L5": (
            f"Controllers: ds={daemonset_count}, deploy={deployment_count} | DS: {daemonset_preview} | Deploy: {deployment_preview}",
            True,
        ),
        "L4.1": (kubelet_text, kubelet_ok is True),
        "L4.2": (kube_proxy_text, True),
        "L4.3": (cni_text, True),
        "L3": (containerd_text, containerd_ok is True),
        "L2": (oci_text, True),
        "L1": (kernel_text, True),
        "L0": (infra_text, True),
    }


def map_versions_to_layers(state: dict) -> dict:
    """
    Map version strings to visible ELS table rows.
    """
    v = state.get("versions", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    cni_name = summary_versions.get("cni", v.get("cni", ""))
    cni_version = summary_versions.get("cni_version", "unknown")
    cni_config_spec_version = summary_versions.get("cni_config_spec_version", "unknown")
    return {
        "L9": "",
        "L8": "",
        "L7": v.get("api", ""),
        "L6": v.get("api", ""),
        "L5": v.get("api", ""),
        "L4.5": v.get("api", ""),
        "L4.1": v.get("kubelet", ""),
        "L4.2": v.get("api", ""),
        "L4.3": (
            f"{cni_name} | v{cni_version}"
            if cni_name and cni_name != "unknown" and cni_version not in {"", "unknown"}
            else (
                f"{cni_name} | cniSpec {cni_config_spec_version}"
                if cni_name and cni_name != "unknown" and cni_config_spec_version not in {"", "unknown"}
                else cni_name
            )
        ),
        "L3": v.get("containerd", ""),
        "L2": v.get("runc", ""),
        "L1": v.get("kernel", ""),
        "L0": "",
    }


def format_cni_detection_evidence(state: dict) -> str:
    """
    Render auditable CNI detection evidence for the L4.3 expand view.
    """
    runtime = state.get("runtime", {})
    versions = state.get("versions", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    detection = state.get("evidence", {}).get("cni", {})

    node_level = detection.get("node_level", {})
    cluster_level = detection.get("cluster_level", {})
    capabilities = detection.get("capabilities", {})
    cluster_footprint = detection.get("cluster_footprint", {})
    calico_runtime = detection.get("calico_runtime", {})
    classification = detection.get("classification", {})
    event_history = detection.get("event_history", {})
    provenance = detection.get("provenance", {})
    policy_presence = detection.get("policy_presence", {})
    version = detection.get("version", {})
    config_spec_version = detection.get("config_spec_version", {})
    config_content = detection.get("config_content", "")
    migration_note = detection.get("migration_note", "unknown")

    filenames = node_level.get("filenames", [])
    filename_text = "\n".join(filenames) if filenames else "(none found)"
    selected_file = node_level.get("selected_file", "") or "(none)"
    config_dir = node_level.get("config_dir", "/etc/cni/net.d")
    directory_status = node_level.get("directory_status", "directory_missing")
    matched_pods = cluster_level.get("matched_pods", [])
    matched_pod_text = "\n".join(matched_pods) if matched_pods else "(none found)"
    selected_pod = cluster_level.get("selected_pod", "") or "(none)"
    confidence = detection.get("confidence", "low")
    reconciliation = detection.get("reconciliation", "unknown")
    cni_name = summary_versions.get("cni", versions.get("cni", "")) or "unknown"
    policy_label = {
        "present": "present",
        "absent": "none detected",
        "unknown": "unknown",
    }.get(policy_presence.get("status", "unknown"), policy_presence.get("status", "unknown"))

    return (
        "[cni detection]\n"
        f"detected cni: {cni_name}\n"
        f"confidence: {confidence}\n"
        f"reconciliation: {reconciliation}\n\n"
        "[node-level detection]\n"
        f"detected cni: {node_level.get('cni', 'unknown')}\n"
        f"confidence: {node_level.get('confidence', 'low')}\n"
        f"host evidence enabled: {node_level.get('host_evidence_enabled', False)}\n"
        f"config directory used: {config_dir}\n"
        f"config directory source: {node_level.get('config_dir_source', 'default')}\n"
        f"config directory status: {directory_status}\n"
        f"configured override ignored: {node_level.get('configured_override_ignored', False)}\n"
        f"selected file: {selected_file}\n"
        "files in configured CNI directory:\n"
        f"{filename_text}\n\n"
        "[cluster-level detection]\n"
        f"detected cni: {cluster_level.get('cni', 'unknown')}\n"
        f"confidence: {cluster_level.get('confidence', 'low')}\n"
        f"selected pod: {selected_pod}\n"
        "matched kube-system pods:\n"
        f"{matched_pod_text}\n\n"
        "[capability inference]\n"
        f"summary: {capabilities.get('summary', 'unknown')}\n"
        f"network policy: {capabilities.get('network_policy', 'unknown')}\n"
        f"policy model: {capabilities.get('policy_model', 'unknown')}\n"
        f"policy support: {capabilities.get('policy_support', 'unknown')}\n"
        f"observability: {capabilities.get('observability', 'unknown')}\n"
        f"inference basis: {capabilities.get('inference_basis', 'unknown')}\n\n"
        "[cluster footprint]\n"
        f"summary: {cluster_footprint.get('summary', 'cluster footprint not directly observed')}\n"
        f"operator present: {cluster_footprint.get('operator_present', False)}\n"
        f"daemonset count: {cluster_footprint.get('daemonset_count', 0)}\n"
        f"daemonsets: {json.dumps(cluster_footprint.get('daemonsets', []), indent=2)}\n\n"
        "[platform signals]\n"
        f"signals: {json.dumps(cluster_footprint.get('platform_signals', []), indent=2)}\n\n"
        "[direct evidence entry points]\n"
        "cluster: kubectl get pods -n kube-system\n"
        "cluster: kubectl get ds -n kube-system\n"
        "node: ls /etc/cni/net.d/\n"
        "node: cat /etc/cni/net.d/<config>\n"
        "node: ip route\n\n"
        "[normalized classification]\n"
        f"state: {classification.get('state', 'unknown')}\n"
        f"reason: {classification.get('reason', 'unknown')}\n"
        f"notes: {json.dumps(classification.get('notes', []), indent=2)}\n"
        f"previous detected cni: {classification.get('previous_detected_cni', 'unknown')}\n\n"
        "[provenance]\n"
        f"available: {provenance.get('available', False)}\n"
        f"current detected cni: {provenance.get('current_detected_cni', 'unknown')}\n"
        f"previous detected cni: {provenance.get('previous_detected_cni', 'unknown')}\n"
        f"last cleaned at: {provenance.get('last_cleaned_at', '') or '(unknown)'}\n"
        f"cleaned by: {provenance.get('cleaned_by', '') or '(unknown)'}\n"
        f"last install observed at: {provenance.get('last_install_observed_at', '') or '(unknown)'}\n"
        f"evidence basis: {provenance.get('evidence_basis', 'unknown')}\n\n"
        "[historical events / recent transitions]\n"
        f"summary: {event_history.get('summary', 'no relevant CNI event history collected')}\n"
        f"relevant lines: {json.dumps(event_history.get('relevant_lines', []), indent=2)}\n\n"
        "[calico runtime evidence]\n"
        f"summary: {calico_runtime.get('summary', 'not applicable for current CNI')}\n"
        f"status: {calico_runtime.get('status', 'unknown')}\n"
        f"pod: {calico_runtime.get('pod', '') or '(none)'}\n"
        f"bird ready: {calico_runtime.get('bird_ready', False)}\n"
        f"established peers: {calico_runtime.get('established_peers', 0)}\n"
        f"protocol lines: {json.dumps(calico_runtime.get('protocol_lines', []), indent=2)}\n\n"
        "[version evidence]\n"
        f"observed version: {version.get('value', 'unknown')}\n"
        f"source: {version.get('source', 'unknown')}\n"
        f"pod: {version.get('pod', '') or '(none)'}\n"
        f"image: {version.get('image', '') or '(none)'}\n\n"
        "[cni config spec evidence]\n"
        f"observed cniVersion: {config_spec_version.get('value', 'unknown')}\n"
        f"source: {config_spec_version.get('source', 'unknown')}\n"
        f"file: {config_spec_version.get('file', '') or '(none)'}\n"
        "selected config content:\n"
        f"{config_content or '(none)'}\n\n"
        "[policy presence summary]\n"
        f"status: {policy_label}\n"
        f"count: {policy_presence.get('count', 0)}\n"
        f"namespaces: {', '.join(policy_presence.get('namespaces', [])) or '(none)'}\n\n"
        "[migration or reconciliation note]\n"
        f"{migration_note}\n\n"
        "[node network evidence]\n"
        f"{runtime.get('network', '')}\n\n{runtime.get('routes', '')}"
    ).strip()


def get_expand_text(key: str, state: dict) -> str:
    """
    Return the raw evidence block for the chosen visible row.

    This is what the student sees when they expand a layer. It is useful
    as a low-level inspection view beside the higher-level ELS explanation.
    """
    runtime = state.get("runtime", {})
    versions = state.get("versions", {})
    health = state.get("health", {})

    mapping = {
        "L8": runtime.get("pods", ""),
        "L7": runtime.get("events", ""),
        "L4.5": versions.get("k8s_json", ""),
        "L5": runtime.get("processes", ""),
        "L4.1": runtime.get("kubelet", ""),
        "L4.2": runtime.get("nodes", ""),
        "L4.3": format_cni_detection_evidence(state),
        "L3": runtime.get("containerd", "") + "\n\n" + runtime.get("containers", ""),
        "L2": versions.get("runc", ""),
        "L1": runtime.get("network", "") + "\n\n" + versions.get("kernel", ""),
        "L0": runtime.get("nodes", ""),
    }

    return mapping.get(key, json.dumps({
        "versions": versions,
        "health": health,
    }, indent=2))

def render_architecture_panel():
    """
    Render a simple architecture diagram / mental model above the ELS table.

    Use components.html() instead of st.markdown(..., unsafe_allow_html=True)
    because this block is complex enough that Streamlit markdown may partially
    render or leak raw HTML tags.
    """
    st.markdown("## How cka-coach works")
    st.caption(
        "Gen2 architecture: deterministic ELS model + structured state collection + AI explanation layer"
    )

    architecture_html = """
    <html>
    <head>
    <style>
    body {
        margin: 0;
        font-family: Arial, sans-serif;
        background: #f7fffc;
    }

    .arch-wrap {
        border: 1px solid #00aa88;
        border-radius: 10px;
        padding: 14px;
        background: #f7fffc;
        box-sizing: border-box;
    }

    .arch-grid {
        display: grid;
        grid-template-columns: 1fr 80px 1.2fr 80px 1fr;
        gap: 10px;
        align-items: center;
        margin-top: 10px;
        margin-bottom: 14px;
    }

    .arch-box {
        border: 2px solid #0f766e;
        border-radius: 12px;
        padding: 12px;
        background: white;
        min-height: 110px;
        box-sizing: border-box;
    }

    .arch-title {
        font-weight: 700;
        font-size: 16px;
        margin-bottom: 6px;
        color: #134e4a;
    }

    .arch-text {
        font-size: 13px;
        line-height: 1.35;
        color: #1f2937;
    }

    .arch-arrow {
        text-align: center;
        font-size: 28px;
        color: #0f766e;
        font-weight: bold;
    }

    .arch-subgrid {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 10px;
        margin-top: 8px;
    }

    .arch-small {
        border: 1px solid #94a3b8;
        border-radius: 10px;
        padding: 10px;
        background: #ffffff;
        min-height: 120px;
        box-sizing: border-box;
    }

    .arch-small-title {
        font-weight: 700;
        font-size: 14px;
        margin-bottom: 6px;
        color: #0f172a;
    }

    .arch-note {
        margin-top: 10px;
        padding: 10px 12px;
        border-left: 4px solid #0f766e;
        background: #ecfeff;
        color: #164e63;
        font-size: 13px;
    }

    .arch-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        background: #ccfbf1;
        color: #115e59;
        font-size: 12px;
        font-weight: 600;
        margin-bottom: 6px;
    }

    ul {
        margin: 6px 0 0 18px;
        padding: 0;
    }

    li {
        margin-bottom: 4px;
    }
    </style>
    </head>
    <body>
      <div class="arch-wrap">
        <div class="arch-grid">
          <div class="arch-box">
            <div class="arch-title">1. Student / UI</div>
            <div class="arch-text">
              The student uses the <b>ELS Console</b> to inspect the cluster.
              <ul>
                <li>read the ELS layer table</li>
                <li>choose a focused layer in <b>Layer Detail</b></li>
                <li>switch between <b>Explain</b> and <b>Evidence (Raw)</b></li>
              </ul>
            </div>
          </div>

          <div class="arch-arrow">→</div>

          <div class="arch-box">
            <div class="arch-pill">Can run as a pod in the student's cluster</div>
            <div class="arch-title">2. cka-coach Gen2</div>
            <div class="arch-text">
              cka-coach collects structured cluster state, maps it into the
              <b>ELS model</b>, and then uses an LLM to explain what is happening.
              This is the core of the learning system.
            </div>
          </div>

          <div class="arch-arrow">→</div>

          <div class="arch-box">
            <div class="arch-title">3. Student-facing output</div>
            <div class="arch-text">
              The console below shows:
              <ul>
                <li><b>ELS table</b> = layered system view</li>
                <li><b>Explain</b> = deterministic ELS + AI explanation</li>
                <li><b>Evidence (Raw)</b> = raw collected evidence</li>
              </ul>
            </div>
          </div>
        </div>

        <div class="arch-subgrid">
          <div class="arch-small">
            <div class="arch-small-title">State Collector</div>
            <div class="arch-text">
              Collects structured evidence from:
              <ul>
                <li>pods</li>
                <li>events</li>
                <li>nodes</li>
                <li>kubelet</li>
                <li>containerd</li>
                <li>network / routes</li>
              </ul>
            </div>
          </div>

          <div class="arch-small">
            <div class="arch-small-title">ELS Core</div>
            <div class="arch-text">
              The deterministic core of cka-coach.
              It maps evidence into the Expanded Layered Stack so students learn
              <b>where things live</b> and how layers relate.
            </div>
          </div>

          <div class="arch-small">
            <div class="arch-small-title">AI / Agent Layer</div>
            <div class="arch-text">
              The LLM does <b>explanation</b>, not truth creation.
              It teaches through:
              <ul>
                <li>Kubernetes</li>
                <li>AI / Agents</li>
                <li>Platform</li>
                <li>Product</li>
              </ul>
            </div>
          </div>
        </div>

        <div class="arch-note">
          <b>Reading guide:</b> The ELS table below is the live layered view of the cluster.
          <b>Layer Detail</b> lets you focus on one layer at a time.
          <b>Evidence (Raw)</b> shows the supporting data for that layer.
          <b>Explain</b> uses structured state + deterministic ELS reasoning + the LLM to teach what that layer means.
        </div>
      </div>
    </body>
    </html>
    """
    
    st.html(architecture_html)

    with st.expander("Why this is Gen2 and not just a simple chatbot"):
        st.markdown(
            """
**cka-coach Gen2** is more than prompt + response:

- **Deterministic layer model:** the ELS model is computed in Python, not invented by the LLM
- **Structured evidence:** cka-coach collects real cluster/runtime state first
- **Agent trace:** the app can show how it reasoned
- **AI as explainer:** the model explains the evidence, rather than making up the system model
- **Kubernetes-native direction:** cka-coach itself can be packaged and run as a pod inside the student's cluster

That means the student is learning both:
1. **how Kubernetes works**, and
2. **how a modern agentic support system is built on Kubernetes**
"""
        )

with st.expander("Show cka-coach Gen2 architecture", expanded=False):
    render_architecture_panel()

# --------------------------
# Collect State
# --------------------------
# This is now the shared evidence source for the dashboard.
# Important: the agent also receives this same structured state object.
with st.spinner("Collecting state..."):
    state = collect_state(allow_host_evidence=ALLOW_HOST_EVIDENCE)

summary = summarize(state)
versions_map = map_versions_to_layers(state)
health = state.get("health", {})
lesson_repo = lesson_catalog()
available_lessons = [lesson for lesson in lesson_repo if lesson.get("available")]

if available_lessons and "active_lesson_id" not in st.session_state:
    st.session_state["active_lesson_id"] = available_lessons[0]["id"]


def _layer_debug_commands(key: str):
    """
    Reuse ELS layer debug metadata wherever possible, with a few UI-level
    overrides only where the visible table needs more operationally useful
    entry points than the base schema currently provides.
    """
    overrides = {
        "L4.5": ["kubectl cluster-info", "kubectl get componentstatuses", "crictl ps | grep kube-apiserver"],
        "L5": ["kubectl get events", "kubectl describe deployment <name>", "kubectl get ds -A"],
        "L4.1": ["systemctl status kubelet", "journalctl -u kubelet"],
        "L4.2": ["kubectl get pods -n kube-system -l k8s-app=kube-proxy", "iptables -L -n -v"],
        "L4.3": ["kubectl get pods -n kube-system", "kubectl get ds -n kube-system", "ls /etc/cni/net.d/", "cat /etc/cni/net.d/<config>", "ip route"],
        "L3": ["systemctl status containerd", "crictl ps", "crictl inspect <id>"],
    }
    if key in overrides:
        return overrides[key]

    layer_id = key[1:]
    layer_meta = ELS_LAYERS.get(layer_id, {})
    return layer_meta.get("debug", [])

# --------------------------
# Layer Definitions for Table UI
# --------------------------
# These are the visual rows used in the dashboard table.
# They are related to ELS, but are primarily UI metadata for display.
layers = [
    ("9", "Applications", "User-facing application logic such as app binaries, web servers, APIs, and background workers running inside containers.", "application processes living inside containers", "user_process", _layer_debug_commands("L9"), "L9"),
    ("8", "Pods", "Pod abstraction wrapping one or more containers, restart policy, IP identity, and scheduling placement on nodes.", "kubelet-managed containers on nodes", "abstraction/meta", _layer_debug_commands("L8"), "L8"),
    ("7", "K8S Objects", "Desired-state resources stored in the API server such as Deployments, Services, ConfigMaps, Secrets, and NetworkPolicies.", "Persistent state (etcd via kube-apiserver)", "data", _layer_debug_commands("L7"), "L7"),
    ("6", "Operators", "Custom controllers with domain-specific logic, often shipped by platforms like Cilium, Calico, databases, and observability stacks.", "pods in cluster", "long_running_daemon", _layer_debug_commands("L6"), "L6"),
    ("5", "Controllers", "Core reconciliation loops such as kube-controller-manager, plus examples like Deployments, ReplicaSets, Jobs, and DaemonSets being continuously reconciled.", "kube-controller-manager static pod", "long_running_daemon", _layer_debug_commands("L5"), "L5"),
    ("4.5", "K8S API Layer", "Kubernetes API server and etcd as the cluster source of truth and control-plane entry boundary.", "control-plane node (containers or processes)", "long_running_daemon", _layer_debug_commands("L4.5"), "L4.5"),
    ("4.1", "kubelet", "Node-level control agent that watches PodSpecs and makes sure containers, volumes, probes, and restarts happen on each node.", "workers and control-plane nodes' systemd/PID1", "long_running_system_service", _layer_debug_commands("L4.1"), "L4.1"),
    ("4.2", "kube-proxy", "Service networking and virtual IP routing for Pods, unless some of that behavior is replaced by the active CNI dataplane.", "kube-system pod (or replaced by CNI dataplane)", "long_running_daemon", _layer_debug_commands("L4.2"), "L4.2"),
    ("4.3", "cni", "Container Network Interface plugin and node networking glue that wires pod networking, interfaces, routes, and policy-capable dataplanes.", "short-lived execution on node to wire pod networking", "short_lived_executable", _layer_debug_commands("L4.3"), "L4.3"),
    ("3", "Container Runtime / CRI", "Node-level container management through CRI, handling image pulls, container lifecycle, and runtime coordination.", "systemd service on node", "cri_daemon", _layer_debug_commands("L3"), "L3"),
    ("2", "OCI (runc)", "Low-level OCI container executor invoked by the CRI runtime to create and start individual containers.", "invoked by CRI runtime", "short_lived_executable", _layer_debug_commands("L2"), "L2"),
    ("1", "Kernel", "Linux namespaces, cgroups, networking, filesystems, and syscalls that ultimately enforce container isolation and connectivity.", "guest OS inside provider VM", "persistent_state_machine", _layer_debug_commands("L1"), "L1"),
    ("0", "VM/Infra", "Virtualized CPU, memory, disks, and network interfaces provided by the underlying VM or infrastructure platform.", "hypervisor-provided abstraction", "virtualization_layer", _layer_debug_commands("L0"), "L0"),
]

layer_options = [
    {
        "lvl": lvl,
        "name": name,
        "description": description,
        "lives": lives,
        "exec_type": exec_type,
        "api": api,
        "key": key,
    }
    for lvl, name, description, lives, exec_type, api, key in layers
]


def layer_label(option: dict) -> str:
    return f"L{option['lvl']} — {option['name']}"

def layer_status(key: str, health: dict):
    """
    Map ELS UI rows to their derived health status.

    Returns:
    - True / False / None for legacy layers
    - "healthy" / "degraded" / "unknown" for CNI
    """
    if key == "L8":
        return health.get("pods_ok")
    if key == "L7":
        return health.get("api_access_ok")
    if key == "L4.5":
        return health.get("api_access_ok")
    if key == "L6":
        return health.get("api_access_ok")
    if key == "L5":
        return health.get("events_ok")
    if key == "L4.1":
        return health.get("kubelet_ok")
    if key == "L4.2":
        return None
    if key == "L4.3":
        return health.get("cni_ok")
    if key == "L3":
        return health.get("containerd_ok")
    if key == "L2":
        return health.get("runc_ok")
    if key == "L1":
        return health.get("kernel_ok")
    if key == "L0":
        return True
    if key == "L9":
        return None
    return None

# --------------------------
# Build table rows once
# --------------------------
rows = ""

family_theme = {
    "blue": {"healthy": "#15365f", "border": "#60a5fa"},
    "green": {"healthy": "#174227", "border": "#4ade80"},
    "orange": {"healthy": "#4a3414", "border": "#fb923c"},
}

non_green_theme = {
    "warn": {"background": "#31353f", "border": "#cbd5e1"},
    "bad": {"background": "#4a2323", "border": "#fca5a5"},
}

plane_boundaries = {
    "L6": True,
    "L4.1": True,
}

plane_labels = {
    "L9": {"label": "App / Desired State", "rowspan": 3, "class": "plane-blue"},
    "L6": {"label": "Control Plane / Reconciliation", "rowspan": 3, "class": "plane-green"},
    "L4.1": {"label": "Node / Runtime / Dataplane", "rowspan": 7, "class": "plane-orange"},
}

for lvl, name, description, lives, exec_type, api, key in layers:
    if key in plane_boundaries:
        rows += """
        <tr class="plane-separator">
            <td colspan="9"></td>
        </tr>
        """

    current, ok = summary.get(key, ("...", True))
    version = versions_map.get(key, "")
    api_html = format_boundary_commands_html(api)

    # --- Status model ---
    # 🟢 = confirmed healthy
    # 🔴 = confirmed unhealthy
    # 🟡 = unknown / visibility-limited (NEW default for Phase 1 container mode)

    status = layer_status(key, health)
    family = layer_family(key)
    family_base = family_theme[family]

    row_color = non_green_theme["warn"]["background"]
    border_color = non_green_theme["warn"]["border"]
    health_icon = "🟡"

    if status is True or status == "healthy":
        row_color = family_base["healthy"]
        border_color = family_base["border"]
        health_icon = "🟢"
    elif status is False or status == "degraded":
        row_color = non_green_theme["bad"]["background"]
        border_color = non_green_theme["bad"]["border"]
        health_icon = "🔴"

    rows += f"""
    <tr style="background-color:{row_color}">
        {
            f'<td rowspan="{plane_labels[key]["rowspan"]}" class="plane-label-cell" style="border-color:{border_color}"><div class="plane-label {plane_labels[key]["class"]}">{plane_labels[key]["label"]}</div></td>'
            if key in plane_labels else ''
        }
        <td style="width:40px;border-color:{border_color}">{lvl}</td>
        <td style="width:120px;border-color:{border_color}"><div class="layer-name">{name}</div>{health_icon}</td>
        <td style="width:140px;border-color:{border_color}">{version}</td>
        <td style="width:240px;border-color:{border_color}">{description}</td>
        <td style="width:240px;border-color:{border_color}">{lives}</td>
        <td style="width:180px;border-color:{border_color}">{exec_type}</td>
        <td style="width:320px;border-color:{border_color}" class="small">{api_html}</td>
        <td style="border-color:{border_color}">{current}</td>
    </tr>
    """

# --------------------------
# Render table
# --------------------------
table_html += f"""
<table class="els-table">
    <tr>
        <th style="width:34px"></th>
        <th style="width:40px">Lvl</th>
        <th style="width:120px">Layer (health)</th>
        <th style="width:140px">Version</th>
        <th style="width:240px">Description</th>
        <th style="width:240px">Lives</th>
        <th style="width:180px">Execution</th>
        <th style="width:320px">API boundary / CLI</th>
        <th style="width:520px">Current Evidence</th>
    </tr>
    {rows}
</table>
"""

st.html(table_html)
st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")
st.html(
    """
    <div class="family-legend">
      <div class="family-chip family-blue">Blue = applications / desired state</div>
      <div class="family-chip family-green">Green = reconciliation / source of truth</div>
      <div class="family-chip family-orange">Brown = node / runtime / dataplane</div>
      <div class="family-chip family-alert">Purple/red shading = not healthy or visibility-limited; investigate before trusting this layer</div>
    </div>
    """
)
st.warning(
    "Running in container mode narrows which boundaries cka-coach can inspect directly. "
    "Host-level checks such as kubelet, systemctl, local config files, and other node/runtime evidence may be unavailable from inside the container boundary. "
    "At this stage, it is expected that some lower ELS layers will become visibility-limited or health-unknown unless the right host or in-cluster evidence paths are explicitly provided."
)
st.warning(
    "KEY: 🟢 = healthy; 🔴 = degraded/unhealthy; 🟡 = unknown / visibility-limited. "
    "A future lab can teach how to run cka-coach in a container, Pod, or Service while preserving the evidence paths it needs."
)

# --------------------------
# Networking Panel
# --------------------------
st.divider()
st.markdown("## Networking Panel")
st.caption(
    "Current networking view: identity, health, policy, observability, component presence, and directly observed versions."
)

networking_panel = build_networking_panel(state)

with st.container(border=True):
    render_networking_kv_cards(
        "Current Networking Summary",
        networking_panel.get("overview", {}),
        columns=3,
    )
    render_networking_kv_cards(
        "Networking Mode / Transport",
        networking_panel.get("mode", {}),
        columns=4,
    )

    info_col1, info_col2 = st.columns([1, 1], gap="large")
    with info_col1:
        render_networking_kv_cards(
            "Policy + Observability",
            networking_panel.get("policy_observability", {}),
            columns=1,
            value_as_markdown=False,
        )

    with info_col2:
        with st.container(border=True):
            st.caption("Current Interpretation")
            st.write(networking_panel.get("interpretation", "Networking state is not directly observed."))

evidence_col1, evidence_col2 = st.columns([1, 1], gap="large")
with evidence_col1:
    with st.container(border=True):
        st.markdown("### Cluster Evidence")
        for line in networking_panel.get("cluster_evidence", []):
            st.write(f"- {line}")

with evidence_col2:
    with st.container(border=True):
        st.markdown("### Node Evidence")
        for line in networking_panel.get("node_evidence", []):
            st.write(f"- {line}")

component_col, version_col = st.columns([1.1, 1], gap="large")
with component_col:
    with st.container(border=True):
        st.markdown("### Current Networking Components")
        component_rows = networking_panel.get("components", [])
        if component_rows:
            st.table(component_rows)
        else:
            st.caption("No networking components were directly observed.")

with version_col:
    with st.container(border=True):
        st.markdown("### Observed Versions")
        version_rows = networking_panel.get("versions", [])
        if version_rows:
            st.table(version_rows)
        else:
            st.caption("No current networking component versions were directly observed.")

calico_330_rows = networking_panel.get("calico_330_signals", [])
if calico_330_rows:
    with st.container(border=True):
        st.markdown("### Calico 3.30+ Signals")
        st.table(calico_330_rows)

# --------------------------
# Network Visual Panel
# --------------------------
st.divider()
st.markdown("## Network Visual Panel")
st.caption(
    "Current cluster topology from Kubernetes objects down to overlay transport, node networking, and kernel / namespace reality."
)

network_visual_model = build_network_visual_model(state)
st.html(render_network_visual_html(network_visual_model))

# --------------------------
# Active Lesson / Coaching Console
# --------------------------
st.divider()
st.markdown("## Lessons")
st.caption(
    "Lesson selection stays visible here. The active coaching console is temporarily collapsed while the networking and evidence views are being finished."
)

with st.expander("Lessons / available lessons", expanded=False):
    if available_lessons:
        selected_lesson_id = st.radio(
            "Available lessons",
            options=[lesson["id"] for lesson in available_lessons],
            index=next(
                (
                    i
                    for i, lesson in enumerate(available_lessons)
                    if lesson["id"] == st.session_state.get("active_lesson_id")
                ),
                0,
            ),
            format_func=lambda lesson_id: next(
                (
                    lesson["title"]
                    for lesson in available_lessons
                    if lesson["id"] == lesson_id
                ),
                lesson_id,
            ),
            key="active_lesson_id",
        )
        selected_lesson_meta = next(
            lesson for lesson in available_lessons if lesson["id"] == selected_lesson_id
        )
        st.caption(selected_lesson_meta.get("description", ""))
    else:
        selected_lesson_id = ""
        st.info("No lessons are available yet.")

    upcoming_lessons = [lesson for lesson in lesson_repo if not lesson.get("available")]
    if upcoming_lessons:
        st.markdown("**Coming soon**")
        for lesson in upcoming_lessons:
            st.write(f"- {lesson['title']}: {lesson['description']}")

active_lesson_id = st.session_state.get("active_lesson_id", "")
lesson_progress_key = f"lesson_progress_{active_lesson_id}"
if active_lesson_id and lesson_progress_key not in st.session_state:
    st.session_state[lesson_progress_key] = default_lesson_progress()

lesson_progress = st.session_state.get(lesson_progress_key, default_lesson_progress())
lesson_run = (
    build_lesson_run(active_lesson_id, state, lesson_progress)
    if available_lessons
    else {}
)
with st.expander("Active Lesson / Coaching Console — Under Construction", expanded=False):
    st.caption(
        "This guided lesson flow is paused while cka-coach's networking and verification surfaces are being tightened. "
        "We’ll bring it back once the product is more complete."
    )

    if lesson_run:
        ensure_initial_lesson_audit(st.session_state, lesson_run["id"], lesson_run)
        lesson_steps = lesson_run.get("steps", [])
        current_step_index = lesson_run.get("current_step", 0)
        active_step = lesson_steps[current_step_index] if lesson_steps else {}
        lesson_audit = st.session_state.get(f"lesson_audit_{lesson_run['id']}", [])
        lesson_notes_key = f"lesson_notes_{lesson_run['id']}"
        lesson_input_key = f"lesson_note_input_{lesson_run['id']}"
        target_nodes = active_step.get("target_nodes", [])
        target_scope = active_step.get("target_scope", "")

        def _persist_lesson_progress(updated_progress: dict, rerun: bool = True):
            st.session_state[lesson_progress_key] = updated_progress
            if rerun:
                st.rerun()

        coach_col, student_col = st.columns([1.2, 1], gap="large")

        with coach_col:
            with st.container(border=True):
                st.markdown("### Coach")
                st.markdown("**What we are doing overall**")
                st.write(lesson_run.get("overall_summary", ""))
                st.caption(lesson_run.get("why_it_matters", ""))

                progress_fraction = lesson_run.get("completion_percentage", 0) / 100
                st.progress(progress_fraction)
                st.caption(f"{lesson_run.get('completion_percentage', 0)}% complete")

                st.markdown("**Current position in the lesson**")
                st.write(lesson_run.get("current_position_summary", ""))
                for note in lesson_run.get("nonblocking_notes", []):
                    st.info(note)
                render_lesson_step_tracker(lesson_steps, current_step_index)

                st.markdown("**Next step guidance**")
                if active_step:
                    st.write(active_step.get("title", ""))
                    st.caption(active_step.get("why", ""))
                    st.markdown(f"**Scope:** {target_scope or '(unknown)'}")
                    st.markdown(
                        "**Targets:** "
                        + (", ".join(target_nodes) if target_nodes else "(none)")
                    )
                    st.markdown("**Coach can do now**")
                    st.write(active_step.get("coach_action", ""))
                    st.markdown("**Student must do**")
                    st.write(active_step.get("student_action", "None for this step."))
                    st.markdown("**Verification**")
                    st.caption(active_step.get("verification", ""))
                else:
                    st.success("This lesson is complete.")

                action_col1, action_col2 = st.columns([1, 1])
                if action_col1.button("Refresh lesson state", key=f"lesson_refresh_{lesson_run['id']}"):
                    append_coach_audit(
                        st.session_state,
                        lesson_run["id"],
                        active_step.get("id", "refresh"),
                        target_scope or "Cluster",
                        target_nodes,
                        "refresh_state",
                        "collect_state()",
                        f"Lesson remains {lesson_run.get('status', 'paused')}.",
                        state_changed=False,
                        requires_student_action=active_step.get("student_must_do", False),
                    )
                    st.rerun()
                if active_step and active_step.get("status") in {"waiting_for_coach", "blocked"}:
                    coach_label = "Run coach step"
                    if active_step.get("id") == "generate_remediation_scripts":
                        coach_label = "Generate student script"
                    elif active_step.get("id") == "confirm_baseline":
                        coach_label = "Confirm lesson checkpoint"

                    if action_col2.button(coach_label, key=f"lesson_coach_step_{lesson_run['id']}"):
                        updated = dict(lesson_progress)
                        step_id = active_step.get("id")
                        if step_id == "inspect_current_state":
                            updated["inspect_ran"] = True
                        elif step_id == "classify_cleanup_scope":
                            updated["classify_ran"] = True
                        elif step_id == "generate_remediation_scripts":
                            updated["scripts_generated"] = True
                        elif step_id == "recheck_target_nodes":
                            updated["recheck_ran"] = True
                        elif step_id == "confirm_baseline":
                            updated["baseline_confirmed"] = lesson_run.get("baseline_ready", False)
                        append_coach_audit(
                            st.session_state,
                            lesson_run["id"],
                            step_id,
                            target_scope or "Cluster",
                            target_nodes,
                            "coach_step",
                            active_step.get("coach_action", ""),
                            active_step.get("verification", ""),
                            state_changed=step_id in {"generate_remediation_scripts"},
                            requires_student_action=active_step.get("student_must_do", False),
                        )
                        _persist_lesson_progress(updated)
                elif active_step and active_step.get("status") == "completed" and current_step_index < len(lesson_steps) - 1:
                    if action_col2.button("Continue to next step", key=f"lesson_continue_{lesson_run['id']}"):
                        updated = dict(lesson_progress)
                        updated["current_step"] = current_step_index + 1
                        append_coach_audit(
                            st.session_state,
                            lesson_run["id"],
                            active_step.get("id", "continue"),
                            target_scope or "Cluster",
                            target_nodes,
                            "continue",
                            "advance lesson pointer",
                            f"Moved to step {current_step_index + 2}.",
                            state_changed=False,
                            requires_student_action=False,
                        )
                        _persist_lesson_progress(updated)

                st.markdown("**Coach audit trail**")
                if lesson_audit:
                    for entry in lesson_audit[:6]:
                        with st.expander(
                            f"{entry.get('timestamp', '')} — {entry.get('step_id', '')} — {entry.get('action_type', '')}",
                            expanded=False,
                        ):
                            st.write(f"Scope: {entry.get('node_scope', '')}")
                            st.write(
                                "Targets: "
                                + (", ".join(entry.get("target_nodes", [])) or "(none)")
                            )
                            st.write(f"Check / action: {entry.get('command_or_check', '')}")
                            st.write(f"Result: {entry.get('result_summary', '')}")
                            st.write(
                                "State changed: "
                                + ("yes" if entry.get("state_changed") else "no")
                            )
                            st.write(
                                "Student action required: "
                                + ("yes" if entry.get("requires_student_action") else "no")
                            )
                else:
                    st.caption("No coach actions recorded yet.")

        with student_col:
            with st.container(border=True):
                st.markdown("### Student Workspace")
                st.write(
                    "This is the student working area. Review the generated commands or scripts, run them on the correct node or cluster shell, then return here to trigger verification."
                )
                if active_step:
                    status = active_step.get("status", "not_started")
                    st.markdown(
                        f"**Active step:** {active_step.get('title', '')}  \n"
                        f"{step_status_icon(status)} {step_status_badge(status)}"
                    )
                    observed = active_step.get("observed", "")
                    if observed:
                        st.caption(f"Observed right now: {observed}")
                    st.caption(f"Scope: {target_scope or '(unknown)'}")
                    st.caption("Targets: " + (", ".join(target_nodes) if target_nodes else "(none)"))
                    run_on = active_step.get("run_on", "")
                    if run_on:
                        st.caption(f"Run on: {run_on}")

                    scripts = lesson_run.get("remediation_scripts", {})
                    current_remediation_target = lesson_run.get("current_remediation_target", "")
                    completed_target_nodes = lesson_run.get("completed_target_nodes", [])
                    should_show_scripts = (
                        bool(scripts)
                        and (
                            active_step.get("id") == "generate_remediation_scripts"
                            or (
                                active_step.get("id") in {"student_run_remediation", "recheck_target_nodes", "confirm_baseline"}
                                and not lesson_run.get("baseline_ready")
                            )
                        )
                    )
                    if should_show_scripts:
                        st.markdown("**Generated remediation scripts**")
                        st.caption(
                            "These scripts are generated for review in the lesson screen only. "
                            "cka-coach is not writing them to disk automatically."
                        )
                        ordered_nodes = list(scripts.keys())
                        if current_remediation_target and current_remediation_target in ordered_nodes:
                            ordered_nodes = [current_remediation_target] + [
                                node for node in ordered_nodes if node != current_remediation_target
                            ]
                        if current_remediation_target:
                            st.info(
                                f"Run this next: `cleanup-cni-residuals-{current_remediation_target}.sh` on node `{current_remediation_target}`."
                            )
                        if completed_target_nodes:
                            st.caption(
                                "Completed target nodes: " + ", ".join(completed_target_nodes)
                            )
                        if len(ordered_nodes) > 1:
                            st.markdown("**Run these next**")
                            for idx, node_name in enumerate(ordered_nodes, start=1):
                                st.write(f"{idx}. Run `cleanup-cni-residuals-{node_name}.sh` on node `{node_name}`")
                        for node_name in ordered_nodes:
                            script = scripts[node_name]
                            st.markdown(f"**{script.get('filename', node_name)}**")
                            st.caption(script.get("summary", ""))
                            st.caption(f"Target node: {node_name} | sudo required: {script.get('sudo_required', 'yes')}")
                            st.code(script.get("content", ""), language="bash")
                        if active_step.get("id") == "confirm_baseline" and not lesson_run.get("baseline_ready"):
                            st.warning(
                                "The baseline is still blocked. The generated remediation scripts remain visible here because at least one target node still needs cleanup."
                            )
                    else:
                        commands = active_step.get("commands", [])
                        if commands:
                            st.markdown("**Run these commands**")
                            st.code("\n".join(commands), language="bash")
                        else:
                            st.info("This step does not require a student-run command right now.")

                    st.markdown("**Interpret what you see**")
                    st.caption(active_step.get("verification", ""))

                    with st.form(
                        key=f"lesson_note_form_{lesson_run['id']}",
                        clear_on_submit=True,
                    ):
                        note = st.text_area(
                            "Student command notebook / paste what you ran",
                            key=lesson_input_key,
                            height=120,
                            placeholder="Example:\nls /etc/cni/net.d/\nsudo mv /etc/cni/net.d/05-cilium.conflist /etc/cni/net.d/05-cilium.conflist.bak",
                        )
                        save_note = st.form_submit_button("Save note")

                    rerun_col, spacer_col = st.columns([1, 1])
                    if save_note:
                        note = note.strip()
                        if note:
                            saved_notes = list(st.session_state.get(lesson_notes_key, []))
                            saved_notes.insert(
                                0,
                                {
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                    "text": note,
                                },
                            )
                            st.session_state[lesson_notes_key] = saved_notes[:6]
                            st.rerun()
                    if active_step.get("student_must_do") and rerun_col.button(
                        "I ran this — re-check",
                        key=f"lesson_student_rerun_{lesson_run['id']}",
                    ):
                        updated = dict(lesson_progress)
                        updated["student_confirmed"] = True
                        current_target = lesson_run.get("current_remediation_target", "")
                        cleanup_targets = list(lesson_run.get("cleanup_target_nodes", []))
                        completed_targets = list(updated.get("completed_target_nodes", []))
                        advanced_to_next_target = False
                        if (
                            active_step.get("id") == "student_run_remediation"
                            and current_target
                            and current_target not in completed_targets
                        ):
                            completed_targets.append(current_target)
                            updated["completed_target_nodes"] = completed_targets
                            remaining_targets = [
                                node for node in cleanup_targets if node not in completed_targets
                            ]
                            if remaining_targets:
                                updated["current_target_index"] = cleanup_targets.index(remaining_targets[0])
                                updated["current_step"] = current_step_index
                                advanced_to_next_target = True
                            elif current_step_index < len(lesson_steps) - 1:
                                updated["current_step"] = current_step_index + 1
                        elif current_step_index < len(lesson_steps) - 1:
                            updated["current_step"] = current_step_index + 1
                        append_coach_audit(
                            st.session_state,
                            lesson_run["id"],
                            active_step.get("id", "student_step"),
                            target_scope or "Node remediation",
                            target_nodes,
                            "student_confirmation",
                            "student reported reviewed sudo step was run",
                            (
                                f"Marked {current_target} complete and advanced to the next target node."
                                if advanced_to_next_target
                                else "Moved lesson to coach re-check step."
                            ),
                            state_changed=False,
                            requires_student_action=False,
                        )
                        _persist_lesson_progress(updated)

                    saved_notes = st.session_state.get(lesson_notes_key, [])
                    if saved_notes:
                        st.markdown("**Recent student notes**")
                        for entry in saved_notes[:3]:
                            st.caption(f"{entry.get('time', '')} — {entry.get('text', '')}")
                else:
                    st.info("Select a lesson above to start guided work.")

                if lesson_run.get("baseline_ready"):
                    st.success(
                        "Known-good baseline verified. This lab is ready for the next networking lesson."
                    )
                else:
                    st.info(
                        "The lesson remains paused until cka-coach can verify that residual networking state is gone or intentionally retained."
                    )

        st.markdown("### Per-node remediation status")
        per_node_rows = []
        for entry in lesson_run.get("per_node_status", []):
            per_node_rows.append(
                {
                    "Node": lesson_table_value(entry.get("node", "")),
                    "Scope": lesson_table_value(entry.get("scope", "")),
                    "Classification": lesson_table_value(entry.get("current_classification", "")),
                    "Cilium ifaces": lesson_table_value(entry.get("cilium_interfaces_present", "unknown")),
                    "Calico ifaces": lesson_table_value(entry.get("calico_interfaces_present", "unknown")),
                    "Calico iptables": lesson_table_value(entry.get("calico_iptables_present", "unknown")),
                    "Residue": lesson_table_value(", ".join(entry.get("residue_types", []))),
                    "Cleanup required": lesson_table_value(entry.get("cleanup_required", False)),
                    "Last verified": lesson_table_value(entry.get("last_verified_at", "")),
                }
            )
        if per_node_rows:
            st.table(per_node_rows)
        else:
            st.caption("No node-specific remediation status is available.")
    else:
        st.info("No lesson state is available yet.")

# --------------------------
# Layer Detail
# --------------------------
# Keep interpretation and raw evidence separate, but use one focused detail
# area instead of a long list of per-row Explain/Expand controls.
st.divider()

st.markdown("## Layer Detail")
st.caption("Use one focused selector to move through layers quickly. L4.x stays easy to reach while interpreted explanation and raw evidence remain clearly separated.")

default_layer_index = next((i for i, option in enumerate(layer_options) if option["key"] == "L4.3"), 0)
selected_layer = st.selectbox(
    "Focus Layer",
    layer_options,
    index=default_layer_index,
    format_func=layer_label,
)

selected_key = selected_layer["key"]
selected_summary, _ = summary.get(selected_key, ("...", True))
selected_version = versions_map.get(selected_key, "")
selected_status = layer_status(selected_key, health)
cni_evidence = state.get("evidence", {}).get("cni", {})
cni_confidence = cni_evidence.get("confidence", "unknown")
cni_config_spec_ui = cni_config_spec_display(state)
cni_capability = cni_evidence.get("capabilities", {}).get("summary", "unknown")
cni_policy_status = cni_evidence.get("policy_presence", {}).get("status", "unknown")
cni_classification = cni_evidence.get("classification", {})
cni_provenance = cni_evidence.get("provenance", {})
cni_policy_label = {
    "present": "present",
    "absent": "none detected",
    "unknown": "unknown",
}.get(cni_policy_status, cni_policy_status)
cni_name = state.get("summary", {}).get("versions", {}).get(
    "cni",
    state.get("versions", {}).get("cni", "unknown"),
)
cni_node_level = cni_evidence.get("node_level", {})
cni_cluster_level = cni_evidence.get("cluster_level", {})
cni_reconciliation = cni_evidence.get("reconciliation", "unknown")
cni_partial_uninstall_warning = (
    selected_key == "L4.3"
    and cni_reconciliation == "single_source"
    and cni_node_level.get("cni", "unknown") not in {"", "unknown"}
    and cni_cluster_level.get("cni", "unknown") in {"", "unknown"}
)

status_label = cni_status_label(state).replace("-", " ").title() if selected_key == "L4.3" else "Unknown / limited visibility"
if selected_key != "L4.3":
    if selected_status is True or selected_status == "healthy":
        status_label = "Healthy"
    elif selected_status is False or selected_status == "degraded":
        status_label = "Degraded"

with st.container(border=True):
    st.markdown(f"### {layer_label(selected_layer)}")
    if selected_key == "L4.3":
        st.caption(selected_layer["description"])
        summary_col1, summary_col2, summary_col3, summary_col4 = st.columns([1.6, 1.1, 1.1, 1.2])

        with summary_col1:
            st.markdown("**Interpreted Summary**")
            st.write(f"CNI: {cni_name}")
            st.write(f"Classification: {cni_classification.get('state', 'unknown')}")
            st.write(f"Capability: {cni_capability}")
            st.write(f"Policy: {cni_policy_label}")

        with summary_col2:
            st.markdown("**Identity / Version**")
            st.write(selected_version or "unknown")
            st.write(f"CNI config spec: {cni_config_spec_ui['label']}")

        with summary_col3:
            st.markdown("**Confidence / Status**")
            st.write(f"Confidence: {cni_confidence}")
            st.write(f"Health: {status_label}")

        with summary_col4:
            st.markdown("**Placement**")
            st.write(selected_layer["lives"])
            st.write(f"Execution: {selected_layer['exec_type']}")

        st.markdown("**API boundary / CLI**")
        st.code(format_boundary_commands_text(selected_layer["api"]))
        st.caption(f"Why this classification: {cni_classification.get('reason', 'unknown')}")
        if cni_classification.get("notes"):
            st.caption("Supporting notes: " + " ".join(cni_classification.get("notes", [])))
        if cni_provenance.get("available"):
            st.caption(
                "Provenance: current="
                f"{cni_provenance.get('current_detected_cni', 'unknown')}, previous="
                f"{cni_provenance.get('previous_detected_cni', 'unknown')}, cleaned_by="
                f"{cni_provenance.get('cleaned_by', '') or '(unknown)'}, last_cleaned_at="
                f"{cni_provenance.get('last_cleaned_at', '') or '(unknown)'}"
            )
        else:
            st.caption(
                "Provenance: no in-cluster provenance record found; current/previous state is inferred from live evidence only."
            )
        if cni_partial_uninstall_warning:
            st.warning(
                "Cluster-level components for this CNI are absent, but host/node CNI config still "
                f"references `{cni_node_level.get('cni', 'unknown')}`. This may indicate a partial "
                "uninstall, stale node configuration, or transitional state."
            )
            st.caption(
                "Action hint: inspect `/etc/cni/net.d` and clean up or replace stale config before installing another CNI."
            )
        if not cni_config_spec_ui["observed"]:
            st.caption(cni_config_spec_ui["note"])
    else:
        meta_col1, meta_col2 = st.columns([2, 1])
        with meta_col1:
            st.write(selected_layer["description"])
        with meta_col2:
            st.markdown("**Where it lives**")
            st.write(selected_layer["lives"])
            st.markdown("**Execution**")
            st.write(selected_layer["exec_type"])

        st.markdown("**Interpreted Summary**")
        st.write(selected_summary)
        if selected_version:
            st.write(f"Version / identity: {selected_version}")
        st.write(f"Health / status: {status_label}")
        st.markdown("**API boundary / CLI**")
        st.code(format_boundary_commands_text(selected_layer["api"]))

    if selected_key == "L4.3":
        st.caption(
            "Confidence key: high = agreeing direct evidence across sources; medium = one source or mixed support; low = insufficient direct evidence."
        )

with st.expander("Explain", expanded=True):
    st.caption("Interpreted explanation generated from the structured state and deterministic ELS logic.")
    if st.button(f"Explain {layer_label(selected_layer)}", key=f"explain_{selected_key}"):
        explanation = ask_llm(
            f"Explain current state of {selected_layer['name']}",
            state
        )
        st.session_state[f"explanation_{selected_key}"] = normalize_explanation_output(explanation)

    parsed = st.session_state.get(f"explanation_{selected_key}")
    if not parsed:
        st.info("Select a layer and click Explain to load the interpreted explanation.")
    elif "error" in parsed:
        st.error(parsed["error"])
    elif "raw_text" in parsed:
        st.write(parsed["raw_text"])
    else:
        explain_tab_answer, explain_tab_learning, explain_tab_trace, explain_tab_raw = st.tabs(
            ["Answer", "Learning", "Trace", "Raw JSON"]
        )

        with explain_tab_answer:
            st.markdown("#### Answer")
            st.write(parsed.get("answer", ""))

            summary_text = parsed.get("summary", "")
            if summary_text:
                st.markdown("#### Summary")
                st.write(summary_text)

            warnings = parsed.get("warnings", [])
            if warnings:
                st.markdown("#### Warnings")
                for warning in warnings:
                    st.warning(warning)

            els = parsed.get("els", {})
            guided_plan = els.get("guided_investigation_plan", [])
            if guided_plan:
                st.markdown("#### Next Steps (Guided Investigation Plan)")
                render_guided_plan(guided_plan)
            else:
                next_steps = els.get("next_steps", [])
                if next_steps:
                    st.markdown("#### Next Steps")
                    for step in next_steps:
                        st.write(f"- {step}")

        with explain_tab_learning:
            learning = parsed.get("learning", {})

            learn_col1, learn_col2 = st.columns(2)

            with learn_col1:
                st.markdown("#### Kubernetes")
                st.write(learning.get("kubernetes", "No Kubernetes learning view returned."))

                st.markdown("#### AI / Agents")
                st.write(learning.get("ai", "No AI / Agents learning view returned."))

            with learn_col2:
                st.markdown("#### Platform")
                st.write(learning.get("platform", "No Platform learning view returned."))

                st.markdown("#### Product")
                st.write(learning.get("product", "No Product learning view returned."))

        with explain_tab_trace:
            trace = parsed.get("agent_trace", [])
            if trace:
                for step in trace:
                    with st.expander(f"Step {step.get('step', '?')}: {step.get('action', '')}"):
                        st.markdown(f"**Why:** {step.get('why', '')}")
                        st.markdown(f"**Outcome:** {step.get('outcome', '')}")
            else:
                st.write("No agent trace returned.")

        with explain_tab_raw:
            st.json(parsed)

with st.expander("Evidence (Raw)", expanded=False):
    st.caption("Raw supporting evidence for the selected layer without interpretation.")
    st.text(get_expand_text(selected_key, state)[:6000])

st.divider()
st.markdown("## Future Networking Visuals")
st.caption("Reserved space for a later network or policy diagram. This branch only prepares the layout cleanly.")
with st.container(border=True):
    st.markdown(
        '<div class="detail-note">Future Phase 2 diagram or policy visuals can be placed here below the focused layer detail area.</div>',
        unsafe_allow_html=True,
    )
ALLOW_HOST_EVIDENCE = "--allow-host-evidence" in sys.argv[1:]
