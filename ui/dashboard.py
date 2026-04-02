import streamlit as st
import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from state_collector import collect_state
from agent import ask_llm

st.set_page_config(layout="wide")
st.title("🧠 CKA Coach — ELS Console")

# --------------------------
# Retro Styling (separate from table HTML)
# --------------------------
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
</style>
"""

# --------------------------
# Controls
# --------------------------
col1, col2, col3 = st.columns([1, 1, 2])

auto_refresh = col1.checkbox("Auto Refresh", value=False)
interval = col2.slider("Refresh Interval (sec)", 2, 30, 5)
if col3.button("Refresh Now"):
    st.rerun()

# Note: this is a simple rerun toggle, not timed refresh.
# A timed refresh can be added later with st_autorefresh.

# --------------------------
# Helpers
# --------------------------
def clean_json(response: str) -> str:
    if "```" in response:
        parts = response.split("```")
        if len(parts) > 1:
            response = parts[1].replace("json", "").strip()
    return response


def summarize(state: dict) -> dict:
    runtime = state.get("runtime", {})
    health = state.get("health", {})
    versions = state.get("versions", {})

    pods_text = runtime.get("pods", "")
    pod_lines = [l for l in pods_text.splitlines() if l.strip()]
    data_lines = pod_lines[1:] if len(pod_lines) > 1 else []

    total_pods = len(data_lines)
    kube_system_pods = sum(1 for l in data_lines if l.startswith("kube-system "))
    default_pods = sum(1 for l in data_lines if l.startswith("default "))
    pending_pods = sum(1 for l in data_lines if " Pending " in f" {l} ")
    crashloop_pods = sum(1 for l in data_lines if "CrashLoopBackOff" in l)

    kubelet_ok = health.get("kubelet_ok", False)
    containerd_ok = health.get("containerd_ok", False)

    cni_name = versions.get("cni", "")
    kernel_ver = versions.get("kernel", "")
    containerd_ver = versions.get("containerd", "")
    kubelet_ver = versions.get("kubelet", "")
    runc_ver = versions.get("runc", "")
    api_ver = versions.get("api", "")

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
        "L4.1": ("kubelet running" if kubelet_ok else "kubelet issue", kubelet_ok),
        "L4.2": ("kube-proxy / service routing", True),
        "L4.3": (f"CNI config: {cni_name or 'unknown'}", True),
        "L3": ("containerd running" if containerd_ok else "containerd issue", containerd_ok),
        "L2": (runc_ver or "runc version unknown", True),
        "L1": (f"kernel {kernel_ver or 'unknown'}", True),
        "L0": ("VM / virtual hardware", True),
    }


def map_versions_to_layers(state: dict) -> dict:
    v = state.get("versions", {})
    return {
        "L9": "",
        "L8": "",
        "L7": v.get("api", ""),
        "L6.5": v.get("api", ""),
        "L6": v.get("api", ""),
        "L5": v.get("api", ""),
        "L4.1": v.get("kubelet", ""),
        "L4.2": v.get("api", ""),      # kube-proxy usually tracks cluster version
        "L4.3": v.get("cni", ""),
        "L3": v.get("containerd", ""),
        "L2": v.get("runc", ""),
        "L1": v.get("kernel", ""),
        "L0": "",
    }


def get_expand_text(key: str, state: dict) -> str:
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
        "L4.3": runtime.get("network", "") + "\n\n" + runtime.get("routes", ""),
        "L3": runtime.get("containerd", "") + "\n\n" + runtime.get("containers", ""),
        "L2": versions.get("runc", ""),
        "L1": runtime.get("network", "") + "\n\n" + versions.get("kernel", ""),
        "L0": runtime.get("nodes", ""),
    }

    return mapping.get(key, json.dumps({
        "versions": versions,
        "health": health,
    }, indent=2))


# --------------------------
# Collect State
# --------------------------
with st.spinner("Collecting state..."):
    state = collect_state()

summary = summarize(state)
versions_map = map_versions_to_layers(state)
health = state.get("health", {})

# --------------------------
# Layer Definitions
# --------------------------
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

# --------------------------
# Build table rows ONCE
# --------------------------
rows = ""

for lvl, name, description, lives, exec_type, api, key in layers:
    current, ok = summary.get(key, ("...", True))
    version = versions_map.get(key, "")

    if key == "L8" and (health.get("pods_pending", False) or health.get("pods_crashloop", False)):
        row_color = "#220000"
        health_icon = "🔴"
    elif key == "L4.1" and not health.get("kubelet_ok", True):
        row_color = "#220000"
        health_icon = "🔴"
    elif key == "L3" and not health.get("containerd_ok", True):
        row_color = "#220000"
        health_icon = "🔴"
    else:
        row_color = "#001100"
        health_icon = "🟢"

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
# Render table ONCE
# --------------------------
table_html += f"""
<table class="els-table">
    <tr>
        <th style="width:40px">Lvl</th>
        <th style="width:120px">Layer</th>
        <th style="width:140px">Version</th>
        <th style="width:240px">Description</th>
        <th style="width:240px">Lives</th>
        <th style="width:180px">Execution</th>
        <th style="width:180px">API</th>
        <th>Current</th>
    </tr>
    {rows}
</table>
"""
import streamlit.components.v1 as components
components.html(table_html, height=1000, scrolling=True)

st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

# --------------------------
# Explain + Expand
# --------------------------
st.divider()

for lvl, name, _, _, _, _, key in layers:
    col1, col2 = st.columns([1, 3])

    with col1:
        if st.button(f"Explain L{lvl}", key=f"btn_{lvl}"):
            explanation = ask_llm(
                f"Explain current state of {name}",
                context=get_expand_text(key, state)
            )

            cleaned = clean_json(explanation)

            try:
                parsed = json.loads(cleaned)
                st.json(parsed)
            except Exception:
                st.code(explanation)

    with col2:
        with st.expander(f"Expand L{lvl} — {name}"):
            st.text(get_expand_text(key, state)[:3000])
