import json
from openai import OpenAI

from config import OPENAI_MODEL, MAX_CONTEXT_CHARS
from schemas import CoachResponse, ELSResult
from els import load_els_model
from els_model import ELS_LAYERS
from els_mapper import map_to_els
from command_boundaries import normalize_boundary_commands, format_boundary_commands_text

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
    summary_versions = collected_state.get("summary", {}).get("versions", {})
    health = collected_state.get("health", {})
    cni_evidence = collected_state.get("evidence", {}).get("cni", {})
    kubelet_transitional_note = health.get("kubelet_transitional_note", "")
    containerd_transitional_note = health.get("containerd_transitional_note", "")
    node_level = cni_evidence.get("node_level", {})
    cluster_level = cni_evidence.get("cluster_level", {})

    cni_filenames = node_level.get("filenames", [])
    cni_filename_text = "\n".join(cni_filenames) if cni_filenames else "(none found)"
    matched_pods = cluster_level.get("matched_pods", [])
    matched_pod_text = "\n".join(matched_pods) if matched_pods else "(none found)"
    cni_name = summary_versions.get("cni", versions.get("cni", "")) or "unknown"
    cni_health = health.get("cni_ok", "unknown")
    capabilities = cni_evidence.get("capabilities", {})
    cluster_footprint = cni_evidence.get("cluster_footprint", {})
    daemonset_text = json.dumps(cluster_footprint.get("daemonsets", []), indent=2)
    calico_runtime = cni_evidence.get("calico_runtime", {})
    classification = cni_evidence.get("classification", {})
    event_history = cni_evidence.get("event_history", {})
    provenance = cni_evidence.get("provenance", {})
    policy_presence = cni_evidence.get("policy_presence", {})
    version = cni_evidence.get("version", {})
    config_spec_version = cni_evidence.get("config_spec_version", {})
    config_content = cni_evidence.get("config_content", "")
    migration_note = cni_evidence.get("migration_note", "unknown")
    policy_label = {
        "present": "present",
        "absent": "none detected",
        "unknown": "unknown",
    }.get(policy_presence.get("status", "unknown"), policy_presence.get("status", "unknown"))

    missing_or_unverified = []
    if cluster_level.get("cni", "unknown") == "unknown":
        missing_or_unverified.append("Current cluster footprint does not confirm an active CNI from kube-system pod names.")
    elif not matched_pods:
        missing_or_unverified.append("Cluster-level pod evidence is limited, so the full CNI component footprint is not fully visible.")
    if node_level.get("cni", "unknown") == "unknown":
        missing_or_unverified.append("No recognized node-level CNI config filename was detected.")
    elif not config_content.strip():
        missing_or_unverified.append("Node-level CNI config content was not directly collected from the selected file.")
    if (
        cluster_footprint.get("daemonset_count", 0) == 0
        and "not directly observed" in cluster_footprint.get("summary", "")
    ):
        missing_or_unverified.append("CNI DaemonSet presence or readiness was not directly collected from cluster evidence.")
    if version.get("value", "unknown") == "unknown":
        missing_or_unverified.append("The CNI plugin version is not directly evidenced from a single trustworthy image tag.")
    if cni_name == "calico" and calico_runtime.get("status") == "established":
        missing_or_unverified.append(
            "Direct Calico runtime evidence was collected from one calico-node pod, but it does not by itself prove identical BGP or health state on every node."
        )
    else:
        missing_or_unverified.append(
            "CNI-specific health output from the plugin itself is still not directly verified from the provided context."
        )
    if cni_evidence.get("reconciliation", "unknown") == "conflict":
        missing_or_unverified.append(
            "Cluster-level and node-level signals conflict, so the result is a lower-certainty inference rather than a well-supported conclusion."
        )
    if cni_evidence.get("reconciliation", "unknown") == "single_source":
        missing_or_unverified.append(
            "Only one evidence source identified a CNI, so the result remains a medium-confidence inference rather than a fully well-supported conclusion."
        )
    missing_or_unverified.append(
        "Pod IP assignment, interface output, and routes are supporting networking context, not primary CNI identification evidence."
    )
    missing_text = "\n".join(f"- {item}" for item in missing_or_unverified)

    cni_detection_text = (
        "[detected or inferred cni]\n"
        f"detected/inferred cni: {cni_name}\n"
        f"reconciliation: {cni_evidence.get('reconciliation', 'unknown')}\n"
        f"confidence: {cni_evidence.get('confidence', 'low')}\n"
        f"health/status meaning: {cni_health}\n\n"
        "[cluster-level evidence]\n"
        "primary cluster checks:\n"
        "kubectl get pods -n kube-system\n"
        "kubectl get ds -n kube-system\n"
        f"detected cni: {cluster_level.get('cni', 'unknown')}\n"
        f"confidence: {cluster_level.get('confidence', 'low')}\n"
        f"selected pod: {cluster_level.get('selected_pod', '') or '(none)'}\n"
        "matched kube-system pods:\n"
        f"{matched_pod_text}\n"
        "current matching daemonsets:\n"
        f"{daemonset_text}\n\n"
        "[node-level evidence]\n"
        "primary node checks:\n"
        "ls /etc/cni/net.d/\n"
        "cat /etc/cni/net.d/<config>\n"
        "ip route\n"
        f"detected cni: {node_level.get('cni', 'unknown')}\n"
        f"confidence: {node_level.get('confidence', 'low')}\n"
        f"selected file: {node_level.get('selected_file', '') or '(none)'}\n"
        "files in /etc/cni/net.d:\n"
        f"{cni_filename_text}\n\n"
        "[capability inference]\n"
        f"summary: {capabilities.get('summary', 'unknown')}\n"
        f"network policy: {capabilities.get('network_policy', 'unknown')}\n"
        f"policy model: {capabilities.get('policy_model', 'unknown')}\n"
        f"policy support: {capabilities.get('policy_support', 'unknown')}\n"
        f"observability: {capabilities.get('observability', 'unknown')}\n"
        f"inference basis: {capabilities.get('inference_basis', 'unknown')}\n\n"
        "[cluster footprint]\n"
        f"summary: {cluster_footprint.get('summary', 'cluster footprint not directly observed')}\n"
        f"operator present: {cluster_footprint.get('operator_present', False)}\n"
        f"daemonset count: {cluster_footprint.get('daemonset_count', 0)}\n"
        f"daemonsets: {json.dumps(cluster_footprint.get('daemonsets', []), indent=2)}\n\n"
        "[normalized classification]\n"
        f"state: {classification.get('state', 'unknown')}\n"
        f"reason: {classification.get('reason', 'unknown')}\n"
        f"notes: {json.dumps(classification.get('notes', []), indent=2)}\n"
        f"previous detected cni: {classification.get('previous_detected_cni', 'unknown')}\n\n"
        "[provenance]\n"
        f"available: {provenance.get('available', False)}\n"
        f"current detected cni: {provenance.get('current_detected_cni', 'unknown')}\n"
        f"previous detected cni: {provenance.get('previous_detected_cni', 'unknown')}\n"
        f"last cleaned at: {provenance.get('last_cleaned_at', '') or '(unknown)'}\n"
        f"cleaned by: {provenance.get('cleaned_by', '') or '(unknown)'}\n"
        f"last install observed at: {provenance.get('last_install_observed_at', '') or '(unknown)'}\n"
        f"evidence basis: {provenance.get('evidence_basis', 'unknown')}\n\n"
        "[calico runtime evidence]\n"
        f"summary: {calico_runtime.get('summary', 'not applicable for current CNI')}\n"
        f"status: {calico_runtime.get('status', 'unknown')}\n"
        f"pod: {calico_runtime.get('pod', '') or '(none)'}\n"
        f"bird ready: {calico_runtime.get('bird_ready', False)}\n"
        f"established peers: {calico_runtime.get('established_peers', 0)}\n"
        f"protocol lines: {json.dumps(calico_runtime.get('protocol_lines', []), indent=2)}\n\n"
        "[version evidence]\n"
        f"observed version: {version.get('value', 'unknown')}\n"
        f"source: {version.get('source', 'unknown')}\n"
        f"pod: {version.get('pod', '') or '(none)'}\n"
        f"image: {version.get('image', '') or '(none)'}\n\n"
        "[cni config spec evidence]\n"
        f"observed cniVersion: {config_spec_version.get('value', 'unknown')}\n"
        f"source: {config_spec_version.get('source', 'unknown')}\n"
        f"file: {config_spec_version.get('file', '') or '(none)'}\n"
        "selected config content:\n"
        f"{config_content or '(none)'}\n\n"
        "[historical events / recent transitions]\n"
        f"summary: {event_history.get('summary', 'no relevant CNI event history collected')}\n"
        f"relevant lines: {json.dumps(event_history.get('relevant_lines', []), indent=2)}\n"
        "Use this section as historical transition context, not as the primary basis for current CNI identification.\n\n"
        "[policy presence summary]\n"
        f"status: {policy_label}\n"
        f"count: {policy_presence.get('count', 0)}\n"
        f"namespaces: {', '.join(policy_presence.get('namespaces', [])) or '(none)'}\n\n"
        "[migration or reconciliation note]\n"
        f"{migration_note}\n\n"
        "[missing or unverified evidence]\n"
        f"{missing_text}\n\n"
        "[confidence and health/status meaning]\n"
        f"confidence: {cni_evidence.get('confidence', 'low')}\n"
        f"health/status meaning: {cni_health}"
    )

    return {
        "pods": runtime.get("pods", ""),
        "events": runtime.get("events", ""),
        "nodes": runtime.get("nodes", ""),
        "network_policies": runtime.get("network_policies", ""),
        "kubelet": runtime.get("kubelet", "")
        + (
            "\n\n[kubelet health note]\n" + kubelet_transitional_note
            if kubelet_transitional_note
            else ""
        ),
        "containerd": runtime.get("containerd", "")
        + (
            "\n\n[containerd health note]\n" + containerd_transitional_note
            if containerd_transitional_note
            else ""
        ),
        "containers": runtime.get("containers", ""),
        "processes": runtime.get("processes", ""),
        "network": runtime.get("network", ""),
        "routes": runtime.get("routes", ""),
        "cni_detection": cni_detection_text,
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
        return "L4.5 api_layer", "4.5"

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


def _first_meaningful_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and "No strong evidence" not in stripped:
            return stripped
    return "Current evidence is limited, so start from the nearest inspection boundary."


def _build_cni_guided_plan(collected_state: dict) -> list[dict]:
    runtime = collected_state.get("runtime", {})
    evidence = collected_state.get("evidence", {}).get("cni", {})
    summary_versions = collected_state.get("summary", {}).get("versions", {})
    cni_name = summary_versions.get("cni", collected_state.get("versions", {}).get("cni", "unknown"))
    classification = evidence.get("classification", {})
    cluster_level = evidence.get("cluster_level", {})
    node_level = evidence.get("node_level", {})
    cluster_footprint = evidence.get("cluster_footprint", {})
    calico_runtime = evidence.get("calico_runtime", {})
    event_history = evidence.get("event_history", {})
    selected_file = node_level.get("selected_file", "") or "<config>"
    matched_pods = cluster_level.get("matched_pods", [])
    daemonset_count = cluster_footprint.get("daemonset_count", 0)
    cluster_commands = [
        "kubectl get pods -n kube-system",
        "kubectl get ds -n kube-system",
    ]
    node_commands = [
        "ls /etc/cni/net.d/",
        f"cat /etc/cni/net.d/{selected_file}",
        "ip route",
    ]
    if cni_name == "calico" and calico_runtime.get("pod"):
        cluster_commands.append(
            f"kubectl -n kube-system exec {calico_runtime.get('pod')} -- birdcl show protocols"
        )

    plan = [
        {
            "title": "Validate the current cluster CNI footprint",
            "why": (
                f"The current classification is {classification.get('state', 'unknown')}, and the strongest current-state check is whether "
                f"{cni_name} pods and daemonsets are still present right now."
            ),
            "commands": cluster_commands,
            "interpretation": (
                f"If kube-system still shows the expected {cni_name} footprint and daemonsets are Ready, continue to node config and datapath checks. "
                "If the footprint is absent or mismatched, treat the state as stale or transitional rather than assuming the old plugin is still active."
            ),
        },
        {
            "title": "Verify node-level config provenance",
            "why": (
                f"Node-level evidence currently points to {node_level.get('cni', 'unknown')} via {selected_file}, so confirm whether the node config matches the live cluster footprint."
            ),
            "commands": node_commands,
            "interpretation": (
                "If the config file names the same plugin as the current cluster footprint, the node and cluster evidence agree. "
                "If the file still names a different plugin, this is stale_node_config or mixed_or_transitional rather than a generic CNI state."
            ),
        },
    ]

    if cni_name == "calico" and calico_runtime.get("status") != "not_applicable":
        plan.append(
            {
                "title": "Confirm the live Calico datapath before trusting old events",
                "why": (
                    "Direct runtime evidence from calico-node is more trustworthy for current health than historical readiness or restart events."
                ),
                "commands": [f"kubectl -n kube-system exec {calico_runtime.get('pod', '<calico-node-pod>')} -- birdcl show protocols"],
                "interpretation": (
                    "If BGP peers are Established, the datapath is live enough to treat old event warnings as historical context. "
                    "If BIRD is not ready or peers are missing, the active networking issue is still in the CNI datapath."
                ),
            }
        )

    if event_history.get("relevant_lines"):
        plan.append(
            {
                "title": "Correlate current state with recent transitions",
                "why": "Recent events can explain why the cluster entered a stale or transitional state, but they should not override stronger current-state evidence.",
                "commands": ["kubectl get events -A --sort-by=.lastTimestamp"],
                "interpretation": (
                    "Use events to understand timing and restarts. If events mention the old plugin but current pods, daemonsets, and config disagree, trust the current-state checks first."
                ),
            }
        )

    return plan[:4]


def _build_generic_guided_plan(layer_num: str, layer_name: str, mapped_context: str, debug_cmds: list[str]) -> list[dict]:
    grouped = normalize_boundary_commands(debug_cmds)
    evidence_line = _first_meaningful_line(mapped_context)
    plan: list[dict] = []

    titles = {
        "8": "Validate current pod state",
        "7": "Inspect the desired-state object first",
        "4.5": "Confirm API/control-plane reachability",
        "6": "Inspect the operator control loop",
        "5": "Check reconciliation behavior closest to the symptom",
        "4": "Inspect the active node boundary first",
        "3": "Validate the container runtime service",
        "2": "Check the low-level OCI executor path",
        "1": "Inspect the kernel-facing substrate",
        "0": "Validate the virtual infrastructure surface",
        "9": "Inspect the user workload directly",
    }

    why = f"The strongest current evidence for {layer_name} is: {evidence_line}"
    if grouped.get("Cluster"):
        plan.append(
            {
                "title": titles.get(layer_num, "Start at the nearest cluster-facing boundary"),
                "why": why,
                "commands": grouped["Cluster"],
                "interpretation": (
                    "If the cluster-facing view matches the expected objects or status, move one layer lower. "
                    "If it already looks wrong here, the issue is still in this layer's control surface."
                ),
            }
        )
    if grouped.get("Node"):
        plan.append(
            {
                "title": "Validate the node/runtime boundary",
                "why": f"{layer_name} also depends on local runtime evidence, so check the node-facing surface next.",
                "commands": grouped["Node"],
                "interpretation": (
                    "If node-facing state is healthy and consistent, the problem likely sits higher in the stack. "
                    "If node-facing state is unhealthy, stay in this layer before moving outward."
                ),
            }
        )
    if layer_num not in {"5", "7"}:
        plan.append(
            {
                "title": "Correlate with recent cluster events",
                "why": "Events help explain recent restarts, reconciliations, or transitions that led to the current state.",
                "commands": ["kubectl get events -A --sort-by=.lastTimestamp"],
                "interpretation": (
                    "Use events to explain timing and sequence. Treat them as supporting context rather than proof of current health if stronger current-state evidence exists."
                ),
            }
        )

    return plan[:4]


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
    mapped_context = mapped.get(primary_layer_key, "")

    explanation = (
        f"Based on the current question and collected context, the most relevant ELS layer is "
        f"{primary_layer_key}. In your ELS model, this corresponds to '{layer_name}'. "
        f"This layer is the best starting point because it most closely matches the student's question "
        f"and the structured cluster evidence."
    )

    if layer_num == "4":
        guided_plan = _build_cni_guided_plan(collected_state)
    else:
        guided_plan = _build_generic_guided_plan(
            str(layer_num),
            layer_name,
            mapped_context,
            debug_cmds,
        )

    next_steps = [step.get("title", "") for step in guided_plan]

    return {
        "layer": primary_layer_key,
        "layer_number": str(layer_num),
        "layer_name": layer_name,
        "explanation": explanation,
        "next_steps": next_steps,
        "guided_investigation_plan": guided_plan,
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
                "guided_investigation_plan": [],
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
            "primary_layer_context": els_result.get("mapped_context", {}).get(
                els_result.get("layer", ""),
                "",
            )[:2000],
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

        cni_answer_policy = ""
        if "cni" in question.lower() or "container network interface" in question.lower():
            cni_answer_policy = """
For CNI explanations, structure the "answer" field with these exact section labels:
Current interpretation
What we know
What supports it at cluster level
What supports it at node level
What is still unverified
Final confidence/health conclusion

Use precise language:
- prefer phrasing like high-confidence inference, well-supported conclusion, and supported by direct cluster-level evidence over wording that overstates certainty
- do not overclaim when evidence is partial or conflicting
- do not treat pod IP assignment alone as primary CNI identification evidence
- do not imply observed policy enforcement when only platform capability or NetworkPolicy object presence is shown
- when primary_layer_context contains structured CNI evidence, treat it as the authoritative basis for the explanation ahead of the generic compact context
- use the combined confidence from primary_layer_context exactly as written for the overall conclusion
- if combined confidence is medium, do not describe the overall interpretation as high-confidence
- if cluster-level evidence is strong but combined confidence is only medium, describe that as direct cluster-level support with a medium-confidence overall conclusion
- if health/status meaning is degraded, describe the CNI as present but partially healthy or degraded; do not call it healthy
- keep health/status meaning aligned with primary_layer_context; if it says unknown, describe visibility as limited rather than healthy or degraded
- only describe the CNI as healthy when primary_layer_context explicitly says health/status meaning: healthy
- use the normalized classification and provenance sections when present to explain whether the state looks healthy, mixed, stale, or transitional
- prioritize current cluster evidence (pods, daemonsets, direct runtime checks) and current node evidence (config files, config content, routes) over historical event mentions
- if current cluster footprint is absent but node config explicitly says Calico or Cilium, say that directly and use stale_node_config or mixed_or_transitional wording rather than generic_cni
- treat any historical events / recent transitions section as supporting context about recent changes, not as the primary basis for current CNI identification
- do not warn that generic pod listings are truncated if primary_layer_context already contains sufficient cluster-level CNI evidence
- only warn about incomplete, weak, or conflicting evidence when the primary_layer_context itself shows that limitation
"""

        system_prompt = f"""
You are cka-coach, a Kubernetes + AI systems tutor.

Rules:
- Treat the provided ELS result as deterministic project logic
- For kubelet, kube-proxy, and CNI be more explicit and clear in your responses (for example: kubelet is not a pod, it is a systemd service; clearly state which CNI plugin is in use if evidence is present)
- Base answers on the provided data and instructions.
- Avoid guessing when evidence is incomplete.
- Return ONLY valid JSON.
- Do not wrap the JSON in markdown fences.
- Do not add commentary before or after the JSON.

Knowledge policy:
{knowledge_policy}

Style policy:
{concise_policy}
{cni_answer_policy}
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
    "next_steps": ["step 1", "step 2"],
    "guided_investigation_plan": []
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
                "guided_investigation_plan": [],
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
