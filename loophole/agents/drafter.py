from __future__ import annotations

import re
from typing import Any

from loophole.agents.base import BaseAgent
from loophole.models import Case, Endorsement, SessionState
from loophole.prompts import DRAFTER_INITIAL, DRAFTER_REVISE, DRAFTER_SYSTEM


def _format_resolved_cases(cases: list[Case]) -> str:
    if not cases:
        return "(none yet)"
    parts = []
    for c in cases:
        parts.append(
            f"Case #{c.id} ({c.case_type.value}) — {c.scenario}\n"
            f"  Resolution: {c.resolution}\n"
            f"  Resolved by: {c.resolved_by}"
        )
    return "\n\n".join(parts)


class EndorsementDrafter(BaseAgent):
    def _build_system_prompt(self, **kwargs: Any) -> str:
        return DRAFTER_SYSTEM

    def _build_user_message(self, state: SessionState, **kwargs: Any) -> str:
        case: Case | None = kwargs.get("case")
        if case is None:
            return DRAFTER_INITIAL.format(
                domain=state.domain,
                policy_text=state.policy_text,
                endorsement_goal=state.endorsement_goal,
            )
        return DRAFTER_REVISE.format(
            domain=state.domain,
            policy_text=state.policy_text,
            endorsement_goal=state.endorsement_goal,
            user_clarifications="\n".join(state.user_clarifications) or "(none)",
            endorsement_version=state.current_endorsement.version,
            endorsement_text=state.current_endorsement.text,
            case_type=case.case_type.value,
            case_scenario=case.scenario,
            case_explanation=case.explanation,
            case_resolution=case.resolution,
            resolved_cases_text=_format_resolved_cases(state.resolved_cases),
        )

    def draft_initial(self, state: SessionState) -> Endorsement:
        raw = self.run(state)
        text = _extract_tag(raw, "endorsement") or raw
        return Endorsement(version=1, text=text.strip())

    def revise(self, state: SessionState, case: Case) -> Endorsement:
        raw = self.run(state, case=case)
        text = _extract_tag(raw, "endorsement") or raw
        changelog = _extract_tag(raw, "changelog")
        return Endorsement(
            version=state.current_endorsement.version + 1,
            text=text.strip(),
            changelog=changelog,
        )


def _extract_tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else None
