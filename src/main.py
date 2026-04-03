import typer
from rich import print
import tools
from agent import ask_llm
from els_model import ELS_LAYERS
app = typer.Typer()
@app.command()
def layers():
    """Show ELS layers"""
    for i, layer in ELS_LAYERS.items():
        print(f"[bold]{i}[/bold] - {layer['name']}")
@app.command()
def scan():
    """Scan cluster"""
    nodes = tools.kubectl_nodes()
    pods = tools.kubectl_pods()
    print("[bold green]Nodes[/bold green]")
    print(nodes)
    print("[bold green]Pods[/bold green]")
    print(pods)
@app.command()
import os
import yaml
import json
from openai import OpenAI

client = OpenAI()

BASE_DIR = os.path.dirname(os.path.dirname(__file__))


# --------------------------
# Load ELS Model (UNCHANGED)
# --------------------------
def load_els_model():
    path = os.path.join(BASE_DIR, "src/schemas", "els_schema.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


# --------------------------
# Build structured context
# --------------------------
def build_context(question: str, context: str):
    return {
        "question": question,
        "context": context[:4000]  # protect cluster + tokens
    }


# --------------------------
# Agent Trace (NEW)
# --------------------------
def build_trace(question, context):
    trace = [
        {
            "step": 1,
            "action": "Interpret question",
            "why": "Determine which Kubernetes layer and resource type is relevant",
            "outcome": question
        },
        {
            "step": 2,
            "action": "Attach cluster context",
            "why": "Provide real cluster evidence instead of hallucination",
            "outcome": f"context size={len(context)} chars"
        },
        {
            "step": 3,
            "action": "Apply ELS model",
            "why": "Map observations to layered Kubernetes mental model",
            "outcome": "ELS model loaded"
        }
    ]
    return trace


# --------------------------
# LLM call (UPDATED)
# --------------------------
def ask_llm(question: str, context: str = ""):
    try:
        els_model = load_els_model()
        trace = build_trace(question, context)

        payload = {
            "question": question,
            "context": context[:4000],
            "els_model": els_model,
            "agent_trace": trace
        }

        system_prompt = """
You are cka-coach, a Kubernetes + AI systems tutor.

You MUST:
- Use the provided ELS model as ground truth
- Use the provided agent trace
- Use ONLY provided context (no guessing)

You teach through 4 lenses:
1. Kubernetes
2. AI / Agents
3. Platform Engineering
4. Product Thinking

Return STRICT JSON.
"""

        response = client.responses.create(
            model="gpt-5",
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"""
DATA:
{json.dumps(payload, indent=2)}

Return JSON:
{{
  "summary": "",
  "answer": "",
  "els": {{
    "layer": "",
    "explanation": "",
    "next_steps": []
  }},
  "learning": {{
    "kubernetes": "",
    "ai": "",
    "platform": "",
    "product": ""
  }},
  "warnings": []
}}
"""
                }
            ],
        )

        raw = response.output_text

        try:
            return json.loads(raw)
        except Exception:
            return {"error": raw}

    except Exception as e:
        return {"error": str(e)}
