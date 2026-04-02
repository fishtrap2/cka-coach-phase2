import subprocess
import json

# --------------------------
# Core runner
# --------------------------
def run(cmd: str) -> str:
    try:
        return subprocess.check_output(
            cmd, shell=True, stderr=subprocess.STDOUT, text=True
        )
    except subprocess.CalledProcessError as e:
        return e.output


# --------------------------
# Runtime State
# --------------------------
def collect_runtime():
    return {
        "pods": run("kubectl get pods -A -o wide"),
        "nodes": run("kubectl get nodes -o wide"),
        "events": run("kubectl get events -A --sort-by=.metadata.creationTimestamp"),
        "kubelet": run("systemctl status kubelet --no-pager"),
        "containerd": run("systemctl status containerd --no-pager"),
        "containers": run("crictl ps"),
        "images": run("crictl images"),
        "processes": run("ps aux | grep -E 'kube|containerd'"),
        "network": run("ip addr"),
        "routes": run("ip route"),
    }


# --------------------------
# Version Collection
# --------------------------
def collect_versions():
    return {
        "k8s_json": run("kubectl version -o json"),
        "kubelet": run("kubelet --version"),
        "containerd": run("containerd --version"),
        "runc": run("runc --version"),
        "crictl": run("crictl --version"),
        "cni": run("ls /etc/cni/net.d/"),
        "kernel": run("uname -r"),
    }


# --------------------------
# Health Signals
# --------------------------
def collect_health(runtime):
    return {
        "kubelet_ok": "active (running)" in runtime.get("kubelet", ""),
        "containerd_ok": "active (running)" in runtime.get("containerd", ""),
        "pods_pending": "Pending" in runtime.get("pods", ""),
        "pods_crashloop": "CrashLoopBackOff" in runtime.get("pods", ""),
    }


# --------------------------
# Version Parsing (CLEAN)
# --------------------------
def parse_versions(v):
    parsed = {}

    # Kubernetes API version (clean JSON parse)
    try:
        data = json.loads(v.get("k8s_json", "{}"))
        parsed["api"] = data.get("serverVersion", {}).get("gitVersion", "")
    except:
        parsed["api"] = ""

    parsed["kubelet"] = v.get("kubelet", "").strip().split("\n")[0]
    parsed["containerd"] = v.get("containerd", "").strip().split("\n")[0]
    parsed["runc"] = v.get("runc", "").split("\n")[0]
    parsed["kernel"] = v.get("kernel", "").strip()

    # CNI plugin (first config file)
    cni_lines = v.get("cni", "").strip().split("\n")
    parsed["cni"] = cni_lines[0] if cni_lines else ""

    return parsed


# --------------------------
# Unified State Entry Point
# --------------------------
def collect_state():
    runtime = collect_runtime()
    versions_raw = collect_versions()

    return {
        "runtime": runtime,
        "versions_raw": versions_raw,
        "versions": parse_versions(versions_raw),
        "health": collect_health(runtime),
    }
