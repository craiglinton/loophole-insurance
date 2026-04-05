from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

from loophole.agents.judge import Judge
from loophole.agents.drafter import EndorsementDrafter
from loophole.agents.gap_finder import GapFinder
from loophole.agents.overreach_finder import OverreachFinder
from loophole.llm import LLMClient
from loophole.models import CaseStatus, CaseType, Endorsement, SessionState
from loophole.session import SessionManager

app = typer.Typer(name="loophole", add_completion=False)
console = Console()


def _load_config() -> dict:
    config_path = Path("config.yaml")
    if config_path.exists():
        return yaml.safe_load(config_path.read_text())
    return {
        "model": {"default": "minimax-m2.7:cloud", "max_tokens": 4096},
        "temperatures": {
            "drafter": 0.4,
            "gap_finder": 0.9,
            "overreach_finder": 0.9,
            "judge": 0.3,
        },
        "loop": {"max_rounds": 10, "cases_per_agent": 3},
        "session_dir": "sessions",
    }


def _build_agents(config: dict) -> dict:
    model = config["model"]["default"]
    max_tokens = config["model"]["max_tokens"]
    temps = config["temperatures"]
    cases_per = config["loop"]["cases_per_agent"]

    llm = LLMClient(model=model, max_tokens=max_tokens)

    return {
        "drafter": EndorsementDrafter(llm, temperature=temps["drafter"]),
        "gap_finder": GapFinder(llm, temperature=temps["gap_finder"], cases_per_agent=cases_per),
        "overreach": OverreachFinder(llm, temperature=temps["overreach_finder"], cases_per_agent=cases_per),
        "judge": Judge(llm, temperature=temps["judge"]),
    }


