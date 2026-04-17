import typer
from rich import print

import tools
from agent import ask_llm
from els_model import ELS_LAYERS
from state_collector import collect_state

# Typer gives us a clean CLI with subcommands like:
#   python src/main.py layers
#   python src/main.py scan
#   python src/main.py ask "where does kubelet run?"
app = typer.Typer()


@app.command()
def layers():
    """
    Show the current ELS layers known to the application.

    Why this exists:
    - helps verify that els_model.py is loading correctly
    - gives the student/developer a quick view of the layer taxonomy
    - useful after schema/model refactors to confirm layer names and IDs

    Output example:
      4 - node_agents_and_networking
      6.5 - api_layer
    """
    for layer_id, layer in ELS_LAYERS.items():
        print(f"[bold]{layer_id}[/bold] - {layer['name']}")


@app.command()
def scan():
    """
    Run a quick raw cluster scan using the older kubectl helper functions.

    Why keep this:
    - useful for debugging when you want raw node/pod output quickly
    - useful for comparing the old direct kubectl path with the newer
      structured collect_state() path

    Important:
    - this is NOT the preferred data path for Gen2 reasoning
    - the ask() command now uses collect_state() instead
    """
    nodes = tools.kubectl_nodes()
    pods = tools.kubectl_pods()

    print("[bold green]Nodes[/bold green]")
    print(nodes)

    print("[bold green]Pods[/bold green]")
    print(pods)


@app.command()
def ask(
    question: str,
    concise: bool = typer.Option(
        False,
        "--concise",
        help="Only show Summary, Answer, Next Steps, and Warnings.",
    ),
    allow_web: bool = typer.Option(
        False,
        "--allow-web",
        help="Allow the agent/LLM to use external web information when needed.",
    ),
    allow_host_evidence: bool = typer.Option(
        False,
        "--allow-host-evidence",
        help="Allow cka-coach to use explicitly exposed host-mounted or user-provided evidence paths.",
    ),
):
    """
    Ask cka-coach a question from the CLI.

    Current Gen2 flow:
    1. collect structured cluster state using collect_state()
    2. pass that state into agent.ask_llm()
    3. agent.py computes deterministic ELS output
    4. the LLM explains the result through multiple learning lenses
    5. print the structured response

    Example:
      python src/main.py ask "where does kubelet run?"
      python src/main.py ask "is kubernetes v1.33.1 compatible with calico 3.30?" --concise --allow-web
    """
    # Use the same structured collection path as the dashboard.
    # This is important because we want one trustworthy source of evidence
    # for both CLI and UI.
    state = collect_state(allow_host_evidence=allow_host_evidence)

    # Pass through the new switches.
    # NOTE: ask_llm() must be updated to accept these keyword args.
    result = ask_llm(question, state, concise=concise, allow_web=allow_web)

    # Hard error path: the OpenAI call or agent logic failed.
    if result.get("error"):
        print(f"[red]LLM error: {result['error']}[/red]")
        return

    # Soft failure path: the model returned something that could not be parsed
    # as JSON. We show the raw output for debugging instead of pretending it worked.
    if result.get("raw_text"):
        print("[yellow]Warning: model response was not parsed as JSON.[/yellow]")

        print("\n[bold]Raw Response[/bold]")
        print(result["raw_text"])
        return

    # --------
    # Summary
    # --------
    from config import OPENAI_MODEL
    print(f"\n[bold]Summary API USING: ({OPENAI_MODEL})[/bold]")
    print(result.get("summary", ""))

    # -------
    # Answer
    # -------
    print("\n[bold]Answer[/bold]")
    print(result.get("answer", ""))

    # -------------------------
    # Concise mode ends here,
    # except for Next Steps and Warnings
    # -------------------------
    if concise:
        next_steps = (
            result.get("next_steps")
            or result.get("els", {}).get("next_steps", [])
        )
        if next_steps:
            print("\n[bold]Next Steps[/bold]")
            for step in next_steps:
                print(f"- {step}")

        warnings = result.get("warnings", [])
        if warnings:
            print("\n[bold]Warnings[/bold]")
            for warning in warnings:
                print(f"- {warning}")

        return

    # ----
    # ELS
    # ----
    # This is the deterministic project-side ELS result.
    # It is generated in Python and attached after the LLM response so that
    # the app remains consistent and trustworthy.
    els = result.get("els", {})

    #print("\n[bold]ELS[/bold]")
    #print(f"Layer: {els.get('layer', '')}")
    #print(f"Layer Number: {els.get('layer_number', '')}")
    #print(f"Layer Name: {els.get('layer_name', '')}")
    #print(els.get("explanation", ""))

    next_steps = els.get("next_steps", [])
    if next_steps:
        print("\n[bold]Next Steps[/bold]")
        for step in next_steps:
            print(f"- {step}")

    # ----------
    # Learning
    # ----------
    # These four views are generated by the LLM to help the student learn
    # the same situation through multiple lenses:
    # - Kubernetes
    # - AI / Agents
    # - Platform Engineering
    # - Product Thinking
    #learning = result.get("learning", {})

    #print("\n[bold]Learning[/bold]")

    #print("\n[Kubernetes]")
    #print(learning.get("kubernetes", ""))

    #print("\n[AI / Agents]")
    #print(learning.get("ai", ""))

    #print("\n[Platform]")
    #print(learning.get("platform", ""))

    #print("\n[Product]")
    #print(learning.get("product", ""))

    # ---------
    # Warnings
    # ---------
    warnings = result.get("warnings", [])
    if warnings:
        print("\n[bold]Warnings[/bold]")
        for warning in warnings:
            print(f"- {warning}")

    # -----------
    # Agent Trace
    # -----------
    # This is deterministic agent-side reasoning, not a model-invented trace.
    # It shows the student how cka-coach approached the question.
    #trace = result.get("agent_trace", [])
    #if trace:
    #    print("\n[bold]Agent Trace[/bold]")
    #    for step in trace:
    #        print(f"\nStep {step.get('step', '?')}: {step.get('action', '')}")
    #        print(f"  Why: {step.get('why', '')}")
    #        print(f"  Outcome: {step.get('outcome', '')}")


if __name__ == "__main__":
    app()
