import streamlit as st
import sys
import os
import json
from datetime import datetime

# Allow imports from ../src
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from state_collector import collect_state
from agent import ask_llm

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

    pods_text = runtime.get("pods", "")
    pod_lines = [l for l in pods_text.splitlines() if l.strip()]
    data_lines = pod_lines[1:] if len(pod_lines) > 1 else []

    total_pods = len(data_lines)
    kube_system_pods = sum(1 for l in data_lines if l.startswith("kube-system "))
    default_pods = sum(1 for l in data_lines if l.startswith("default "))
    pending_pods = sum(1 for l in data_lines if " Pending " in f" {l} ")
    crashloop_pods = sum(1 for l in data_lines if "CrashLoopBackOff" in l)

    kubelet_ok = health.get("kubelet_ok", None)
    containerd_ok = health.get("containerd_ok", None)

    cni_name = summary_versions.get("cni", versions.get("cni", ""))
    kernel_ver = versions.get("kernel", "")
    kubelet_ver = versions.get("kubelet", "")
    runc_ver = versions.get("runc", "")
    api_ver = versions.get("api", "")
    cni_evidence = state.get("evidence", {}).get("cni", {})
    capability_summary = cni_evidence.get("capabilities", {}).get("summary", "unknown")
    policy_status = cni_evidence.get("policy_presence", {}).get("status", "unknown")
    cni_confidence = cni_evidence.get("confidence", "unknown")
    policy_label = {
        "present": "present",
        "absent": "none detected",
        "unknown": "unknown",
    }.get(policy_status, policy_status)

    if kubelet_ok is True:
        kubelet_text = "kubelet running"
    elif kubelet_ok is False:
        kubelet_text = "kubelet issue"
    else:
        kubelet_text = "kubelet status unknown (no host access)"

    if containerd_ok is True:
        containerd_text = "containerd running"
    elif containerd_ok is False:
        containerd_text = "containerd issue"
    else:
        containerd_text = "containerd status unknown"

    return {
        "L9": ("User workloads", True),
        "L8": (
            f"{total_pods} pods | default={default_pods} | kube-system={kube_system_pods}"
            + (f" | Pending={pending_pods}" if pending_pods else "")
            + (f" | CrashLoop={crashloop_pods}" if crashloop_pods else ""),
            not (health.get("pods_pending", False) or health.get("pods_crashloop", False)),
        ),
        "L7": ("Desired state via API objects", True),
        "L6.5": (f"API server / etcd | {api_ver or 'unknown'}", True),
        "L6": ("Operators / custom controllers", True),
        "L5": ("kube-controller-manager", True),
        "L4.1": (kubelet_text, kubelet_ok is True),
        "L4.2": ("kube-proxy / service routing", True),
        "L4.3": (
            f"CNI: {cni_name or 'unknown'} | confidence: {cni_confidence} | capability: {capability_summary} | policy: {policy_label}",
            True,
        ),
        "L3": (containerd_text, containerd_ok is True),
        "L2": (runc_ver or "runc version unknown", True),
        "L1": (f"kernel {kernel_ver or 'unknown'}", True),
        "L0": ("VM / virtual hardware", True),
    }


