import src/schemas/els-schema.yaml

def load_els_model():
    with open("models/els_model.yaml", "r") as f:
        return yaml.safe_load(f)
