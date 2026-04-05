import json
from openai import OpenAI

from config import OPENAI_MODEL, MAX_CONTEXT_CHARS
from schemas import CoachResponse, ELSResult
from els import load_els_model
from els_model import ELS_LAYERS
from els_mapper import map_to_els

# OpenAI client used for the explanatory / teaching layer.
# Important: the model is no longer the owner of the ELS logic.
# Python computes the deterministic ELS result first, then the LLM explains it.
client = OpenAI()


def build_trace(question: str, state: dict):
    """
    Build a simple deterministic trace of what cka-coach did.

    This is useful for:
    - teaching students how the agent reasoned
    - debugging the system
    - making the AI behavior less "mysterious"

    We derive a lightweight trace from the structured state rather than
    asking the model to hallucinate a trace afterward.
    """
    runtime = state.get("runtime", {})
    versions = state.get("versions", {})

    return [
        {
            "step": 1,
            "action": "Interpret question",
            "why": "Determine which Kubernetes layer or runtime concept the student is asking about",
            "outcome": question,
        },
        {
            "step": 2,
            "action": "Normalize collected cluster state",
            "why": "Use structured evidence instead of one large unstructured text blob",
            "outcome": f"runtime_keys={list(runtime.keys())}, version_keys={list(versions.keys())}",
        },
        {
            "step": 3,
            "action": "Map evidence into ELS layers",
            "why": "Assign the collected evidence to the most relevant ELS layers",
            "outcome": "ELS mapping complete",
        },
        {
            "step": 4,
            "action": "Select primary ELS layer",
            "why": "Choose the best starting layer for the student's question",
            "outcome": "Primary layer selected",
        },
    ]


def normalize_collected_state(collected_state: dict) -> dict:
    """
    Convert state_collector.collect_state() output into the flatter normalized
    structure expected by els_mapper.map_to_els().

    Why this exists:
    - dashboard.py already uses collect_state()
    - collect_state() returns nested sections like runtime / versions / health
    - els_mapper.py wants a flatter dictionary keyed by evidence type

    This function is the bridge between those two shapes.
    """
    runtime = collected_state.get("runtime", {})
    versions = collected_state.get("versions", {})

    return {
        "pods": runtime.get("pods", ""),
        "events": runtime.get("events", ""),
        "nodes": runtime.get("nodes", ""),
        "kubelet": runtime.get("kubelet", ""),
        "containerd": runtime.get("containerd", ""),
        "containers": runtime.get("containers", ""),
        "processes": runtime.get("processes", ""),
        "network": runtime.get("network", ""),
        "routes": runtime.get("routes", ""),
        "api": versions.get("api", ""),
        "k8s_json": versions.get("k8s_json", ""),
    }


def choose_primary_els_layer(question: str, normalized_state: dict) -> tuple[str, str]:
    """
    Deterministically choose the single most relevant ELS layer for the question.

    Important:
    - this is a heuristic router, not a full inference engine
    - it gives the model a stable starting point
    - it prevents the LLM from inventing its own layer taxonomy

    Returns:
      (layer_label, layer_id_as_string)

    Example:
      ("L4 node_agents_and_networking", "4")
    """
    q = question.lower()

    # Questions about kubelet, kube-proxy, CNI, iptables, routes, etc.
    # belong primarily to the node-agent/networking layer.
    if "kubelet" in q or "node agent" in q:
        return "L4 node_agents_and_networking", "4"

    if "kube-proxy" in q or "cni" in q or "network" in q or "route" in q or "iptables" in q:
        return "L4 node_agents_and_networking", "4"

    # Questions about containerd / CRI belong to the container runtime layer.
    if "containerd" in q or "cri" in q:
        return "L3 container_runtime", "3"

    # Questions about runc / OCI belong to the OCI runtime layer.
    if "runc" in q or "oci" in q:
        return "L2 oci_runtime", "2"

    # Pod lifecycle issues belong primarily to the pod abstraction layer.
    if "pod" in q or "crashloop" in q or "pending" in q:
        return "L8 application_pods", "8"

    # Objects like deployments, services, configmaps, secrets map to k8s objects.
    if "deployment" in q or "service" in q or "configmap" in q or "secret" in q:
        return "L7 kubernetes_objects", "7"

    # Questions about the apiserver / etcd / REST API go to the API layer.
    if "api server" in q or "apiserver" in q or "etcd" in q or "rest api" in q:
        return "L6.5 api_layer", "6.5"

    # Scheduler / controllers / control plane questions generally map to controllers.
    if "scheduler" in q or "controller" in q or "control plane" in q:
        return "L5 controllers", "5"

    # Operator questions map to custom controllers/operators.
    if "operator" in q:
        return "L6 operators", "6"

    # App/process questions go to the application layer.
    if "application" in q or "process" in q:
        return "L9 applications", "9"

    # Kernel primitives map to the linux kernel layer.
    if "kernel" in q or "namespace" in q or "cgroup" in q or "syscall" in q:
        return "L1 linux_kernel", "1"

    # VM / hardware / compute resource questions map to virtual hardware.
    if "vm" in q or "hardware" in q or "cpu" in q or "memory" in q or "disk" in q:
        return "L0 virtual_hardware", "0"

    # Fallback strategy:
    # if we have pod evidence, start from pods;
    # otherwise fall back to kubernetes objects.
    if normalized_state.get("pods"):
        return "L8 application_pods", "8"

    return "L7 kubernetes_objects", "7"


