from els import load_els_model


def _clean(value: str) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return value


def _meaningful(value: str) -> bool:
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
    cleaned = [p.strip() for p in parts if _meaningful(p)]
    if not cleaned:
        return "No strong evidence collected for this layer yet."
    return "\n\n".join(cleaned)


def map_to_els(state: dict):
    """
    Map collected runtime state to the YAML-defined ELS model.
    Keys returned are aligned to the current els_schema.yaml.
    """
    schema = load_els_model()
    result = {}

    pods = _clean(state.get("pods", ""))
    events = _clean(state.get("events", ""))
    nodes = _clean(state.get("nodes", ""))
    kubelet = _clean(state.get("kubelet", ""))
    containerd = _clean(state.get("containerd", ""))
    containers = _clean(state.get("containers", ""))
    processes = _clean(state.get("processes", ""))
    network = _clean(state.get("network", ""))
    routes = _clean(state.get("routes", ""))
    api = _clean(state.get("api", ""))
    k8s_json = _clean(state.get("k8s_json", ""))

    for layer in schema.get("layers", []):
        layer_id = str(layer["id"])
        layer_name = layer.get("name", "")
        key = f"L{layer_id} {layer_name}"

        if layer_id == "9":
            result[key] = "User-facing application logic running inside containers."

        elif layer_id == "8":
            result[key] = _join_parts([
                pods,
            ])

        elif layer_id == "7":
            result[key] = _join_parts([
                events,
                k8s_json,
            ])

        elif layer_id == "6.5":
            result[key] = _join_parts([
                api,
                k8s_json,
            ])

        elif layer_id == "6":
            result[key] = _join_parts([
                events,
            ])

        elif layer_id == "5":
            result[key] = _join_parts([
                events,
                nodes,
            ])

        elif layer_id == "4":
            sub_lines = []

            if _meaningful(kubelet):
                sub_lines.append("[kubelet]\n" + kubelet)

            # kube-proxy isn't separately collected today, so use node/network clues if present
            if _meaningful(nodes):
                sub_lines.append("[node networking view]\n" + nodes)

            cni_text = _join_parts([network, routes])
            if _meaningful(cni_text) and cni_text != "No strong evidence collected for this layer yet.":
                sub_lines.append("[cni]\n" + cni_text)

            result[key] = _join_parts(sub_lines)

        elif layer_id == "3":
            result[key] = _join_parts([
                containerd,
                containers,
            ])

        elif layer_id == "2":
            result[key] = _join_parts([
                processes,
            ])

        elif layer_id == "1":
            result[key] = _join_parts([
                network,
                routes,
                processes,
            ])

        elif layer_id == "0":
            result[key] = "Virtualized compute, memory, disk, and network provided by the underlying cloud VM."

        else:
            result[key] = "No mapping implemented for this layer yet."

    return result
