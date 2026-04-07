from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import questionary
import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from loophole.agents.judge import Judge
from loophole.agents.drafter import EndorsementDrafter
from loophole.agents.gap_finder import GapFinder
from loophole.agents.overreach_finder import OverreachFinder
from loophole.llm import LLMClient
from loophole.models import CaseStatus, CaseType, Endorsement, SessionState
from loophole.session import SessionManager
from loophole.template_browser import browse_and_select

app = typer.Typer(name="loophole", add_completion=False)
console = Console()

TEMPLATES_DIR = Path("templates")
CONFIG_PATH = Path("config.yaml")


# ---------------------------------------------------------------------------
# Menu context — ephemeral workspace for pre-session selections
# ---------------------------------------------------------------------------

@dataclass
class MenuContext:
    config: dict = field(default_factory=dict)
    selected_policy: Path | None = None
    selected_guidelines: Path | None = None
    selected_endorsement_template: Path | None = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text())
    return {
        "model": {"default": "minimax-m2.7:cloud", "max_tokens": 8192},
        "temperatures": {
            "drafter": 0.4,
            "gap_finder": 0.9,
            "overreach_finder": 0.9,
            "judge": 0.3,
        },
        "loop": {"max_rounds": 10, "cases_per_agent": 3},
        "session_dir": "sessions",
        "verbose": False,
    }


def _save_config(config: dict) -> None:
    CONFIG_PATH.write_text(yaml.safe_dump(config, default_flow_style=False))


def _first_template_file(directory: Path) -> Path | None:
    """Return the first .txt/.md file alphabetically in *directory*, or None."""
    if not directory.exists():
        return None
    files = sorted(
        f for f in directory.iterdir()
        if f.is_file() and f.suffix in (".txt", ".md")
    )
    return files[0] if files else None


def _resolve_selection(directory: Path, saved_name: str | None) -> Path | None:
    """Resolve a saved filename back to a full Path, falling back to the first
    file in the directory if the saved file no longer exists."""
    if saved_name:
        candidate = directory / saved_name
        if candidate.exists():
            return candidate
    return _first_template_file(directory)


def _init_selections(ctx: MenuContext) -> None:
    """Populate MenuContext from config.yaml selections (or first-file defaults)."""
    saved = ctx.config.get("selections", {})
    ctx.selected_policy = _resolve_selection(
        TEMPLATES_DIR / "policies", saved.get("policy"),
    )
    ctx.selected_guidelines = _resolve_selection(
        TEMPLATES_DIR / "guidelines", saved.get("guidelines"),
    )
    ctx.selected_endorsement_template = _resolve_selection(
        TEMPLATES_DIR / "endorsements", saved.get("endorsement_template"),
    )


def _persist_selections(ctx: MenuContext) -> None:
    """Write current selections into config.yaml so they survive restarts."""
    ctx.config.setdefault("selections", {})
    ctx.config["selections"]["policy"] = (
        ctx.selected_policy.name if ctx.selected_policy else None
    )
    ctx.config["selections"]["guidelines"] = (
        ctx.selected_guidelines.name if ctx.selected_guidelines else None
    )
    ctx.config["selections"]["endorsement_template"] = (
        ctx.selected_endorsement_template.name
        if ctx.selected_endorsement_template else None
    )
    _save_config(ctx.config)


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


