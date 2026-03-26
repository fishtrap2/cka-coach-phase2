def map_to_els(state: dict):
    return {
        "L9 Applications": "User workloads running inside containers",
        "L8 Pods": state.get("pods", ""),
        "L7 K8S Objects / API": state.get("events", ""),
        "L6 Controllers / Scheduling": state.get("nodes", ""),
        "L5 Node Agents (kubelet)": state.get("kubelet", ""),
        "L4 Container Runtime (containerd)": state.get("containerd", ""),
        "L3 Containers (crictl)": state.get("containers", ""),
        "L2 Processes": state.get("processes", ""),
        "L1 Network (CNI / kernel)": state.get("network", "") + "\n\n" + state.get("routes", ""),
        "L0 Infrastructure": "VM / GCP underlying infrastructure",
    }
