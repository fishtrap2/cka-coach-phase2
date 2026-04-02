import streamlit as st
import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from state_collector import collect_state
from agent import ask_llm

# --------------------------
# Retro Styling
# --------------------------
st.set_page_config(layout="wide")
table_html="""
<style>
body {
    background-color: black;
    color: #00ff00;
    font-family: monospace;
}

.els-table {
    width: 150%;
    border-collapse: collapse;
}

.els-table th, .els-table td {
    border: 1px solid #00ff00;
    padding: 6px;
    vertical-align: top;
    font-size: 12px;
}

.els-table th {
    background-color: #001100;
}

.layer-name {
    font-weight: bold;
}

.health-ok {
    color: #00ff00;
}

.health-bad {
    color: red;
}
</style>
"""
def map_versions_to_layers(state):
    v = state.get("versions", {})

    return {
        "L6.5": v.get("api", ""),
        "L5": v.get("api", ""),          # controllers tied to API version
        "L4": v.get("kubelet", ""),
        "L3": v.get("containerd", ""),
        "L2": v.get("runc", ""),
        "L1": v.get("kernel", ""),
        "L3_cni": v.get("cni", ""),
    }

st.title("🧠 CKA Coach — ELS Console")

# --------------------------
# Controls
# --------------------------
col1, col2 = st.columns(2)

auto_refresh = col1.checkbox("Auto Refresh", value=False)
interval = col2.slider("Refresh Interval (sec)", 2, 30, 5)

if auto_refresh:
    st.rerun()

# --------------------------
# Helpers
# --------------------------
def summarize(state):
    pods = state.get("pods", "")
    pod_lines = [l for l in pods.split("\n") if l.strip()]

    total = max(len(pod_lines) - 1, 0)
    kube = len([l for l in pod_lines if "kube-system" in l])

    kubelet_ok = "active (running)" in state.get("kubelet", "")
    containerd_ok = "active (running)" in state.get("containerd", "")

    return {
        "L8": (f"{total} pods ({kube} kube-system)", kubelet_ok),
        "L5": ("kubelet running" if kubelet_ok else "kubelet issue", kubelet_ok),
        "L4": ("containerd running" if containerd_ok else "containerd issue", containerd_ok),
        "L3": (state.get("containers", "")[:100], True),
        "L1": ("network active", True),
    }

def clean_json(response):
    if "```" in response:
        response = response.split("```")[1].replace("json", "").strip()
    return response

# --------------------------
# Collect State
# --------------------------
with st.spinner("Collecting state..."):
    state = collect_state()
    summary = summarize(state)

# --------------------------
# Layer Definitions
# --------------------------
layers = [
    ("9", "Applications", "User-facing application logic", "application processes living inside containers", "app specific", "unkown", "L9"),
    ("8", "Pods", "Pod abstraction wrapping one or more containers", "kubelet-managed containers on nodes", "abstraction/meta", "kubectl get pods -o wide", "L8"),
    ("7", "K8S Objects", "Desired state definitions stored in API server", "Persistent state(etcd via kube-apiserver)", "abstraction/meta data", "kubectl cluster-info, kubectl config view", "L7"),
    ("6.5", "K8S API Layer", "Kubernetes API server and etcd (cluster state store)", "control-plane node (containers or processes)", "long_running_daemon", "kubectl get componentstatuses", "L6.5"),
    ("6", "Operators", "Custom controllers with domain-specific logic", "pods in cluster", "long_running_daemon", "kubectl get pods -n <operator-namespace>", "L6"),
    ("5", "Controllers", "Core reconciliation loops (deployment, replicaset, node)", "kube-controller-manager (is itself  a static pod)", "long running daemon", "kubectl get pods --all-namespaces", "L5"),
    ("4.1", "kubelet", "node level control agent", "workers and control plane nodes' systemd/PID1", "long running system service", "systemctl status kubelet", "L4.1"),
    ("4.2", "kube-proxy", "tasked with managing network connectivity for Pods", "lives as a kube-system pod (may be replaced by CNI plugins)", "long running daemon", "iptables -L -n -v", "L4.2"),
    ("4.3", "cni", "Container Network Interface & Plugin", "runs long enough to create veth pairs, assign IPs, attach pod to a bridge etc.", "short lived executable", "sudo ls /etc/cni/net.d/, ip route", "L4.3"),   
    ("3", "Container Runtime Interface - CRI (e.g. containerd or CRI-O)", "Enables node-level container management (start/stop/pull) by the kubelet.",  "systemd service on node", "CRI daemon", "crictl", "L4"),
    ("2", "OCI (runc)", "Low-level container executor or shim (e.g., runc)", "invoked by the CRI", "short lived executable", "ps aux | grep runc", "L2"),
    ("1", "Kernel", "Kernel providing namespaces, cgroups, networking", "guest OS inside of provider's VM", "Persistent State Machine", "ip / proc", "L1"),
    ("0", "VM/Infra", "Virtualized CPU, memory, network interfaces", "hypervisor-provided abstraction", "Virtualization Layer", "lscpu, lsblk", "L0"),
]

# --------------------------
# Render Table
# --------------------------
table_html += """
<table class="els-table">
<tr>
<th style="width:40px">Lvl</th>
<th style="width:100px">Layer</th>
<th style="width:140px">Version</th>
<th style="width:240px">Description</th>
<th style="width:240px">Lives</th>
<th style="width:200px">Execution Type</th>
<th style="width:200px">API</th>
<th style="width:680px">Current</th>
</tr>
"""
rows =""

for lvl, name, description, lives, exec_type, api, key in layers:
    current, ok = summary.get(key, ("...", True))
    version = versions_map.get(key, "")

    # Health Logic
     if key == "L8" and (health["pods_pending"] or health["pods_crashloop"]):
        row_color = "#220000"
        health_icon = "🔴"
    elif key == "L5" and not health["kubelet_ok"]:
        row_color = "#220000"
        health_icon = "🔴"
    elif key == "L4" and not health["containerd_ok"]:
        row_color = "#220000"
        health_icon = "🔴"
    else:
        row_color = "#001100"
        health_icon = "🟢"

    rows += f"""
    <tr style="background-color:{row_color}">
        <td>{lvl}</td>
        <td><div class="layer-name">{name}</div>{health_icon}</td>
        <td>{version}</td>
        <td>{lives}</td>
        <td>{exec_type}</td>
        <td>{api}</td>
        <td>{current}</td>
    </tr>
    """

    table_html += f"""
    <style>
    body {{
        background-color: black;
        color: #00ff00;
        font-family: monospace;
    }}
    .els-table {{
        width: 100%;
        border-collapse: collapse;
    }}
    .els-table td, .els-table th {{
        border: 1px solid #00ff00;
        padding: 6px;
    }}
    </style>
    
    <table class="els-table"> 
    <tr>
    <th>Lvl</th>
    <th>Layer</th>
    <th>Version</th>
    <th>Description</th>
    <th>Lives</th>
    <th>Execution</th>
    <th>API</th>
    <th>Current</th>
    </tr>
    {rows}
    </table>
    """

st.write("Rendering table now...")

st.markdown(table_html, unsafe_allow_html=True)

st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

st.write("Query LLM Here")

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
                context=str(state)
            )

            cleaned = clean_json(explanation)

            try:
                parsed = json.loads(cleaned)
                st.json(parsed)
            except:
                st.code(explanation)

    with col2:
        with st.expander(f"Expand L{lvl} — {name}"):
            st.text(state.get("pods", "")[:1000])

