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
table_html="""
<style>
body {
    background-color: black;
    color: #00ff00;
    font-family: monospace;
}

.els-table {
    width: 100%;
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

st.title("🧠 CKA Coach — ELS Console")

# --------------------------
# Controls
# --------------------------
col1, col2 = st.columns(2)

auto_refresh = col1.checkbox("Auto Refresh", value=False)
interval = col2.slider("Refresh Interval (sec)", 2, 30, 5)

if auto_refresh:
    st._rerun()

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
    ("9", "Applications", "User containers", "User processes", "", "L9"),
    ("8", "Pods", "kubelet-managed", "Abstraction", "kubectl", "L8"),
    ("7", "K8S Objects", "etcd/API server", "Persistent state", "kubectl", "L7"),
    ("6", "Controllers", "control plane", "Control loops", "kubectl", "L6"),
    ("5", "kubelet", "systemd service", "Daemon", "systemctl", "L5"),
    ("4", "containerd", "systemd service", "CRI daemon", "crictl", "L4"),
    ("3", "Containers", "runtime processes", "Short-lived", "crictl", "L3"),
    ("2", "OCI (runc)", "invoked binary", "Exec", "ps", "L2"),
    ("1", "Kernel", "guest OS", "State machine", "ip / proc", "L1"),
    ("0", "VM/Infra", "GCP VM", "Virtualization", "", "L0"),
]

# --------------------------
# Render Table
# --------------------------
table_html += """
<table class="els-table">
<tr>
<th style="width:40px">Lvl</th>
<th style="width:240px">Layer</th>
<th style="width:240px">Lives</th>
<th style="width:200px">Execution Type</th>
<th style="width:200px">API</th>
<th>Current</th>
</tr>
"""

for lvl, name, lives, exec_type, api, key in layers:
    current, ok = summary.get(key, ("...", True))
    health = "🟢" if ok else "🔴"

    table_html += f"""
    <tr>
        <td>{lvl}</td>
        <td><div class="layer-name">{name}</div>{health}</td>
        <td>{lives}</td>
        <td>{exec_type}</td>
        <td>{api}</td>
        <td>{current}</td>
    </tr>
    """

table_html += "</table>"
st.write("Rendering table now...")

import streamlit.components.v1 as components
components.html(table_html, height=500, scrolling=True)

st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

# --------------------------
# Explain + Expand
# --------------------------
st.divider()

for lvl, name, _, _, _, key in layers:
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

