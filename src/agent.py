import json
from openai import OpenAI

from config import OPENAI_MODEL, MAX_CONTEXT_CHARS
from schemas import CoachResponse, ELSResult
from els import load_els_model
from els_model import ELS_LAYERS
from els_mapper import map_to_els

client = OpenAI()


# --------------------------
# Parse raw context into state
# --------------------------
def build_state_from_context(context: str) -> dict:
    """
    Current project passes plain-text cluster context around.
    We turn that into a simple state object that els_mapper can consume.
    """
    text = context[:MAX_CONTEXT_CHARS]

    return {
        "pods": text,
        "events": text,
        "nodes": text,
        "kubelet": text,
        "containerd": text,
        "containers": text,
        "processes": text,
        "network": text,
        "routes": text,
    }


# --------------------------
# Agent Trace
# --------------------------
def build_trace(question: str, context: str):
    return [
        {
            "step": 1,
            "action": "Interpret question",
            "why": "Determine which Kubernetes layer and resource type is relevant",
            "outcome": question,
        },
        {
            "step": 2,
            "action": "Build ELS state map",
            "why": "Map current cluster evidence into the Expanded Layered Stack model",
            "outcome": f"context size={len(context)} chars",
        },
        {
            "step": 3,
            "action": "Select primary ELS layer",
            "why": "Choose the most relevant layer to explain first, while preserving the broader layered view",
            "outcome": "Primary layer selected",
        },
    ]


# --------------------------
# Deterministic ELS selection
# --------------------------
def choose_primary_els_layer(question: str, context: str) -> tuple[str, str]:
    q = question.lower()
    c = context.lower()

    if "kubelet" in q or "kubelet" in c or "node agent" in q:
        return "L4 node_agents_and_networking", "4"

    if "kube-proxy" in q or "cni" in q or "network" in q or "route" in q or "iptables" in q:
        return "L4 node_agents_and_networking", "4"

    if "containerd" in q or "runc" in q or "cri" in q or "runtime" in q:
        return "L3 container_runtime", "3" if "containerd" in q or "cri" in q else ("L2 oci_runtime", "2")

    if "pod" in q or "crashloop" in q or "pending" in q:
        return "L8 application_pods", "8"

    if "deployment" in q or "service" in q or "configmap" in q or "secret" in q:
        return "L7 kubernetes_objects", "7"

    if "api server" in q or "apiserver" in q or "etcd" in q or "rest api" in q:
        return "L6.5 api_layer", "6.5"

    if "scheduler" in q or "controller" in q or "control plane" in q:
        return "L5 controllers", "5"

    if "operator" in q:
        return "L6 operators", "6"

    if "application" in q or "process" in q:
        return "L9 applications", "9"

    if "kernel" in q or "namespace" in q or "cgroup" in q or "syscall" in q:
        return "L1 linux_kernel", "1"

    if "vm" in q or "hardware" in q or "cpu" in q or "memory" in q or "disk" in q:
        return "L0 virtual_hardware", "0"

    return "L7 kubernetes_objects", "7"

def build_deterministic_els_result(question: str, context: str) -> ELSResult:
    """
    This is the important Phase 1 shift:
    ELS becomes deterministic project logic, not just prompt material.
    """
    _els_schema = load_els_model()
    state = build_state_from_context(context)
    mapped = map_to_els(state)

    primary_layer_key, layer_num = choose_primary_els_layer(question, context)
    layer_meta = ELS_LAYERS.get(layer_num, {})

    layer_name = layer_meta.get("name", primary_layer_key)
    debug_cmds = layer_meta.get("debug", [])

    explanation = (
        f"Based on the current question and collected context, the most relevant ELS layer is "
        f"{primary_layer_key}. In your ELS model, this corresponds to '{layer_name}'. "
        f"This layer is the best starting point because it is the closest match to the user's intent "
        f"and the visible cluster evidence."
    )

    next_steps = debug_cmds[:]
    if not next_steps:
        next_steps = ["Inspect the most relevant cluster object and work down the stack."]

    return {
        "layer": primary_layer_key,
        "layer_number": str(layer_num),
        "layer_name": layer_name,
        "explanation": explanation,
        "next_steps": next_steps,
        "mapped_context": mapped,
    }