def map_versions_to_layers(state: dict) -> dict:
    """
    Map version strings to visible ELS table rows.
    """
    v = state.get("versions", {})
    summary_versions = state.get("summary", {}).get("versions", {})
    cni_name = summary_versions.get("cni", v.get("cni", ""))
    cni_version = summary_versions.get("cni_version", "unknown")
    return {
        "L9": "",
        "L8": "",
        "L7": v.get("api", ""),
        "L6.5": v.get("api", ""),
        "L6": v.get("api", ""),
        "L5": v.get("api", ""),
        "L4.1": v.get("kubelet", ""),
        "L4.2": v.get("api", ""),
        "L4.3": (
            f"{cni_name} | v{cni_version}"
            if cni_name and cni_name != "unknown" and cni_version not in {"", "unknown"}
            else cni_name
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
    policy_presence = detection.get("policy_presence", {})
    version = detection.get("version", {})
    migration_note = detection.get("migration_note", "unknown")

    filenames = node_level.get("filenames", [])
    filename_text = "\n".join(filenames) if filenames else "(none found)"
    selected_file = node_level.get("selected_file", "") or "(none)"
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
        f"selected file: {selected_file}\n"
        "files in /etc/cni/net.d:\n"
        f"{filename_text}\n\n"
        "[cluster-level detection]\n"
        f"detected cni: {cluster_level.get('cni', 'unknown')}\n"
        f"confidence: {cluster_level.get('confidence', 'low')}\n"
        f"selected pod: {selected_pod}\n"
        "matched kube-system pods:\n"
        f"{matched_pod_text}\n\n"
        "[capability inference]\n"
        f"summary: {capabilities.get('summary', 'unknown')}\n"
        f"policy support: {capabilities.get('policy_support', 'unknown')}\n"
        f"observability: {capabilities.get('observability', 'unknown')}\n"
        f"inference basis: {capabilities.get('inference_basis', 'unknown')}\n\n"
        "[version evidence]\n"
        f"observed version: {version.get('value', 'unknown')}\n"
        f"source: {version.get('source', 'unknown')}\n"
        f"pod: {version.get('pod', '') or '(none)'}\n"
        f"image: {version.get('image', '') or '(none)'}\n\n"
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
        "L6.5": versions.get("k8s_json", ""),
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
    state = collect_state()

summary = summarize(state)
versions_map = map_versions_to_layers(state)
health = state.get("health", {})

# --------------------------
# Layer Definitions for Table UI
# --------------------------
# These are the visual rows used in the dashboard table.
# They are related to ELS, but are primarily UI metadata for display.
layers = [
    ("9", "Applications", "User-facing application logic", "application processes living inside containers", "user_process", "app specific", "L9"),
    ("8", "Pods", "Pod abstraction wrapping one or more containers", "kubelet-managed containers on nodes", "abstraction/meta", "kubectl get pods -o wide", "L8"),
    ("7", "K8S Objects", "Desired state definitions stored in API server", "Persistent state (etcd via kube-apiserver)", "data", "kubectl get <resource>", "L7"),
    ("6.5", "K8S API Layer", "Kubernetes API server and etcd (cluster state store)", "control-plane node (containers or processes)", "long_running_daemon", "kubectl cluster-info", "L6.5"),
    ("6", "Operators", "Custom controllers with domain-specific logic", "pods in cluster", "long_running_daemon", "kubectl get pods -n <operator-namespace>", "L6"),
    ("5", "Controllers", "Core reconciliation loops", "kube-controller-manager static pod", "long_running_daemon", "kubectl get events", "L5"),
    ("4.1", "kubelet", "Node-level control agent", "workers and control-plane nodes' systemd/PID1", "long_running_system_service", "systemctl status kubelet", "L4.1"),
    ("4.2", "kube-proxy", "Service networking for Pods", "kube-system pod (or replaced by CNI dataplane)", "long_running_daemon", "iptables -L -n -v", "L4.2"),
    ("4.3", "cni", "Container Network Interface & plugin", "short-lived execution on node to wire pod networking", "short_lived_executable", "ls /etc/cni/net.d/ ; ip route", "L4.3"),
    ("3", "Container Runtime / CRI", "Node-level container management", "systemd service on node", "cri_daemon", "crictl", "L3"),
    ("2", "OCI (runc)", "Low-level container executor", "invoked by CRI runtime", "short_lived_executable", "runc --version", "L2"),
    ("1", "Kernel", "Namespaces, cgroups, networking", "guest OS inside provider VM", "persistent_state_machine", "ip / proc / uname -r", "L1"),
    ("0", "VM/Infra", "Virtualized CPU, memory, network interfaces", "hypervisor-provided abstraction", "virtualization_layer", "lscpu ; lsblk", "L0"),
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
    if key == "L6.5":
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

for lvl, name, description, lives, exec_type, api, key in layers:
    current, ok = summary.get(key, ("...", True))
    version = versions_map.get(key, "")

    # --- Status model ---
    # 🟢 = confirmed healthy
    # 🔴 = confirmed unhealthy
    # 🟡 = unknown / visibility-limited (NEW default for Phase 1 container mode)

    status = layer_status(key, health)

    row_color = "#332200"
    health_icon = "🟡"

    if status is True or status == "healthy":
        row_color = "#001100"
        health_icon = "🟢"
    elif status is False or status == "degraded":
        row_color = "#220000"
        health_icon = "🔴"

    # --- everything else stays AMBER ---

    rows += f"""
    <tr style="background-color:{row_color}">
        <td style="width:40px">{lvl}</td>
        <td style="width:120px"><div class="layer-name">{name}</div>{health_icon}</td>
        <td style="width:140px">{version}</td>
        <td style="width:240px">{description}</td>
        <td style="width:240px">{lives}</td>
        <td style="width:180px">{exec_type}</td>
        <td style="width:180px" class="small">{api}</td>
        <td>{current}</td>
    </tr>
    """

# --------------------------
# Render table
# --------------------------
table_html += f"""
<table class="els-table">
    <tr>
        <th style="width:40px">Lvl</th>
        <th style="width:120px">Layer (health)</th>
        <th style="width:140px">Version</th>
        <th style="width:240px">Description</th>
        <th style="width:240px">Lives</th>
        <th style="width:180px">Execution</th>
        <th style="width:180px">API</th>
        <th style="width:700px">Current Evidence</th>
    </tr>
    {rows}
</table>
"""

st.html(table_html)
st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")
st.warning(
    "Running in container mode: host-level checks (e.g. kubelet, systemctl) may be unavailable. "
    "Cluster API access requires kubeconfig or in-cluster credentials."
)
st.warning(
    "KEY: 🟢 = healthy; 🔴 = degraded/unhealthy; 🟡 = unknown / visibility-limited (NEW default for Phase 1 container mode)"
)

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

status_label = "Unknown / limited visibility"
if selected_status is True or selected_status == "healthy":
    status_label = "Healthy"
elif selected_status is False or selected_status == "degraded":
    status_label = "Degraded"

info_col1, info_col2 = st.columns([2, 1])
with info_col1:
    st.markdown(f"### {layer_label(selected_layer)}")
    st.write(selected_layer["description"])
with info_col2:
    st.markdown("**Where it lives**")
    st.write(selected_layer["lives"])
    st.markdown("**Execution**")
    st.write(selected_layer["exec_type"])

with st.container(border=True):
    st.markdown("**Interpreted Summary**")
    st.write(selected_summary)
    if selected_version:
        st.write(f"Version / identity: {selected_version}")
    if selected_key == "L4.3":
        cni_confidence = state.get("evidence", {}).get("cni", {}).get("confidence", "unknown")
        st.write(f"Confidence: {cni_confidence}")
    st.write(f"Health / status: {status_label}")
    st.caption(f"Suggested debug entry point: `{selected_layer['api']}`")

detail_tab_explain, detail_tab_raw = st.tabs(["Explain", "Evidence (Raw)"])

with detail_tab_explain:
    st.caption("This tab shows the interpreted explanation generated from the structured state and deterministic ELS logic.")
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
        tab_els, tab_answer, tab_learning, tab_trace, tab_raw = st.tabs(
            ["ELS", "Answer", "Learning", "Trace", "Raw JSON"]
        )

        with tab_els:
            els = parsed.get("els", {})
            st.markdown("#### ELS Analysis")
            st.markdown(f"**Layer:** {els.get('layer', 'Unknown')}")
            st.markdown(f"**Layer Number:** {els.get('layer_number', '')}")
            st.markdown(f"**Layer Name:** {els.get('layer_name', '')}")
            st.markdown("**Explanation:**")
            st.write(els.get("explanation", ""))

            next_steps = els.get("next_steps", [])
            if next_steps:
                st.markdown("**Next Steps:**")
                for step in next_steps:
                    st.write(f"- {step}")

            mapped_context = els.get("mapped_context", {})
            if mapped_context:
                with st.expander("ELS mapped context"):
                    st.json(mapped_context)

        with tab_answer:
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

        with tab_learning:
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

        with tab_trace:
            trace = parsed.get("agent_trace", [])
            if trace:
                for step in trace:
                    with st.expander(f"Step {step.get('step', '?')}: {step.get('action', '')}"):
                        st.markdown(f"**Why:** {step.get('why', '')}")
                        st.markdown(f"**Outcome:** {step.get('outcome', '')}")
            else:
                st.write("No agent trace returned.")

        with tab_raw:
            st.json(parsed)

with detail_tab_raw:
    st.caption("This tab shows the raw supporting evidence for the selected layer without interpretation.")
    st.text(get_expand_text(selected_key, state)[:6000])

st.divider()
st.markdown("## Future Networking Visuals")
st.caption("Reserved space for a later network or policy diagram. This branch only prepares the layout cleanly.")
with st.container(border=True):
    st.markdown(
        '<div class="detail-note">Future Phase 2 diagram or policy visuals can be placed here below the focused layer detail area.</div>',
        unsafe_allow_html=True,
    )
