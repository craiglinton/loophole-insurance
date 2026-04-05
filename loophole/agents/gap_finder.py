from __future__ import annotations

import re
from typing import Any

from loophole.agents.base import BaseAgent
from loophole.models import Case, CaseType, SessionState
from loophole.prompts import GAP_FINDER_SYSTEM, GAP_FINDER_USER


def _format_prior_cases(cases: list[Case]) -> str:
    if not cases:
        return "(none yet)"
    parts = []
    for c in cases:
        parts.append(f"Case #{c.id} ({c.case_type.value}): {c.scenario}")
    return "\n".join(parts)


class GapFinder(BaseAgent):
    def __init__(self, *args: Any, cases_per_agent: int = 3, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.cases_per_agent = cases_per_agent

    def _build_system_prompt(self, **kwargs: Any) -> str:
        return GAP_FINDER_SYSTEM.format(cases_per_agent=self.cases_per_agent)

    def _build_user_message(self, state: SessionState, **kwargs: Any) -> str:
        return GAP_FINDER_USER.format(
            policy_text=state.policy_text,
            endorsement_goal=state.endorsement_goal,
            user_clarifications="\n".join(state.user_clarifications) or "(none)",
            endorsement_version=state.current_endorsement.version,
            endorsement_text=state.current_endorsement.text,
            prior_cases_text=_format_prior_cases(state.cases),
            cases_per_agent=self.cases_per_agent,
        )

    def find(self, state: SessionState) -> list[Case]:
        raw = self.run(state)
        return _parse_scenarios(raw, state)


def _parse_scenarios(raw: str, state: SessionState) -> list[Case]:
    cases: list[Case] = []
    for m in re.finditer(
        r"<scenario>\s*<description>(.*?)</description>\s*<explanation>(.*?)</explanation>\s*</scenario>",
        raw,
        re.DOTALL,
    ):
        cases.append(
            Case(
                id=state.next_case_id + len(cases),
                round=state.current_round,
                case_type=CaseType.LOOPHOLE,
                scenario=m.group(1).strip(),
                explanation=m.group(2).strip(),
            )
        )
    return cases
