from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List


STEP_STATUSES = {
    "not_started",
    "ready",
    "waiting_for_coach",
    "waiting_for_student",
    "verifying",
    "completed",
    "blocked",
    "failed",
}


def lesson_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "id": "reset_networking_lab",
            "title": "Reset networking lab / clean residual CNI state",
            "description": (
                "Return the cluster to a known-good networking baseline by finding, "
                "reviewing, and safely remediating residual CNI state."
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


def default_lesson_progress() -> Dict[str, Any]:
    return {
        "current_step": 0,
        "inspect_ran": False,
        "classify_ran": False,
        "scripts_generated": False,
        "student_confirmed": False,
        "recheck_ran": False,
        "baseline_confirmed": False,
    }


def step_status_badge(status: str) -> str:
    return {
        "completed": "Completed",
        "ready": "Ready",
        "waiting_for_coach": "Coach action required",
        "waiting_for_student": "Student action required",
        "verifying": "Verification pending",
        "blocked": "Blocked",
        "failed": "Failed",
        "not_started": "Not started",
    }.get(status, status.replace("_", " ").title())


def step_status_icon(status: str) -> str:
    return {
        "completed": "✅",
        "ready": "➡️",
        "waiting_for_coach": "🧭",
        "waiting_for_student": "🧑‍💻",
        "verifying": "🔄",
        "blocked": "⛔",
        "failed": "❌",
        "not_started": "•",
    }.get(status, "•")


def append_coach_audit(
    session_state: Any,
    lesson_id: str,
    step_id: str,
    node_scope: str,
    target_nodes: List[str],
    action_type: str,
    command_or_check: str,
    result_summary: str,
    state_changed: bool,
    requires_student_action: bool,
) -> None:
    key = f"lesson_audit_{lesson_id}"
    entries = list(session_state.get(key, []))
    entries.insert(
        0,
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "step_id": step_id,
            "node_scope": node_scope,
            "target_nodes": target_nodes,
            "action_type": action_type,
            "command_or_check": command_or_check,
            "result_summary": result_summary,
            "state_changed": state_changed,
            "requires_student_action": requires_student_action,
        },
    )
    session_state[key] = entries[:12]


def ensure_initial_lesson_audit(
    session_state: Any,
    lesson_id: str,
    lesson: Dict[str, Any],
) -> None:
    marker = f"lesson_audit_initialized_{lesson_id}"
    if session_state.get(marker):
        return
    append_coach_audit(
        session_state,
        lesson_id,
        "initial_snapshot",
        "Cluster + local node",
        lesson.get("cleanup_target_nodes", []),
        "initial_scan",
        "collect_state() + lesson classification",
        (
            f"Initial classification is {lesson.get('classification', 'unknown')}; "
            f"cleanup required on {', '.join(lesson.get('cleanup_target_nodes', [])) or 'no nodes'}."
        ),
        state_changed=False,
        requires_student_action=bool(lesson.get("cleanup_target_nodes")),
    )
    session_state[marker] = True


def build_lesson_run(
    lesson_id: str,
    state: Dict[str, Any],
    progress: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    progress = {**default_lesson_progress(), **(progress or {})}
    if lesson_id == "reset_networking_lab":
        return _build_cleanup_lesson(state, progress)

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
        "cleanup_target_nodes": [],
        "per_node_status": [],
        "remediation_scripts": {},
    }


