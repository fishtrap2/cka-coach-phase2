from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


STEP_STATUSES = {
    "not_started",
    "ready",
    "in_progress",
    "completed",
    "blocked",
    "failed",
    "needs_student_action",
}


def lesson_catalog() -> List[Dict[str, Any]]:
    """
    Return the lightweight lesson repository shown in the coaching console.

    Keep this intentionally small for now:
    - one active cleanup/reset lesson
    - a few visible upcoming lessons so the screen feels like a reusable runner
    """
    return [
        {
            "id": "reset_networking_lab",
            "title": "Reset networking lab / clean residual CNI state",
            "description": (
                "Return the cluster to a known-good networking baseline by finding "
                "and removing stale CNI config, taints, and leftover interfaces."
            ),
            "available": True,
        },
        {
            "id": "install_cilium",
            "title": "Install Cilium",
            "description": "Coming soon: guided Cilium installation and verification.",
            "available": False,
        },
        {
            "id": "install_calico",
            "title": "Install Calico",
            "description": "Coming soon: guided Calico installation and verification.",
            "available": False,
        },
        {
            "id": "install_goldmane_whisker",
            "title": "Install Goldmane & Whisker",
            "description": "Coming soon: guided observability/platform add-on lesson.",
            "available": False,
        },
    ]