def build_deterministic_els_result(question: str, collected_state: dict) -> ELSResult:
    """
    Build the deterministic ELS result used as authoritative project logic.

    This is the heart of the architecture shift:
    - Python computes the ELS result
    - the LLM explains and teaches from it
    - the LLM does NOT invent the ELS result from scratch

    Output includes:
    - primary layer
    - layer number
    - layer name
    - explanation
    - next debug steps
    - full mapped_context (for debugging / dashboard inspection)
    """
    # Load the schema mainly to ensure the source-of-truth model exists and is available.
    # Even if we do not use the raw schema object directly here, this keeps the dependency explicit.
    _els_schema = load_els_model()

    # Normalize the nested collector output into the flatter mapper input.
    normalized_state = normalize_collected_state(collected_state)

    # Build a per-layer evidence map for visibility/debugging.
    mapped = map_to_els(normalized_state)

    # Select the primary layer for the current question.
    primary_layer_key, layer_num = choose_primary_els_layer(question, normalized_state)

    # Look up layer metadata from the schema-derived ELS_LAYERS structure.
    layer_meta = ELS_LAYERS.get(layer_num, {})

    layer_name = layer_meta.get("name", primary_layer_key)
    debug_cmds = layer_meta.get("debug", [])

    explanation = (
        f"Based on the current question and collected context, the most relevant ELS layer is "
        f"{primary_layer_key}. In your ELS model, this corresponds to '{layer_name}'. "
        f"This layer is the best starting point because it most closely matches the student's question "
        f"and the structured cluster evidence."
    )

    # Prefer schema-derived debug commands when available.
    next_steps = debug_cmds[:] if debug_cmds else [
        "Inspect the most relevant cluster object and work down the stack."
    ]

    return {
        "layer": primary_layer_key,
        "layer_number": str(layer_num),
        "layer_name": layer_name,
        "explanation": explanation,
        "next_steps": next_steps,
        "mapped_context": mapped,
    }


def normalize_response(raw: str) -> CoachResponse:
    """
    Normalize model output into the CoachResponse shape.

    Why this exists:
    - sometimes models still wrap JSON in ```json fences
    - we want the CLI/dashboard to remain stable even if formatting drifts

    Behavior:
    - strip markdown fences if present
    - try json.loads()
    - if parsing fails, return a fallback object with raw_text
    """
    text = raw.strip()

    # Handle fenced JSON like:
    # ```json
    # { ... }
    # ```
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