# --------------------------
# Normalize model output
# --------------------------
def normalize_response(raw: str) -> CoachResponse:
    text = raw.strip()

    # Strip markdown fenced code block if present
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()

    try:
        return json.loads(text)
    except Exception:
        return {
            "raw_text": raw,
            "summary": "",
            "answer": raw,
            "els": {
                "layer": "Unknown",
                "layer_number": "",
                "layer_name": "",
                "explanation": "Model did not return valid JSON.",
                "next_steps": [],
                "mapped_context": {},
            },
            "learning": {
                "kubernetes": "",
                "ai": "",
                "platform": "",
                "product": "",
            },
            "agent_trace": [],
            "warnings": ["Response was not valid JSON."],
        }

# --------------------------
# Main LLM function
# --------------------------
def ask_llm(question: str, context: str = "") -> CoachResponse:
    try:
        trace = build_trace(question, context)
        els_result = build_deterministic_els_result(question, context)
        
        els_prompt_result = {
          "layer": els_result.get("layer", ""),
          "layer_number": els_result.get("layer_number", ""),
          "layer_name": els_result.get("layer_name", ""),
          "explanation": els_result.get("explanation", ""),
          "next_steps": els_result.get("next_steps", []),
        }

        payload = {
           "question": question,
           "context": context[:MAX_CONTEXT_CHARS],
           "els_result": els_prompt_result,
           "agent_trace": trace,
        }

        system_prompt = """
You are cka-coach, a Kubernetes + AI systems tutor.

You MUST:
- Treat the provided ELS result as deterministic project logic
- Use the provided agent trace
- Use ONLY the provided context
- Avoid guessing when evidence is incomplete
- Explain through 4 lenses:
  1. Kubernetes
  2. AI / Agents
  3. Platform Engineering
  4. Product Thinking

Important:
- Do not replace or contradict the provided ELS result unless you clearly say the evidence is incomplete.
- Expand and teach from the ELS result; do not invent a different layered analysis.

Return STRICT JSON only.
Do not wrap the JSON in markdown fences.
Do not add commentary before or after the JSON
"""

        user_prompt = f"""
DATA:
{json.dumps(payload, indent=2)}

Return JSON with exactly this shape:
{{
  "summary": "short summary",
  "answer": "main explanation",
  "els": {{
    "layer": "primary ELS layer",
    "layer_number": "ELS number",
    "layer_name": "ELS layer name",
    "explanation": "ELS-based reasoning",
    "next_steps": ["step 1", "step 2"],
    "mapped_context": {{}}
  }},
  "learning": {{
    "kubernetes": "what this teaches about Kubernetes",
    "ai": "what this teaches about AI agents or LLM systems",
    "platform": "what this teaches about platform engineering",
    "product": "what this teaches about product thinking"
  }},
  "agent_trace": [
    {{
      "step": 1,
      "action": "what the agent did",
      "why": "why it did that",
      "outcome": "what it found"
    }}
  ],
  "warnings": ["warning 1"]
}}

Use the provided els_result as the authoritative ELS analysis input.
"""

        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        parsed = normalize_response(response.output_text)

        # Preserve deterministic ELS if model omits or weakens it
        parsed["els"] = els_result

        if not parsed.get("agent_trace"):
            parsed["agent_trace"] = trace

        return parsed

    except Exception as e:
        return {
            "summary": "",
            "answer": "",
            "els": {
                "layer": "Error",
                "layer_number": "",
                "layer_name": "",
                "explanation": "",
                "next_steps": [],
                "mapped_context": {},
            },
            "learning": {
                "kubernetes": "",
                "ai": "",
                "platform": "",
                "product": "",
            },
            "agent_trace": [],
            "warnings": [],
            "error": str(e),
        }