def build_lesson_run(lesson_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the current lesson run state from live collected evidence.
    """
    if lesson_id == "reset_networking_lab":
        return _build_cleanup_lesson(state)

    return {
        "id": lesson_id,
        "title": lesson_id,
        "description": "Lesson not yet available.",
        "status": "blocked",
        "current_step": 0,
        "completion_percentage": 0,
        "steps": [],
        "overall_summary": "This lesson has not been implemented yet.",
        "why_it_matters": "",
        "current_position_summary": "",
        "next_step_summary": "",
        "baseline_ready": False,
    }


def step_status_badge(status: str) -> str:
    return {
        "completed": "Completed",
        "needs_student_action": "Student action",
        "ready": "Ready",
        "in_progress": "In progress",
        "blocked": "Blocked",
        "failed": "Failed",
        "not_started": "Not started",
    }.get(status, status.replace("_", " ").title())


def step_status_icon(status: str) -> str:
    return {
        "completed": "✅",
        "needs_student_action": "🧑‍💻",
        "ready": "➡️",
        "in_progress": "🔄",
        "blocked": "⛔",
        "failed": "❌",
        "not_started": "•",
    }.get(status, "•")


def append_coach_activity(
    session_state: Any,
    lesson_id: str,
    action: str,
    why: str,
    outcome: str,
) -> None:
    key = f"lesson_activity_{lesson_id}"
    entries = list(session_state.get(key, []))
    entries.insert(
        0,
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": action,
            "why": why,
            "outcome": outcome,
        },
    )
    session_state[key] = entries[:8]


def ensure_initial_lesson_activity(
    session_state: Any,
    lesson_id: str,
    lesson: Dict[str, Any],
) -> None:
    marker = f"lesson_activity_initialized_{lesson_id}"
    if session_state.get(marker):
        return

    append_coach_activity(
        session_state,
        lesson_id,
        "Scanned current networking lesson state",
        "Establish a verified starting point before giving student steps.",
        (
            f"Current classification: {lesson.get('classification', 'unknown')}; "
            f"lesson status: {lesson.get('status', 'unknown')}."
        ),
    )
    session_state[marker] = True


def _build_cleanup_lesson(state: Dict[str, Any]) -> Dict[str, Any]:
    cni_evidence = state.get("evidence", {}).get("cni", {})
    classification = cni_evidence.get("classification", {})
    provenance = cni_evidence.get("provenance", {})
    node_level = cni_evidence.get("node_level", {})
    cluster_level = cni_evidence.get("cluster_level", {})
    cluster_footprint = cni_evidence.get("cluster_footprint", {})
    stale_taint = classification.get("stale_taint", {})
    stale_interfaces = classification.get("stale_interfaces", {})

    classification_state = classification.get("state", "unknown")
    classification_reason = classification.get("reason", "unknown")
    current_cni = state.get("summary", {}).get("versions", {}).get(
        "cni",
        state.get("versions", {}).get("cni", "unknown"),
    )
    previous_cni = (
        provenance.get("previous_detected_cni", "unknown")
        or classification.get("previous_detected_cni", "unknown")
    )
    previous_cni = previous_cni if previous_cni not in {"", "unknown"} else "unknown"

    stale_node_config = classification_state == "stale_node_config"
    stale_taint_detected = stale_taint.get("detected", False)
    stale_interfaces_detected = stale_interfaces.get("detected", False)
    mixed_or_transitional = classification_state == "mixed_or_transitional"

    baseline_ready = classification_state in {
        "healthy_calico",
        "healthy_cilium",
        "generic_cni",
        "no_cni",
    } and not stale_taint_detected and not stale_interfaces_detected

    config_dir = node_level.get("config_dir", "/etc/cni/net.d")
    selected_file = node_level.get("selected_file", "")
    stale_config_path = f"{config_dir}/{selected_file}" if selected_file else config_dir

    step_inspect_status = "completed"
    step_inspect = {
        "id": "inspect_residual_state",
        "title": "Inspect current residual networking state",
        "why": (
            "Start from observed evidence so cleanup work is driven by what is actually "
            "left behind, not by guesswork."
        ),
        "instructions": (
            "cka-coach already scanned current CNI config, cluster footprint, stale taints, "
            "leftover interfaces, and provenance."
        ),
        "coach_can_do": True,
        "student_must_do": False,
        "run_on": "Coach / cluster scan",
        "commands": [],
        "verification": "Current classification and residual signals are present in the lesson state.",
        "status": step_inspect_status,
        "observed": (
            f"Classification: {classification_state}. "
            f"Reason: {classification_reason}"
        ),
    }

    step_config_status = "completed" if not stale_node_config else "needs_student_action"
    step_config_observed = (
        "No stale node-level CNI config was detected."
        if not stale_node_config
        else (
            f"Node config still points to {node_level.get('cni', 'unknown')} via "
            f"{stale_config_path}, while current cluster evidence points to "
            f"{cluster_level.get('cni', current_cni) or current_cni}."
        )
    )
    step_config_commands = []
    if stale_node_config:
        step_config_commands = [
            f"ls {config_dir}",
            f"cat {stale_config_path}" if selected_file else f"ls {config_dir}",
            (
                f"sudo mv {stale_config_path} {stale_config_path}.bak"
                if selected_file
                else f"# review {config_dir} and move stale CNI config out of the active directory"
            ),
        ]
    step_config = {
        "id": "remove_stale_config",
        "title": "Remove stale node-level CNI config",
        "why": (
            "Old config files can keep a node pointing at the previous CNI and make the next "
            "install lesson unreliable."
        ),
        "instructions": (
            "Inspect the current node-level config first. If it still references the previous "
            "plugin, move it out of the active CNI config directory before installing another CNI."
        ),
        "coach_can_do": False,
        "student_must_do": True,
        "run_on": "Node: any affected node with stale CNI config",
        "commands": step_config_commands,
        "verification": (
            "Re-check that the old config file is gone from the active CNI directory and that "
            "classification is no longer stale_node_config."
        ),
        "status": step_config_status,
        "observed": step_config_observed,
    }

    taint_list = stale_taint.get("taints", [])
    step_taint_status = "completed" if not stale_taint_detected else "needs_student_action"
    taint_commands = []
    if stale_taint_detected:
        taint_commands.append("kubectl describe node <node> | grep -i taint")
        for taint in taint_list[:3]:
            taint_commands.append(f"kubectl taint nodes {taint.get('node', '<node>')} {taint.get('key', '<taint-key>')}-")
    step_taint = {
        "id": "remove_stale_taints",
        "title": "Remove stale CNI taints",
        "why": (
            "Old taints can keep scheduling and readiness behavior tied to a plugin that is "
            "no longer the active CNI."
        ),
        "instructions": (
            "Inspect node taints and remove only the taints that clearly belong to the previous CNI."
        ),
        "coach_can_do": False,
        "student_must_do": True,
        "run_on": "Cluster: use kubectl from any admin shell with cluster access",
        "commands": taint_commands,
        "verification": "Re-check nodes and confirm no stale CNI-specific taints remain.",
        "status": step_taint_status,
        "observed": (
            stale_taint.get("summary", "No stale CNI taints detected.")
            if stale_taint_detected
            else "No stale CNI taints detected."
        ),
    }

    interfaces = stale_interfaces.get("interfaces", [])
    step_interface_status = "completed" if not stale_interfaces_detected else "needs_student_action"
    interface_commands = []
    if stale_interfaces_detected:
        interface_commands = ["ip link show"]
        for iface in interfaces[:4]:
            interface_commands.append(f"sudo ip link delete {iface}")
    interface_observed = "No stale CNI interfaces detected."
    if stale_interfaces_detected:
        display_names = ", ".join(f"{iface} (may appear as {iface}@NONE in `ip link show`)" for iface in interfaces[:3])
        interface_observed = (
            f"Stale interfaces detected: {display_names}. Use the base interface name when deleting it."
        )
    step_interfaces = {
        "id": "remove_stale_interfaces",
        "title": "Clean up leftover CNI interfaces",
        "why": (
            "Residual node interfaces can keep dataplane artifacts from the previous CNI "
            "and confuse later troubleshooting."
        ),
        "instructions": (
            "Inspect leftover interfaces and remove only the ones that the lesson identifies as stale."
        ),
        "coach_can_do": False,
        "student_must_do": True,
        "run_on": "Node: the node where the stale interface was observed",
        "commands": interface_commands,
        "verification": "Re-check node interfaces and confirm stale CNI-specific links are gone.",
        "status": step_interface_status,
        "observed": interface_observed,
    }

    step_verify_status = "completed" if baseline_ready else ("ready" if not mixed_or_transitional else "in_progress")
    step_verify = {
        "id": "verify_clean_baseline",
        "title": "Re-verify a known-good networking baseline",
        "why": (
            "A cleanup lesson is only useful if the cluster returns to a state the student can trust "
            "before moving on to the next install lesson."
        ),
        "instructions": (
            "Ask cka-coach to re-scan the cluster after each cleanup action so it can verify whether "
            "the baseline is now clean, healthy, or still transitional."
        ),
        "coach_can_do": True,
        "student_must_do": False,
        "run_on": "Coach / cluster re-scan",
        "commands": [],
        "verification": (
            "Classification should move out of stale/transitional states and residual taints/interfaces "
            "should be gone."
        ),
        "status": step_verify_status,
        "observed": (
            "Known-good baseline verified."
            if baseline_ready
            else f"Current baseline is still {classification_state}."
        ),
    }

    steps = [
        step_inspect,
        step_config,
        step_taint,
        step_interfaces,
        step_verify,
    ]

    completed_steps = sum(1 for step in steps if step.get("status") == "completed")
    completion_percentage = int((completed_steps / len(steps)) * 100) if steps else 0

    current_step_index = next(
        (idx for idx, step in enumerate(steps) if step.get("status") != "completed"),
        len(steps) - 1 if steps else 0,
    )
    current_step = steps[current_step_index] if steps else {}

    if baseline_ready:
        lesson_status = "completed"
    elif current_step.get("status") == "needs_student_action":
        lesson_status = "needs_student_action"
    elif mixed_or_transitional:
        lesson_status = "in_progress"
    else:
        lesson_status = "ready"

    overall_summary = (
        "We are checking for leftover networking state so the lab returns to a baseline "
        "you can trust before the next CNI lesson."
    )
    if previous_cni != "unknown":
        overall_summary += f" Earlier evidence suggests the previous plugin may have been {previous_cni}."

    next_step_summary = (
        current_step.get("instructions", "")
        if current_step
        else "The lesson is complete."
    )

    return {
        "id": "reset_networking_lab",
        "title": "Reset networking lab / clean residual CNI state",
        "description": (
            "Find and remove stale networking residue so the cluster reaches a known-good baseline "
            "before the next install lesson."
        ),
        "status": lesson_status,
        "current_step": current_step_index,
        "completion_percentage": completion_percentage,
        "steps": steps,
        "overall_summary": overall_summary,
        "why_it_matters": (
            "Residual CNI state often explains why a cluster behaves strangely after migration. "
            "This lesson keeps the student grounded in current evidence and verified cleanup."
        ),
        "current_position_summary": (
            f"Current classification is {classification_state}. "
            f"Step {current_step_index + 1} of {len(steps)} is the next checkpoint."
        ),
        "next_step_summary": next_step_summary,
        "baseline_ready": baseline_ready,
        "classification": classification_state,
        "classification_reason": classification_reason,
        "current_detected_cni": current_cni,
        "previous_detected_cni": previous_cni,
        "provenance": provenance,
    }