def _default_drafting_guidelines() -> str:
    path = TEMPLATES_DIR / "guidelines" / "drafting_guidelines.txt"
    if path.exists():
        return path.read_text().strip()
    return (
        "1. Be surgical — modify only what is necessary.\n"
        "2. Avoid unnecessary complexity.\n"
        "3. The insured bears the burden of proving coverage; the carrier "
        "bears the burden of proving an exclusion applies.\n"
        "4. Define terms precisely.\n"
        "5. Avoid ambiguity — courts construe ambiguity against the drafter."
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

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


def _verbose(title: str, content: str, style: str = "dim") -> None:
    """Print a verbose-mode panel. Only call when verbose is enabled."""
    console.print(
        Panel(
            f"[{style}]{content}[/{style}]",
            title=f"[dim]{title}[/dim]",
            border_style="dim",
            padding=(0, 2),
        )
    )


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


# ---------------------------------------------------------------------------
# Main menu display
# ---------------------------------------------------------------------------

def _print_banner():
    console.print()
    console.print(
        Panel(
            "[bold]Loophole[/bold]\n"
            "Adversarial Insurance Endorsement Drafter",
            border_style="bright_blue",
            padding=(1, 2),
        )
    )


def _print_selections(ctx: MenuContext):
    console.print()
    console.print("  [bold]Current selections:[/bold]")

    if ctx.selected_policy:
        console.print(f"    Policy:      [green]{ctx.selected_policy.name}[/green]")
    else:
        console.print("    Policy:      [dim](none — add files to templates/policies/)[/dim]")

    if ctx.selected_guidelines:
        console.print(f"    Guidelines:  [green]{ctx.selected_guidelines.name}[/green]")
    else:
        console.print("    Guidelines:  [dim](none — add files to templates/guidelines/)[/dim]")

    if ctx.selected_endorsement_template:
        console.print(f"    Template:    [green]{ctx.selected_endorsement_template.name}[/green]")
    else:
        console.print("    Template:    [dim](none — add files to templates/endorsements/)[/dim]")

    console.print()



# ---------------------------------------------------------------------------
# Menu handlers
# ---------------------------------------------------------------------------

def _configure_menu(ctx: MenuContext):
    """Submenu for editing configuration values."""
    while True:
        config = ctx.config
        console.print(Rule("[bold] Configure [/bold]", style="cyan"))
        console.print()

        choice = questionary.select(
            "Configure:",
            choices=[
                questionary.Choice(f"Model              [{config['model']['default']}]", value="model"),
                questionary.Choice(f"Max output tokens  [{config['model']['max_tokens']}]", value="max_tokens"),
                questionary.Choice(f"Drafter temp       [{config['temperatures']['drafter']}]", value="drafter"),
                questionary.Choice(f"Gap finder temp    [{config['temperatures']['gap_finder']}]", value="gap_finder"),
                questionary.Choice(f"Overreach temp     [{config['temperatures']['overreach_finder']}]", value="overreach"),
                questionary.Choice(f"Judge temp         [{config['temperatures']['judge']}]", value="judge"),
                questionary.Choice(f"Max rounds         [{config['loop']['max_rounds']}]", value="max_rounds"),
                questionary.Choice(f"Cases per agent    [{config['loop']['cases_per_agent']}]", value="cases_per_agent"),
                questionary.Choice(f"Verbose mode       [{'ON' if config.get('verbose', False) else 'OFF'}]", value="verbose"),
                questionary.Choice("Save to config.yaml", value="save"),
                questionary.Choice("Back", value="back"),
            ],
        ).ask()

        if choice is None or choice == "back":
            break
        elif choice == "model":
            config["model"]["default"] = Prompt.ask("Model name", default=config["model"]["default"])
        elif choice == "max_tokens":
            config["model"]["max_tokens"] = int(Prompt.ask("Max output tokens", default=str(config["model"]["max_tokens"])))
        elif choice == "drafter":
            config["temperatures"]["drafter"] = float(Prompt.ask("Drafter temperature", default=str(config["temperatures"]["drafter"])))
        elif choice == "gap_finder":
            config["temperatures"]["gap_finder"] = float(Prompt.ask("Gap finder temperature", default=str(config["temperatures"]["gap_finder"])))
        elif choice == "overreach":
            config["temperatures"]["overreach_finder"] = float(Prompt.ask("Overreach temperature", default=str(config["temperatures"]["overreach_finder"])))
        elif choice == "judge":
            config["temperatures"]["judge"] = float(Prompt.ask("Judge temperature", default=str(config["temperatures"]["judge"])))
        elif choice == "max_rounds":
            config["loop"]["max_rounds"] = int(Prompt.ask("Max rounds", default=str(config["loop"]["max_rounds"])))
        elif choice == "cases_per_agent":
            config["loop"]["cases_per_agent"] = int(Prompt.ask("Cases per agent", default=str(config["loop"]["cases_per_agent"])))
        elif choice == "verbose":
            config["verbose"] = not config.get("verbose", False)
            status = "ON" if config["verbose"] else "OFF"
            console.print(f"[green]Verbose mode: {status}[/green]")
        elif choice == "save":
            _save_config(config)
            console.print("[green]Saved to config.yaml[/green]")


def _select_policy(ctx: MenuContext):
    selected = browse_and_select(TEMPLATES_DIR / "policies", "Policy", console)
    if selected:
        ctx.selected_policy = selected
        _persist_selections(ctx)


def _select_guidelines(ctx: MenuContext):
    selected = browse_and_select(TEMPLATES_DIR / "guidelines", "Guidelines", console)
    if selected:
        ctx.selected_guidelines = selected
        _persist_selections(ctx)


def _select_endorsement_template(ctx: MenuContext):
    selected = browse_and_select(TEMPLATES_DIR / "endorsements", "Endorsement Template", console)
    if selected:
        ctx.selected_endorsement_template = selected
        _persist_selections(ctx)


def _start_new_session(ctx: MenuContext):
    """Gather remaining inputs and launch a drafting session."""
    if not ctx.selected_policy:
        console.print("[red]No policy available. Add a .txt or .md file to templates/policies/.[/red]")
        return

    # Load file contents
    policy_text = ctx.selected_policy.read_text().strip()

    if ctx.selected_guidelines:
        drafting_guidelines = ctx.selected_guidelines.read_text().strip()
    else:
        drafting_guidelines = _default_drafting_guidelines()

    endorsement_template = None
    if ctx.selected_endorsement_template:
        endorsement_template = ctx.selected_endorsement_template.read_text().strip()

    # Prompt for remaining inputs
    console.print(Rule("[bold] New Session [/bold]", style="cyan"))

    domain = Prompt.ask("\n[bold]Line of business[/bold] (e.g., cyber, D&O, E&O)", default="cyber")
    goal = _get_multiline_input(
        "What should this endorsement accomplish?"
    )

    if not goal:
        console.print("[red]An endorsement goal is required.[/red]")
        return

    # Build session
    config = ctx.config
    agents = _build_agents(config)
    session_id = f"{domain}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session_mgr = SessionManager(config.get("session_dir", "sessions"))

    console.print("\n[bold]Drafting initial endorsement...[/bold]")
    drafter: EndorsementDrafter = agents["drafter"]

    placeholder = SessionState(
        session_id=session_id,
        domain=domain,
        policy_text=policy_text,
        endorsement_goal=goal,
        drafting_guidelines=drafting_guidelines,
        endorsement_template=endorsement_template,
        current_endorsement=Endorsement(version=0, text=""),
    )
    initial_endorsement = drafter.draft_initial(placeholder)

    state = session_mgr.create_session(
        session_id, domain, policy_text, goal,
        drafting_guidelines, endorsement_template, initial_endorsement,
    )
    _display_endorsement(state.current_endorsement)

    begin = questionary.confirm("Begin adversarial testing?", default=True).ask()
    if begin:
        _run_adversarial_loop(state, agents, session_mgr, config)


def _previous_sessions_menu(ctx: MenuContext):
    """Submenu for viewing and resuming past sessions."""
    config = ctx.config
    session_mgr = SessionManager(config.get("session_dir", "sessions"))

    while True:
        console.print(Rule("[bold] Previous Sessions [/bold]", style="cyan"))
        console.print()

        choice = questionary.select(
            "Previous sessions:",
            choices=[
                questionary.Choice("Resume a session", value="resume"),
                questionary.Choice("List all sessions", value="list"),
                questionary.Choice("Visualize a session", value="visualize"),
                questionary.Choice("Back", value="back"),
            ],
        ).ask()

        if choice is None or choice == "back":
            break
        elif choice == "resume":
            _resume_session(ctx)
        elif choice == "list":
            _list_sessions(ctx)
        elif choice == "visualize":
            _visualize_session(ctx)


def _list_sessions(ctx: MenuContext):
    session_mgr = SessionManager(ctx.config.get("session_dir", "sessions"))
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


def _resume_session(ctx: MenuContext):
    config = ctx.config
    session_mgr = SessionManager(config.get("session_dir", "sessions"))

    sessions = session_mgr.list_sessions()
    if not sessions:
        console.print("[red]No sessions found.[/red]")
        return

    choices = []
    for s in sessions:
        label = f"{s['id']}  (round {s['round']}, {s['cases']} cases, v{s['endorsement_version']})"
        choices.append(questionary.Choice(title=label, value=s["id"]))
    choices.append(questionary.Choice(title="Cancel", value=None))

    session_id = questionary.select("Select session to resume:", choices=choices).ask()
    if session_id is None:
        return

    state = session_mgr.load(session_id)
    agents = _build_agents(config)

    console.print(f"\n[bold]Resuming session:[/bold] {session_id}")
    console.print(
        f"Domain: {state.domain} | Round: {state.current_round} "
        f"| Endorsement: v{state.current_endorsement.version}"
    )
    _display_endorsement(state.current_endorsement)

    _run_adversarial_loop(state, agents, session_mgr, config)


def _visualize_session(ctx: MenuContext):
    config = ctx.config
    session_mgr = SessionManager(config.get("session_dir", "sessions"))

    sessions = session_mgr.list_sessions()
    if not sessions:
        console.print("[red]No sessions found.[/red]")
        return

    choices = []
    for s in sessions:
        label = f"{s['id']}  ({s['domain']}, {s['cases']} cases)"
        choices.append(questionary.Choice(title=label, value=s["id"]))
    choices.append(questionary.Choice(title="Cancel", value=None))

    session_id = questionary.select("Select session to visualize:", choices=choices).ask()
    if session_id is None:
        return

    state = session_mgr.load(session_id)

    from loophole.visualize import generate_html
    report_path = generate_html(state)
    console.print(f"[bold green]Report generated:[/bold green] {report_path}")


# ---------------------------------------------------------------------------
# Adversarial loop
# ---------------------------------------------------------------------------

def _run_adversarial_loop(state, agents, session_mgr, config):
    max_rounds = config["loop"]["max_rounds"]
    verbose = config.get("verbose", False)
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
            again = questionary.confirm("Run another round to be sure?", default=False).ask()
            if not again:
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

            if verbose and result.reasoning:
                console.print()  # newline after "Judge evaluating..."
                _verbose("Judge Reasoning", result.reasoning)
            if verbose and result.proposed_revision:
                _verbose("Proposed Revision", result.proposed_revision)

            if result.resolvable:
                if result.proposed_revision and state.resolved_cases:
                    console.print(" [dim]validating...[/dim]", end="")

                    case_obj.resolution = result.resolution_summary or result.reasoning
                    case_obj.status = CaseStatus.AUTO_RESOLVED
                    case_obj.resolved_by = "judge"

                    revised = drafter.revise(state, case_obj)
                    if verbose and revised.changelog:
                        _verbose(f"Changelog (v{revised.version})", revised.changelog)

                    validation = judge.validate(state, revised.text)
                    if verbose and validation.details:
                        _verbose(
                            f"Validation {'PASSED' if validation.passes else 'FAILED'}",
                            validation.details,
                            style="green dim" if validation.passes else "red dim",
                        )
                    if validation.passes:
                        state.current_endorsement = revised
                        state.endorsement_history.append(revised)
                        console.print(
                            f" [green]Resolved -> Endorsement v{revised.version}[/green]"
                        )
                        round_auto += 1
                    else:
                        case_obj.status = CaseStatus.ESCALATED
                        case_obj.resolution = None
                        case_obj.resolved_by = None
                        console.print(" [red]Validation failed -- escalating[/red]")
                        _escalate(state, case_obj, validation.details, drafter, verbose)
                        round_escalated += 1
                else:
                    case_obj.resolution = result.resolution_summary or result.reasoning
                    case_obj.status = CaseStatus.AUTO_RESOLVED
                    case_obj.resolved_by = "judge"

                    revised = drafter.revise(state, case_obj)
                    if verbose and revised.changelog:
                        _verbose(f"Changelog (v{revised.version})", revised.changelog)
                    state.current_endorsement = revised
                    state.endorsement_history.append(revised)
                    console.print(
                        f" [green]Resolved -> Endorsement v{revised.version}[/green]"
                    )
                    round_auto += 1
            else:
                console.print(" [red bold]Cannot resolve -- escalating to you[/red bold]")
                _escalate(state, case_obj, result.conflict_explanation or result.reasoning, drafter, verbose)
                round_escalated += 1

            session_mgr.save(state)

        _display_round_summary(state, len(all_cases), round_auto, round_escalated)

        console.print()
        action = questionary.select(
            "Next?",
            choices=[
                questionary.Choice("Continue to next round", value="continue"),
                questionary.Choice("View current endorsement", value="view"),
                questionary.Choice("Stop", value="stop"),
            ],
        ).ask()

        if action == "view":
            _display_endorsement(state.current_endorsement)
            cont = questionary.confirm("Continue to next round?", default=True).ask()
            if not cont:
                break
        elif action == "stop" or action is None:
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

    from loophole.visualize import generate_html
    report_path = generate_html(state)
    console.print(f"[bold blue]HTML report:[/bold blue] {report_path}")


def _escalate(state, case_obj, conflict_text, drafter, verbose: bool = False):
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

    console.print("  [dim]Updating endorsement...[/dim]")
    revised = drafter.revise(state, case_obj)
    if verbose and revised.changelog:
        _verbose(f"Changelog (v{revised.version})", revised.changelog)
    state.current_endorsement = revised
    state.endorsement_history.append(revised)
    console.print(f"  [green]Endorsement updated -> v{revised.version}[/green]")


# ---------------------------------------------------------------------------
# Typer entry point
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Loophole -- Adversarial Insurance Endorsement Drafter."""
    if ctx.invoked_subcommand is not None:
        return

    config = _load_config()
    menu_ctx = MenuContext(config=config)
    _init_selections(menu_ctx)

    while True:
        _print_banner()
        _print_selections(menu_ctx)

        choice = questionary.select(
            "Main menu:",
            choices=[
                questionary.Choice("Configure              LLM settings, loop parameters", value="configure"),
                questionary.Choice("Select policy           Base policy to modify", value="policy"),
                questionary.Choice("Select guidelines       Endorsement drafting guidelines", value="guidelines"),
                questionary.Choice("Select template         Endorsement format template", value="template"),
                questionary.Choice("Start new session       Draft and stress-test an endorsement", value="new_session"),
                questionary.Choice("Previous sessions       Resume or review past sessions", value="previous"),
                questionary.Choice("Exit", value="exit"),
            ],
        ).ask()

        if choice == "configure":
            _configure_menu(menu_ctx)
        elif choice == "policy":
            _select_policy(menu_ctx)
        elif choice == "guidelines":
            _select_guidelines(menu_ctx)
        elif choice == "template":
            _select_endorsement_template(menu_ctx)
        elif choice == "new_session":
            _start_new_session(menu_ctx)
        elif choice == "previous":
            _previous_sessions_menu(menu_ctx)
        elif choice == "exit" or choice is None:
            raise typer.Exit()


if __name__ == "__main__":
    app()
