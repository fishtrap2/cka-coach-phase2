import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

def load_els_model():
    path = os.path.join(BASE_DIR, "src/schemas", "els_model.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)
