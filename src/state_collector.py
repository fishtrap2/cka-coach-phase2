import subprocess
def run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
    except subprocess.CalledProcessError as e:
        return e.output.decode()
def collect_state():
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