def build_llm_context(collected_state: dict) -> str:
    """
    Build a compact context payload for the model.

    Important product decision:
    - do NOT send the entire mapped_context to the LLM
    - do NOT send every raw collector field in full
    - keep the prompt smaller for speed and focus

    We include only the most relevant structured evidence, truncated to
    reasonable lengths so dashboard Explain buttons stay responsive.
    """
    normalized = normalize_collected_state(collected_state)

    compact = {
        "nodes": normalized.get("nodes", "")[:800],
        "pods": normalized.get("pods", "")[:800],
        "events": normalized.get("events", "")[:500],
        "kubelet": normalized.get("kubelet", "")[:400],
        "containerd": normalized.get("containerd", "")[:400],
        "network": normalized.get("network", "")[:500],
        "routes": normalized.get("routes", "")[:400],
        "api": normalized.get("api", ""),
    }

    return json.dumps(compact, indent=2)[:MAX_CONTEXT_CHARS]


def ask_llm(question: str, collected_state: dict, concise: bool = False, allow_web: bool = False) -> CoachResponse:
    """
    Main entrypoint used by CLI and dashboard.

    Input:
    - question: student's question
    - collected_state: structured output from state_collector.collect_state()

    Flow:
    1. build deterministic trace
    2. build deterministic ELS result
    3. send a compact evidence package + ELS result to the model
    4. parse model JSON
    5. overwrite model-returned ELS with deterministic project logic
    6. attach deterministic trace
    """
    try:
        # Deterministic project-side reasoning
        trace = build_trace(question, collected_state)
        els_result = build_deterministic_els_result(question, collected_state)

        # Only send the compact subset of ELS needed for explanation.
        # Do NOT send mapped_context here, because it bloats prompts and slows everything down.
        els_prompt_result = {
            "layer": els_result.get("layer", ""),
            "layer_number": els_result.get("layer_number", ""),
            "layer_name": els_result.get("layer_name", ""),
            "explanation": els_result.get("explanation", ""),
            "next_steps": els_result.get("next_steps", []),
        }

        payload = {
            "question": question,
            "context": build_llm_context(collected_state),
            "els_result": els_prompt_result,
            "concise": concise,
            "allow_web": allow_web,
        }

        knowledge_policy = """
        Use only the provided cluster context.
        Do not use outside knowledge.
        """

       if allow_web:
           knowledge_policy = """
       Use the provided cluster context first.
       You may also use general background knowledge when needed.
       Do NOT claim to have performed a live web lookup.
       For compatibility, support matrix, or version questions:
       - clearly separate cluster evidence from background knowledge
       - state when official vendor documentation is still required for confirmation
       """

       concise_policy = ""
       if concise:
         concise_policy = """
       Keep summary and answer short and direct.
       Keep next_steps to at most 3 items.
       Keep warnings minimal and important.
       """
       system_prompt = """
You are cka-coach, a Kubernetes + AI systems tutor.

Rules:
- Treat the provided ELS result as deterministic project logic
- For kubelet, kube-proxy, and CNI be more explicit & verbose in your responses (e.g. kubelet is not a pod, it is a systemd service, state clearly which CNI plugin is being use)
- Base answers on the provided data and instructions.
- Avoid guessing when evidence is incomplete
- Return ONLY valid JSON.
- Do not wrap the JSON in markdown fences.
- Do not add commentary before or after the JSON.
Knowledge policy:
{knowledge_policy}

Style policy:
{concise_policy}
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
    "explanation": "ELS-based reasoning",
    "next_steps": ["step 1", "step 2"]
  }},
  "learning": {{
    "kubernetes": "what this teaches about Kubernetes",
    "ai": "what this teaches about AI agents or LLM systems",
    "platform": "what this teaches about platform engineering",
    "product": "what this teaches about product thinking"
  }},
  "warnings": ["warning 1"]
}}
"""
         #System vs. User Roles:
         #System --> Permanent rules of the product:
         #  you are cka-coach
         #  deterministic ELS is authoritative
         #  output must be valid JSON
         #  do not invent agent trace
         #User or Per-request details:
         #     here is the question
         #     here is the collected state
         #     concise = true/false
         #     allow_web = true/false
         #     here is the exact output schema
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        parsed = normalize_response(response.output_text)

        # Enforce deterministic project logic after model response.
        # Even if the model returns its own ELS block, we overwrite it with the
        # Python-generated result so the product stays consistent and trustworthy.
        parsed["els"] = els_result

        # Same idea for the agent trace: do not let the model invent it.
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