def _display_endorsement(endorsement: Endorsement) -> None:
    console.print()
    console.print(
        Panel(
            endorsement.text,
            title=f"[bold]Endorsement v{endorsement.version}[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )
    if endorsement.changelog:
        console.print(f"[dim]Changelog: {endorsement.changelog}[/dim]")
    console.print()


def _display_case(case_obj) -> None:
    color = "red" if case_obj.case_type == CaseType.LOOPHOLE else "yellow"
    label = "GAP" if case_obj.case_type == CaseType.LOOPHOLE else "OVERREACH"
    console.print()
    console.print(
        Panel(
            f"[bold]Scenario:[/bold]\n{case_obj.scenario}\n\n"
            f"[bold]Problem:[/bold]\n{case_obj.explanation}",
            title=f"[{color}]Case #{case_obj.id} — {label}[/{color}]",
            border_style=color,
            padding=(1, 2),
        )
    )


def _get_multiline_input(prompt_text: str) -> str:
    console.print(f"\n[bold]{prompt_text}[/bold]")
    console.print("[dim](Enter a blank line when finished)[/dim]")
    lines = []
    while True:
        line = Prompt.ask("", default="")
        if line == "" and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _run_adversarial_loop(state, agents, session_mgr, config):
    max_rounds = config["loop"]["max_rounds"]
    drafter: EndorsementDrafter = agents["drafter"]
    gap_finder: GapFinder = agents["gap_finder"]
    overreach_finder: OverreachFinder = agents["overreach"]
    judge: Judge = agents["judge"]

    while state.current_round < max_rounds:
        state.current_round += 1
        console.print(Rule(f"[bold] Round {state.current_round} [/bold]", style="cyan"))

        # Phase 1: Adversarial search
        console.print("\n[bold]Searching for gaps...[/bold]", end="")
        gaps = gap_finder.find(state)
        console.print(f" found [red]{len(gaps)}[/red]")

        console.print("[bold]Searching for overreach...[/bold]", end="")
        overreaches = overreach_finder.find(state)
        console.print(f" found [yellow]{len(overreaches)}[/yellow]")

        all_cases = gaps + overreaches

        if not all_cases:
            console.print(
                "\n[green bold]No failures found! "
                "The endorsement appears robust against this round of testing.[/green bold]"
            )
            if not Confirm.ask("Run another round to be sure?", default=False):
                break
            continue

        # Phase 2: Judge each case
        round_auto = 0
        round_escalated = 0

        for case_obj in all_cases:
            state.cases.append(case_obj)
            _display_case(case_obj)

            # Judge attempts auto-resolution
            console.print("  [dim]Judge evaluating...[/dim]", end="")
            result = judge.evaluate(state, case_obj)

            if result.resolvable:
                # Validate against test suite
                if result.proposed_revision and state.resolved_cases:
                    console.print(" [dim]validating...[/dim]", end="")

                    # Have the drafter produce the actual revised endorsement
                    case_obj.resolution = result.resolution_summary or result.reasoning
                    case_obj.status = CaseStatus.AUTO_RESOLVED
                    case_obj.resolved_by = "judge"

                    revised = drafter.revise(state, case_obj)

                    validation = judge.validate(state, revised.text)
                    if validation.passes:
                        state.current_endorsement = revised
                        state.endorsement_history.append(revised)
                        console.print(
                            f" [green]Resolved → Endorsement v{revised.version}[/green]"
                        )
                        round_auto += 1
                    else:
                        # Validation failed — escalate
                        case_obj.status = CaseStatus.ESCALATED
                        case_obj.resolution = None
                        case_obj.resolved_by = None
                        console.print(" [red]Validation failed — escalating[/red]")
                        _escalate(state, case_obj, validation.details, drafter)
                        round_escalated += 1
                else:
                    # No prior cases to validate against, or no proposed revision
                    case_obj.resolution = result.resolution_summary or result.reasoning
                    case_obj.status = CaseStatus.AUTO_RESOLVED
                    case_obj.resolved_by = "judge"

                    revised = drafter.revise(state, case_obj)
                    state.current_endorsement = revised
                    state.endorsement_history.append(revised)
                    console.print(
                        f" [green]Resolved → Endorsement v{revised.version}[/green]"
                    )
                    round_auto += 1
            else:
                # Unresolvable — escalate to user
                console.print(" [red bold]Cannot resolve — escalating to you[/red bold]")
                _escalate(state, case_obj, result.conflict_explanation or result.reasoning, drafter)
                round_escalated += 1

            session_mgr.save(state)

        # Round summary
        _display_round_summary(state, len(all_cases), round_auto, round_escalated)

        # Continue?
        console.print()
        action = Prompt.ask(
            "[bold]Next?[/bold]",
            choices=["continue", "view endorsement", "stop"],
            default="continue",
        )
        if action == "view endorsement":
            _display_endorsement(state.current_endorsement)
            if not Confirm.ask("Continue to next round?", default=True):
                break
        elif action == "stop":
            break

    console.print(Rule("[bold green] Session Complete [/bold green]", style="green"))
    _display_endorsement(state.current_endorsement)
    console.print(
        f"[bold]Final stats:[/bold] {len(state.cases)} cases over "
        f"{state.current_round} rounds, endorsement at v{state.current_endorsement.version}"
    )
    console.print(
        f"[dim]Session saved to: sessions/{state.session_id}/[/dim]"
    )

    # Generate HTML report
    from loophole.visualize import generate_html
    report_path = generate_html(state)
    console.print(f"[bold blue]HTML report:[/bold blue] {report_path}")


def _escalate(state, case_obj, conflict_text, drafter):
    console.print(
        Panel(
            f"[bold]The judge could not resolve this case without breaking prior rulings.[/bold]\n\n"
            f"{conflict_text or 'No additional conflict details.'}",
            title="[red bold]Escalation[/red bold]",
            border_style="red",
            padding=(1, 2),
        )
    )

    decision = _get_multiline_input(
        "How should this case be handled? Your decision becomes a new constraint:"
    )

    case_obj.status = CaseStatus.USER_RESOLVED
    case_obj.resolution = decision
    case_obj.resolved_by = "user"
    state.user_clarifications.append(
        f"[Case #{case_obj.id}] {decision}"
    )

    # Drafter incorporates the user's decision
    console.print("  [dim]Updating endorsement...[/dim]")
    revised = drafter.revise(state, case_obj)
    state.current_endorsement = revised
    state.endorsement_history.append(revised)
    console.print(f"  [green]Endorsement updated → v{revised.version}[/green]")


def _display_round_summary(state, total, auto, escalated):
    console.print()
    table = Table(title=f"Round {state.current_round} Summary", show_header=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Cases found", str(total))
    table.add_row("Auto-resolved", f"[green]{auto}[/green]")
    table.add_row("Escalated to user", f"[red]{escalated}[/red]")
    table.add_row("Endorsement version", f"v{state.current_endorsement.version}")
    table.add_row("Total resolved cases", str(len(state.resolved_cases)))
    console.print(table)


@app.command()
def new(
    domain: str = typer.Option(None, help="Line of business (e.g., cyber, D&O, E&O)"),
    policy_file: str = typer.Option(None, "--policy", "-p", help="Path to a text file with the base insurance policy"),
    goal: str = typer.Option(None, "--goal", "-g", help="What the endorsement should accomplish"),
):
    """Start a new Loophole session."""
    console.print(
        Panel(
            "[bold]Loophole[/bold]\n"
            "Adversarial Insurance Endorsement Drafter",
            border_style="bright_blue",
            padding=(1, 2),
        )
    )

    config = _load_config()
    agents = _build_agents(config)

    if not domain:
        domain = Prompt.ask("\n[bold]Line of business[/bold] (e.g., cyber, D&O, E&O)")

    if policy_file:
        policy_text = Path(policy_file).read_text().strip()
        console.print(f"[dim]Loaded policy from {policy_file}[/dim]")
    else:
        policy_text = _get_multiline_input(
            "Paste or type the base insurance policy (or relevant excerpt):"
        )

    if not goal:
        goal = _get_multiline_input(
            "What should this endorsement accomplish? (e.g., add an exclusion for state-sponsored cyber attacks):"
        )

    session_id = f"{domain}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session_mgr = SessionManager(config["session_dir"])

    # Generate initial endorsement
    console.print("\n[bold]Drafting initial endorsement...[/bold]")
    drafter: EndorsementDrafter = agents["drafter"]

    # Bootstrap: create a placeholder state for the initial draft
    placeholder = SessionState(
        session_id=session_id,
        domain=domain,
        policy_text=policy_text,
        endorsement_goal=goal,
        current_endorsement=Endorsement(version=0, text=""),
    )
    initial_endorsement = drafter.draft_initial(placeholder)

    state = session_mgr.create_session(session_id, domain, policy_text, goal, initial_endorsement)
    _display_endorsement(state.current_endorsement)

    if Confirm.ask("Begin adversarial testing?", default=True):
        _run_adversarial_loop(state, agents, session_mgr, config)


@app.command()
def resume(
    session_id: str = typer.Argument(None, help="Session ID to resume"),
):
    """Resume an existing session."""
    config = _load_config()
    session_mgr = SessionManager(config["session_dir"])

    if not session_id:
        sessions = session_mgr.list_sessions()
        if not sessions:
            console.print("[red]No sessions found.[/red]")
            raise typer.Exit()

        table = Table(title="Available Sessions")
        table.add_column("#", style="dim")
        table.add_column("Session ID")
        table.add_column("Domain")
        table.add_column("Round")
        table.add_column("Cases")
        table.add_column("Endorsement Version")
        for i, s in enumerate(sessions, 1):
            table.add_row(
                str(i), s["id"], s["domain"],
                str(s["round"]), str(s["cases"]), f"v{s['endorsement_version']}"
            )
        console.print(table)

        choice = Prompt.ask("Select session number")
        session_id = sessions[int(choice) - 1]["id"]

    state = session_mgr.load(session_id)
    agents = _build_agents(config)

    console.print(f"\n[bold]Resuming session:[/bold] {session_id}")
    console.print(
        f"Domain: {state.domain} | Round: {state.current_round} "
        f"| Endorsement: v{state.current_endorsement.version}"
    )
    _display_endorsement(state.current_endorsement)

    _run_adversarial_loop(state, agents, session_mgr, config)


@app.command(name="list")
def list_sessions():
    """List all sessions."""
    config = _load_config()
    session_mgr = SessionManager(config["session_dir"])
    sessions = session_mgr.list_sessions()

    if not sessions:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Sessions")
    table.add_column("Session ID")
    table.add_column("Domain")
    table.add_column("Round")
    table.add_column("Cases")
    table.add_column("Endorsement Version")
    for s in sessions:
        table.add_row(
            s["id"], s["domain"],
            str(s["round"]), str(s["cases"]), f"v{s['endorsement_version']}"
        )
    console.print(table)


@app.command()
def visualize(
    session_id: str = typer.Argument(None, help="Session ID to visualize"),
    output: str = typer.Option(None, "--output", "-o", help="Output HTML file path"),
):
    """Generate an HTML visualization of a session."""
    config = _load_config()
    session_mgr = SessionManager(config["session_dir"])

    if not session_id:
        sessions = session_mgr.list_sessions()
        if not sessions:
            console.print("[red]No sessions found.[/red]")
            raise typer.Exit()

        table = Table(title="Available Sessions")
        table.add_column("#", style="dim")
        table.add_column("Session ID")
        table.add_column("Domain")
        table.add_column("Cases")
        for i, s in enumerate(sessions, 1):
            table.add_row(str(i), s["id"], s["domain"], str(s["cases"]))
        console.print(table)

        choice = Prompt.ask("Select session number")
        session_id = sessions[int(choice) - 1]["id"]

    state = session_mgr.load(session_id)

    from loophole.visualize import generate_html
    report_path = generate_html(state, output_path=output)
    console.print(f"[bold green]Report generated:[/bold green] {report_path}")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Loophole — Adversarial Insurance Endorsement Drafter."""
    if ctx.invoked_subcommand is None:
        # Interactive menu
        console.print(
            Panel(
                "[bold]Loophole[/bold]\n"
                "Adversarial Insurance Endorsement Drafter",
                border_style="bright_blue",
                padding=(1, 2),
            )
        )
        console.print("  1. [bold]New session[/bold]")
        console.print("  2. [bold]Resume session[/bold]")
        console.print("  3. [bold]List sessions[/bold]")
        console.print("  4. [bold]Exit[/bold]")
        console.print()

        choice = Prompt.ask("Select", choices=["1", "2", "3", "4"], default="1")

        if choice == "1":
            ctx.invoke(new, domain=None, policy_file=None, goal=None)
        elif choice == "2":
            ctx.invoke(resume, session_id=None)
        elif choice == "3":
            ctx.invoke(list_sessions)
        else:
            raise typer.Exit()


if __name__ == "__main__":
    app()
