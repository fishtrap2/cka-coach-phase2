from typing import Any, Dict, Iterable, List


BOUNDARY_ORDER = ["Cluster", "Node"]


def infer_boundary(command: str) -> str:
    text = (command or "").strip().lower()
    if not text:
        return "Node"
    if text.startswith("kubectl"):
        return "Cluster"
    return "Node"


def normalize_boundary_commands(entries: Iterable[Any]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {"Cluster": [], "Node": []}

    for entry in entries or []:
        if isinstance(entry, dict):
            boundary = str(entry.get("boundary", "Node")).strip().title()
            command = str(entry.get("command", "")).strip()
        else:
            boundary = infer_boundary(str(entry))
            command = str(entry).strip()

        if not command:
            continue

        if boundary not in grouped:
            grouped[boundary] = []

        grouped[boundary].append(command)

    return {
        boundary: commands
        for boundary, commands in grouped.items()
        if commands
    }


def format_boundary_commands_text(entries: Iterable[Any]) -> str:
    grouped = normalize_boundary_commands(entries)
    blocks: List[str] = []
    for boundary in BOUNDARY_ORDER:
        commands = grouped.get(boundary, [])
        if not commands:
            continue
        lines = [f"{boundary}:"]
        lines.extend(f"  {command}" for command in commands)
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def format_boundary_commands_html(entries: Iterable[Any]) -> str:
    grouped = normalize_boundary_commands(entries)
    blocks: List[str] = []
    for boundary in BOUNDARY_ORDER:
        commands = grouped.get(boundary, [])
        if not commands:
            continue
        commands_html = "".join(
            f'<div class="cmd-item">{command}</div>'
            for command in commands
        )
        blocks.append(
            f'<div class="cmd-group"><div class="cmd-boundary">{boundary}:</div>{commands_html}</div>'
        )
    return "".join(blocks)