def _parse_node_names(runtime: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    nodes_json = runtime.get("nodes_json", "")
    if nodes_json.strip():
        try:
            import json

            data = json.loads(nodes_json)
            names = [item.get("metadata", {}).get("name", "") for item in data.get("items", [])]
            names = [name for name in names if name]
        except Exception:
            names = []

    if names:
        return names

    nodes_text = runtime.get("nodes", "")
    lines = [line for line in nodes_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    return [line.split()[0] for line in data_lines if line.split()]


def _parse_node_inventory(runtime: Dict[str, Any]) -> List[Dict[str, str]]:
    inventory: List[Dict[str, str]] = []
    nodes_json = runtime.get("nodes_json", "")
    if nodes_json.strip():
        try:
            import json

            data = json.loads(nodes_json)
            for item in data.get("items", []):
                addresses = item.get("status", {}).get("addresses", []) or []
                internal_ip = next(
                    (entry.get("address", "") for entry in addresses if entry.get("type") == "InternalIP"),
                    "",
                )
                inventory.append(
                    {
                        "name": item.get("metadata", {}).get("name", ""),
                        "internal_ip": internal_ip,
                    }
                )
        except Exception:
            inventory = []

    if inventory and any(entry.get("internal_ip") for entry in inventory):
        return [entry for entry in inventory if entry.get("name")]

    nodes_text = runtime.get("nodes", "")
    lines = [line for line in nodes_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    for line in data_lines:
        parts = line.split()
        if len(parts) >= 6:
            inventory.append(
                {
                    "name": parts[0],
                    "internal_ip": parts[5],
                }
            )
    return inventory


def _parse_local_ipv4s(runtime: Dict[str, Any]) -> List[str]:
    network_text = runtime.get("network", "")
    ips = re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)", network_text)
    return [ip for ip in ips if not ip.startswith("127.") and not ip.startswith("172.17.")]


def _resolve_local_node(node_names: List[str], runtime: Dict[str, Any]) -> str:
    inventory = _parse_node_inventory(runtime)
    local_ips = _parse_local_ipv4s(runtime)
    for ip in local_ips:
        for entry in inventory:
            if entry.get("internal_ip") == ip and entry.get("name"):
                return entry["name"]

    hostname = (runtime.get("hostname", "") or "").strip()
    if not hostname:
        return ""

    if hostname in node_names:
        return hostname

    for node in node_names:
        if hostname.startswith(node) or node.startswith(hostname):
            return node
    return hostname


def _parse_cni_pod_nodes(runtime: Dict[str, Any], current_cni: str) -> Dict[str, List[str]]:
    pods_text = runtime.get("pods", "")
    results: Dict[str, List[str]] = {}
    lines = [line for line in pods_text.splitlines() if line.strip()]
    data_lines = lines[1:] if len(lines) > 1 else []
    cni_patterns = {
        "calico": ["calico-node", "calico-kube-controllers"],
        "cilium": ["cilium", "cilium-operator", "cilium-envoy"],
    }.get(current_cni, [])
    if not cni_patterns:
        return results

    for line in data_lines:
        parts = line.split()
        if len(parts) < 8:
            continue
        namespace = parts[0]
        pod_name = parts[1]
        node_name = parts[7]
        if namespace != "kube-system":
            continue
        if any(pattern in pod_name.lower() for pattern in cni_patterns):
            results.setdefault(node_name, []).append(pod_name)
    return results


def _local_interface_presence(runtime: Dict[str, Any]) -> Dict[str, bool]:
    network_text = runtime.get("network", "").lower()
    return {
        "cilium_interfaces_present": any(name in network_text for name in ["cilium_host", "cilium_net", "lxc"]),
        "calico_interfaces_present": any(name in network_text for name in ["tunl0", "vxlan.calico", "cali"]),
    }


def _local_iptables_presence(runtime: Dict[str, Any]) -> Dict[str, bool | str]:
    iptables_text = runtime.get("iptables", "").lower()
    if not iptables_text.strip() or "not installed" in iptables_text:
        return {
            "calico_iptables_present": "unknown",
            "cilium_iptables_present": "unknown",
        }
    return {
        "calico_iptables_present": "cali-" in iptables_text or "calico" in iptables_text,
        "cilium_iptables_present": "cilium" in iptables_text,
    }


def _safe_residual_note(current_cni: str, artifact: str) -> str:
    if current_cni == "calico" and artifact in {"tunl0", "vxlan.calico"}:
        return "actively retained / recreated artifact — do not blindly remove"
    if current_cni == "cilium" and artifact.startswith("cilium"):
        return "actively retained / recreated artifact — do not blindly remove"
    return "safe residual candidate after review"


def _build_per_node_status(
    state: Dict[str, Any],
    classification_state: str,
    current_cni: str,
    local_node: str,
) -> List[Dict[str, Any]]:
    runtime = state.get("runtime", {})
    cni_evidence = state.get("evidence", {}).get("cni", {})
    classification = cni_evidence.get("classification", {})
    stale_taint = classification.get("stale_taint", {})
    stale_interfaces = classification.get("stale_interfaces", {})
    node_level = cni_evidence.get("node_level", {})
    cluster_pod_nodes = _parse_cni_pod_nodes(runtime, current_cni)
    interface_presence = _local_interface_presence(runtime)
    iptables_presence = _local_iptables_presence(runtime)
    node_names = _parse_node_names(runtime)
    now = datetime.now().strftime("%H:%M:%S")

    stale_taint_nodes = {item.get("node", "") for item in stale_taint.get("taints", [])}
    stale_interface_names = stale_interfaces.get("interfaces", [])

    statuses = []
    processed_nodes = set()
    local_residue_detected = bool(
        classification_state in {"stale_node_config", "stale_interfaces"}
        or stale_interface_names
        or iptables_presence["calico_iptables_present"] is True
        or iptables_presence["cilium_iptables_present"] is True
    )

    for node in node_names:
        processed_nodes.add(node)
        local = node == local_node
        residue_types: List[str] = []
        cleanup_required = False
        node_classification = "cluster_footprint_only"

        if node in stale_taint_nodes:
            residue_types.append("stale_taint")
            cleanup_required = True
            node_classification = "stale_taint"

        if local:
            if classification_state == "stale_node_config":
                residue_types.append("stale_node_config")
                cleanup_required = True
                node_classification = "stale_node_config"
            if stale_interface_names:
                residue_types.append("stale_interfaces")
                cleanup_required = True
                if node_classification == "cluster_footprint_only":
                    node_classification = "stale_interfaces"
            if iptables_presence["calico_iptables_present"] is True and current_cni != "calico":
                residue_types.append("calico_iptables")
                cleanup_required = True
            if iptables_presence["cilium_iptables_present"] is True and current_cni != "cilium":
                residue_types.append("cilium_iptables")
                cleanup_required = True
            if not residue_types and classification_state in {"healthy_calico", "healthy_cilium", "generic_cni", "no_cni"}:
                node_classification = classification_state
        elif node in cluster_pod_nodes:
            node_classification = f"{current_cni or 'cni'} cluster footprint"
        elif current_cni in {"calico", "cilium"}:
            node_classification = "node-local evidence unavailable"

        statuses.append(
            {
                "node": node,
                "scope": "Local node" if local else "Cluster-observed only",
                "cilium_interfaces_present": interface_presence["cilium_interfaces_present"] if local else "unknown",
                "calico_interfaces_present": interface_presence["calico_interfaces_present"] if local else "unknown",
                "calico_iptables_present": iptables_presence["calico_iptables_present"] if local else "unknown",
                "current_classification": node_classification,
                "residue_types": residue_types or ["none observed"],
                "cleanup_required": cleanup_required,
                "last_verified_at": now,
                "cluster_pods": cluster_pod_nodes.get(node, []),
                "local_visibility": local,
            }
        )

    if local_node and local_node not in processed_nodes and local_residue_detected:
        residue_types: List[str] = []
        if classification_state == "stale_node_config":
            residue_types.append("stale_node_config")
        if stale_interface_names:
            residue_types.append("stale_interfaces")
        if iptables_presence["calico_iptables_present"] is True and current_cni != "calico":
            residue_types.append("calico_iptables")
        if iptables_presence["cilium_iptables_present"] is True and current_cni != "cilium":
            residue_types.append("cilium_iptables")

        statuses.append(
            {
                "node": local_node,
                "scope": "Local node (unmatched to cluster node name)",
                "cilium_interfaces_present": interface_presence["cilium_interfaces_present"],
                "calico_interfaces_present": interface_presence["calico_interfaces_present"],
                "calico_iptables_present": iptables_presence["calico_iptables_present"],
                "current_classification": classification_state,
                "residue_types": residue_types or ["local_residual_state"],
                "cleanup_required": True,
                "last_verified_at": now,
                "cluster_pods": [],
                "local_visibility": True,
            }
        )
    return statuses


def _cleanup_target_nodes(per_node_status: List[Dict[str, Any]]) -> List[str]:
    return [entry["node"] for entry in per_node_status if entry.get("cleanup_required")]


def _generate_remediation_script_for_node(
    node_name: str,
    state: Dict[str, Any],
    current_cni: str,
    previous_cni: str,
    per_node_entry: Dict[str, Any],
) -> Dict[str, str]:
    cni_evidence = state.get("evidence", {}).get("cni", {})
    node_level = cni_evidence.get("node_level", {})
    classification = cni_evidence.get("classification", {})
    config_dir = node_level.get("config_dir", "/etc/cni/net.d")
    selected_file = node_level.get("selected_file", "")
    stale_config_path = f"{config_dir}/{selected_file}" if selected_file else ""
    stale_interfaces = classification.get("stale_interfaces", {}).get("interfaces", [])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"# Target node: {node_name}",
        "# Generated by cka-coach for review before any privileged cleanup.",
        "# cka-coach did NOT run this automatically.",
        "",
        "echo 'Review current CNI state on this node'",
        "hostname",
        "ip link show",
        "ip route",
        f"ls {config_dir}",
    ]

    if stale_config_path:
        lines.extend(
            [
                "",
                "# Review stale node-level config before moving it aside.",
                f"cat {stale_config_path}",
                f"# sudo mv {stale_config_path} {stale_config_path}.bak",
            ]
        )

    if stale_interfaces:
        lines.append("")
        lines.append("# Review leftover interfaces before deleting anything.")
        for iface in stale_interfaces:
            lines.append(f"# {iface}: {_safe_residual_note(current_cni, iface)}")
            if _safe_residual_note(current_cni, iface).startswith("safe residual candidate"):
                lines.append(f"# sudo ip link delete {iface}")
            else:
                lines.append(f"# inspect {iface} carefully before any deletion")

    if per_node_entry.get("residue_types") and "stale_taint" in per_node_entry.get("residue_types", []):
        lines.extend(
            [
                "",
                "# Cluster-scoped taint cleanup must be run from an admin shell with kubectl access.",
                f"# kubectl describe node {node_name} | grep -i taint",
                f"# kubectl taint nodes {node_name} <stale-taint-key>-",
            ]
        )

    lines.extend(
        [
            "",
            "# After running any reviewed commands, return to cka-coach and use:",
            "# I ran this — re-check",
        ]
    )

    explanation = (
        f"This script is scoped to node `{node_name}`. It focuses on reviewable cleanup for "
        f"{previous_cni if previous_cni != 'unknown' else 'previous CNI'} residue while avoiding "
        "blind removal of artifacts that may be actively recreated by the current plugin."
    )

    return {
        "filename": f"cleanup-cni-residuals-{node_name}.sh",
        "content": "\n".join(lines),
        "summary": explanation,
        "sudo_required": "yes",
    }


def _build_cleanup_steps(
    lesson: Dict[str, Any],
    progress: Dict[str, Any],
) -> List[Dict[str, Any]]:
    cleanup_targets = lesson.get("cleanup_target_nodes", [])
    all_nodes = [entry["node"] for entry in lesson.get("per_node_status", [])]
    classification_state = lesson.get("classification", "unknown")
    unresolved_targets = ", ".join(cleanup_targets) if cleanup_targets else "(none)"

    steps = [
        {
            "id": "inspect_current_state",
            "title": "Inspect current node and cluster state",
            "why": "Start by seeing exactly which nodes are dirty before any remediation is proposed.",
            "coach_can_do": True,
            "student_must_do": False,
            "target_scope": "Cluster + local node",
            "target_nodes": all_nodes,
            "coach_action": "Collect live state and summarize per-node residue.",
            "student_action": "",
            "verification": "Per-node status table is populated and current classification is visible.",
            "run_on": "Coach / cluster scan",
        },
        {
            "id": "classify_cleanup_scope",
            "title": "Classify cleanup scope and pause on risky residue",
            "why": "Distinguish safe residual candidates from actively retained artifacts before generating sudo actions.",
            "coach_can_do": True,
            "student_must_do": False,
            "target_scope": "All nodes",
            "target_nodes": cleanup_targets or all_nodes,
            "coach_action": "Classify each node as clean, residual, or needing careful review.",
            "student_action": "",
            "verification": "Cleanup targets are visible and risky artifacts are clearly labeled.",
            "run_on": "Coach / classification step",
        },
        {
            "id": "generate_remediation_scripts",
            "title": "Generate node-scoped remediation scripts",
            "why": "The coach should generate reviewable sudo steps instead of pretending it can perform privileged cleanup itself.",
            "coach_can_do": True,
            "student_must_do": False,
            "target_scope": "Node remediation",
            "target_nodes": cleanup_targets,
            "coach_action": "Generate cautious node-specific cleanup scripts or command blocks.",
            "student_action": "",
            "verification": "A remediation script is shown for each target node that still needs cleanup.",
            "run_on": "Coach / script generation",
        },
        {
            "id": "student_run_remediation",
            "title": "Run reviewed remediation on the target node(s)",
            "why": "Privileged cleanup belongs with the student on the correct node, not hidden inside the app.",
            "coach_can_do": False,
            "student_must_do": True,
            "target_scope": "Node remediation" if cleanup_targets else "No node remediation required",
            "target_nodes": cleanup_targets,
            "coach_action": "",
            "student_action": "Run the reviewed script on each target node, then return for verification.",
            "verification": "Student confirms the reviewed command/script was run on the listed target node(s).",
            "run_on": "Node shell with sudo/root access",
        },
        {
            "id": "recheck_target_nodes",
            "title": "Re-check the target node(s)",
            "why": "Do not trust button clicks. Re-collect evidence and see what actually changed.",
            "coach_can_do": True,
            "student_must_do": False,
            "target_scope": "Cluster + local node re-check",
            "target_nodes": cleanup_targets or all_nodes,
            "coach_action": "Re-collect evidence and compare against the previous node status snapshot.",
            "student_action": "",
            "verification": "Cleanup-required nodes should decrease or classification should improve.",
            "run_on": "Coach / cluster re-scan",
        },
        {
            "id": "confirm_baseline",
            "title": "Confirm a known-good baseline",
            "why": "The lesson is complete only when the cluster reaches a baseline the next install lesson can trust.",
            "coach_can_do": True,
            "student_must_do": False,
            "target_scope": "Cluster-wide",
            "target_nodes": all_nodes,
            "coach_action": "Confirm whether the cluster is now healthy, clean, or still transitional.",
            "student_action": "",
            "verification": "Classification has moved to a known-good baseline and cleanup-required nodes are gone.",
            "run_on": "Coach / final verification",
        },
    ]

    current_step = int(progress.get("current_step", 0))
    for idx, step in enumerate(steps):
        if idx < current_step:
            step["status"] = "completed"
        elif idx > current_step:
            step["status"] = "not_started"
        else:
            if step["id"] == "inspect_current_state":
                step["status"] = "completed" if progress.get("inspect_ran") else "waiting_for_coach"
            elif step["id"] == "classify_cleanup_scope":
                step["status"] = "completed" if progress.get("classify_ran") else "waiting_for_coach"
            elif step["id"] == "generate_remediation_scripts":
                step["status"] = "completed" if progress.get("scripts_generated") else "waiting_for_coach"
            elif step["id"] == "student_run_remediation":
                if not cleanup_targets:
                    step["status"] = "completed"
                elif progress.get("student_confirmed"):
                    step["status"] = "verifying"
                else:
                    step["status"] = "waiting_for_student"
            elif step["id"] == "recheck_target_nodes":
                if progress.get("recheck_ran"):
                    step["status"] = "completed"
                else:
                    step["status"] = "waiting_for_coach"
            elif step["id"] == "confirm_baseline":
                if lesson.get("baseline_ready") and progress.get("baseline_confirmed"):
                    step["status"] = "completed"
                elif progress.get("recheck_ran") and not lesson.get("baseline_ready"):
                    step["status"] = "blocked"
                else:
                    step["status"] = "waiting_for_coach"

        if step["id"] == "confirm_baseline" and not lesson.get("baseline_ready") and current_step >= 5:
            step["status"] = "blocked"

        if step["id"] == "student_run_remediation" and cleanup_targets:
            step["observed"] = (
                f"Target nodes requiring cleanup: {', '.join(cleanup_targets)}. "
                f"Current classification: {classification_state}."
            )
        elif step["id"] == "generate_remediation_scripts":
            step["observed"] = (
                "Scripts are ready for review."
                if progress.get("scripts_generated")
                else "Scripts have not been generated yet."
            )
        elif step["id"] == "confirm_baseline":
            if lesson.get("baseline_ready"):
                step["observed"] = "Known-good baseline verified."
            else:
                step["observed"] = (
                    f"Baseline is still blocked by residual state on: {unresolved_targets}. "
                    f"Current classification remains {classification_state}."
                )
                step["student_action"] = (
                    "Review the generated remediation scripts again, run the needed sudo cleanup on the unresolved node(s), then re-check."
                )
                step["verification"] = (
                    "Residual target nodes should drop to zero and classification should move to a known-good baseline."
                )

    return steps


def _build_cleanup_lesson(state: Dict[str, Any], progress: Dict[str, Any]) -> Dict[str, Any]:
    runtime = state.get("runtime", {})
    cni_evidence = state.get("evidence", {}).get("cni", {})
    classification = cni_evidence.get("classification", {})
    provenance = cni_evidence.get("provenance", {})
    current_cni = state.get("summary", {}).get("versions", {}).get(
        "cni",
        state.get("versions", {}).get("cni", "unknown"),
    )
    previous_cni = (
        provenance.get("previous_detected_cni", "unknown")
        or classification.get("previous_detected_cni", "unknown")
    )
    previous_cni = previous_cni if previous_cni not in {"", "unknown"} else "unknown"
    classification_state = classification.get("state", "unknown")
    classification_reason = classification.get("reason", "unknown")

    node_names = _parse_node_names(runtime)
    local_node = _resolve_local_node(node_names, runtime)
    per_node_status = _build_per_node_status(state, classification_state, current_cni, local_node)
    cleanup_target_nodes = _cleanup_target_nodes(per_node_status)
    baseline_ready = (
        classification_state in {"healthy_calico", "healthy_cilium", "generic_cni", "no_cni"}
        and not cleanup_target_nodes
    )

    remediation_scripts = {}
    if progress.get("scripts_generated"):
        for entry in per_node_status:
            if entry.get("cleanup_required"):
                remediation_scripts[entry["node"]] = _generate_remediation_script_for_node(
                    entry["node"],
                    state,
                    current_cni,
                    previous_cni,
                    entry,
                )

    lesson = {
        "id": "reset_networking_lab",
        "title": "Reset networking lab / clean residual CNI state",
        "description": (
            "Pause through a node-aware cleanup workflow. cka-coach shows what it sees, "
            "generates reviewable sudo steps, and re-verifies after the student acts."
        ),
        "classification": classification_state,
        "classification_reason": classification_reason,
        "current_detected_cni": current_cni,
        "previous_detected_cni": previous_cni,
        "provenance": provenance,
        "per_node_status": per_node_status,
        "cleanup_target_nodes": cleanup_target_nodes,
        "baseline_ready": baseline_ready,
        "local_node": local_node,
        "remediation_scripts": remediation_scripts,
        "overall_summary": (
            "We are orchestrating a paused remediation workflow so the lab returns to a baseline "
            "you can trust before the next networking lesson."
        ),
        "why_it_matters": (
            "Residual CNI state can survive migrations and make later install lessons unreliable. "
            "The coach will show scope, generate reviewable sudo steps, and verify outcomes after each pause."
        ),
    }

    steps = _build_cleanup_steps(lesson, progress)
    lesson["steps"] = steps
    current_step = min(int(progress.get("current_step", 0)), len(steps) - 1 if steps else 0)
    lesson["current_step"] = current_step
    completed_steps = sum(1 for step in steps if step.get("status") == "completed")
    lesson["completion_percentage"] = int((completed_steps / len(steps)) * 100) if steps else 0
    active_step = steps[current_step] if steps else {}

    if baseline_ready and progress.get("baseline_confirmed"):
        lesson_status = "completed"
    elif active_step.get("status") in {"waiting_for_student", "verifying"}:
        lesson_status = active_step.get("status")
    elif active_step.get("status") == "blocked":
        lesson_status = "blocked"
    else:
        lesson_status = "paused"

    lesson["status"] = lesson_status
    lesson["current_position_summary"] = (
        f"Current classification is {classification_state}. "
        f"The lesson is paused on step {current_step + 1} of {len(steps)}."
    )
    lesson["next_step_summary"] = active_step.get("why", "") if active_step else "Lesson complete."
    return lesson
