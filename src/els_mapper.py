from els import load_els_model


def _clean(value: str) -> str:
    """
    Normalize a raw value into a trimmed string.

    Why:
    - state_collector may return None or empty values
    - mapping code is simpler if everything is treated as a string
    """
    if value is None:
        return ""
    return str(value).strip()


def _meaningful(value: str) -> bool:
    """
    Decide whether a piece of evidence is worth showing.

    We want to suppress placeholder / low-signal values that would confuse
    the student, such as 'No resources found' or 'unknown'.
    """
    if not value:
        return False

    lowered = value.lower().strip()

    if lowered in {
        "",
        "no resources found",
        "none",
        "null",
        "unknown",
    }:
        return False

    return True


def _join_parts(parts: list[str]) -> str:
    """
    Combine multiple evidence fragments into one display string.

    Only include evidence that passes _meaningful().
    If nothing useful exists, return a safe fallback string.
    """
    cleaned = [p.strip() for p in parts if _meaningful(_clean(p))]
    if not cleaned:
        return "No strong evidence collected for this layer yet."
    return "\n\n".join(cleaned)


def map_to_els(state: dict):
    """
    Map normalized collected state into the current YAML-defined ELS model.

    Important idea:
    - We do NOT hardcode a second competing layer model here.
    - We iterate over the YAML schema and attach the most relevant evidence
      to each layer.

    Expected normalized state keys:
      pods, events, nodes, kubelet, containerd, containers,
      processes, network, routes, api, k8s_json
    """
    schema = load_els_model()
    result = {}

    # Pull out normalized evidence once so the layer logic below is easier to read.
    pods = _clean(state.get("pods", ""))
    events = _clean(state.get("events", ""))
    nodes = _clean(state.get("nodes", ""))
    kubelet = _clean(state.get("kubelet", ""))
    containerd = _clean(state.get("containerd", ""))
    containers = _clean(state.get("containers", ""))
    processes = _clean(state.get("processes", ""))
    network = _clean(state.get("network", ""))
    routes = _clean(state.get("routes", ""))
    cni_detection = _clean(state.get("cni_detection", ""))
    api = _clean(state.get("api", ""))
    k8s_json = _clean(state.get("k8s_json", ""))

    # Walk through the source-of-truth ELS schema layer by layer.
    for layer in schema.get("layers", []):
        layer_id = str(layer["id"])
        layer_name = layer.get("name", "")

        # Example keys:
        #   L8 application_pods
        #   L4.5 api_layer
        #   L4 node_agents_and_networking
        key = f"L{layer_id} {layer_name}"

        # L9 = user-facing app logic.
        # We usually do not directly collect app-process evidence here,
        # so this remains a conceptual description unless later you add logs/exec detail.
        if layer_id == "9":
            result[key] = "User-facing application logic running inside containers."

        # L8 = pod abstraction / pod-level runtime view.
        # Best evidence today: kubectl pod listing / pod status text.
        elif layer_id == "8":
            result[key] = _join_parts([
                pods,
            ])

        # L7 = Kubernetes objects and desired state stored via API.
        # Best evidence today: events + API/json-derived version/state output.
        elif layer_id == "7":
            result[key] = _join_parts([
                events,
                k8s_json,
            ])

        # L4.5 = API server and etcd layer.
        # Best evidence today: API version/info plus k8s JSON.
        elif layer_id == "4.5":
            result[key] = _join_parts([
                api,
                k8s_json,
            ])

        # L6 = operators (custom controllers).
        # We do not yet collect operator-specific pod/log data,
        # so events are the lightest available signal here.
        elif layer_id == "6":
            result[key] = _join_parts([
                events,
            ])

        # L5 = core controllers / reconciliation behavior.
        # Events often reveal reconciliation issues; node state sometimes helps too.
        elif layer_id == "5":
            result[key] = _join_parts([
                events,
                nodes,
            ])

        # L4 = node agents and networking.
        # In the YAML schema this layer groups together:
        #   - kubelet
        #   - kube-proxy
        #   - CNI
        #
        # Since we do not yet collect kube-proxy separately,
        # we approximate with:
        #   - kubelet evidence
        #   - node view
        #   - network/routes evidence
        elif layer_id == "4":
            sub_lines = []

            if _meaningful(kubelet):
                sub_lines.append("[kubelet]\n" + kubelet)

            # kube-proxy is not collected directly yet, so node-level information
            # is the closest current clue we have for node-side networking/control.
            if _meaningful(nodes):
                sub_lines.append("[node networking view]\n" + nodes)

            # Combine network + routes into one CNI-oriented view.
            cni_text = _join_parts([cni_detection, network, routes])
            if _meaningful(cni_text) and cni_text != "No strong evidence collected for this layer yet.":
                sub_lines.append("[cni]\n" + cni_text)

            result[key] = _join_parts(sub_lines)

        # L3 = CRI/container runtime layer.
        # Best evidence: containerd service details + container listing.
        elif layer_id == "3":
            result[key] = _join_parts([
                containerd,
                containers,
            ])

        # L2 = OCI runtime layer.
        # Today we do not collect runc-specific output directly,
        # so process-level evidence is the nearest available approximation.
        elif layer_id == "2":
            result[key] = _join_parts([
                processes,
            ])

        # L1 = Linux kernel / networking substrate.
        # Best evidence today: network interfaces, routes, and some process-level OS clues.
        elif layer_id == "1":
            result[key] = _join_parts([
                network,
                routes,
                processes,
            ])

        # L0 = VM / virtual hardware.
        # This is currently conceptual because the collector does not yet gather
        # detailed host virtualization evidence.
        elif layer_id == "0":
            result[key] = "Virtualized compute, memory, disk, and network provided by the underlying cloud VM."

        else:
            result[key] = "No mapping implemented for this layer yet."

    return result
