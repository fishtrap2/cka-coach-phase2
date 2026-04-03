from els import load_els_model


def build_els_layers():
    schema = load_els_model()
    layers = {}

    for layer in schema.get("layers", []):
        layer_id = str(layer["id"])
        entry = {
            "id": layer_id,
            "name": layer.get("name", ""),
            "description": layer.get("description", ""),
            "lives": layer.get("lives", ""),
            "execution_type": layer.get("execution_type", ""),
            "depends_on": layer.get("depends_on", []),
            "primary_interfaces": layer.get("primary_interfaces", []),
            "debug": layer.get("debug_commands", []),
        }

        # Preserve subcomponents for layer 4
        if "subcomponents" in layer:
            entry["subcomponents"] = layer["subcomponents"]

        layers[layer_id] = entry

    return layers


ELS_LAYERS = build_els_layers()
