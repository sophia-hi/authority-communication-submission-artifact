"""Deterministic state machines for seven experimental protocols.

This module contains no model calls.  It is the authority boundary used by
both mock and live runners, so a prompt cannot grant a role rights that the
runtime does not enforce. Seven protocols are active in the recorded panel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from organizations import BRANCH_SPECIALIST_ROLE_BRANCH, SPECS, OrganizationSpec


ACTIONS = ("A", "B")
ONE_WAY_ORGANIZATIONS = {
    "committed_handoff", "informational_handoff", "specialist_proactive",
}
TWO_WAY_ORGANIZATIONS = {"mutual", "centralized_two_way"}
COMMUNICATING_ORGANIZATIONS = ONE_WAY_ORGANIZATIONS | TWO_WAY_ORGANIZATIONS
PROTOCOL_VERSION = "communication_protocol_v21"


class ProtocolError(ValueError):
    pass


@dataclass
class Event:
    sequence: int
    actor: str
    kind: str
    payload: dict[str, Any]


@dataclass
class ProtocolState:
    organization: str
    lead_branch_index: int
    events: list[Event] = field(default_factory=list)
    branch_actions: dict[int, str] = field(default_factory=dict)
    company_actions: tuple[str, str] | None = None
    report_sent: bool = False
    initial_messages_sent: set[str] = field(default_factory=set)
    communication_finished: set[str] = field(default_factory=set)
    final_decision_phase: bool = False
    final_decision_phase_reason: str | None = None
    final_decision_phase_reason_code: str | None = None
    communication_close_reason: str | None = None
    current_round: int = 0
    closed: bool = False

    def __post_init__(self) -> None:
        if self.organization not in SPECS:
            raise ProtocolError(f"unknown organization {self.organization}")
        if self.lead_branch_index not in (0, 1):
            raise ProtocolError("lead_branch_index must be 0 or 1")

    @property
    def spec(self) -> OrganizationSpec:
        return SPECS[self.organization]

    @property
    def reporting_branch_index(self) -> int:
        return 1 - self.lead_branch_index

    @property
    def terminal(self) -> bool:
        return self.company_actions is not None or len(self.branch_actions) == 2

    @property
    def required_initial_senders(self) -> set[str]:
        if self.organization in ONE_WAY_ORGANIZATIONS:
            return {"Reporting"}
        if self.organization in TWO_WAY_ORGANIZATIONS:
            return set(self.spec.initial_roles)
        return set()

    @property
    def initial_communication_complete(self) -> bool:
        required = self.required_initial_senders
        return not required or required <= self.initial_messages_sent

    def _decision_actions(self, role: str) -> set[str]:
        org = self.organization
        if org in {"committed_handoff", "informational_handoff", "mutual"}:
            branch = self._branch_for_role(role)
            return {"submit_branch"} if branch not in self.branch_actions else set()
        if org in {"specialist_proactive", "centralized_two_way"}:
            return {"submit_company"} if role == "Lead" else set()
        return set()

    def _communication_can_affect_pending_decision(self) -> bool:
        if self.organization == "informational_handoff":
            return self.lead_branch_index not in self.branch_actions
        return not self.terminal

    @property
    def communication_open(self) -> bool:
        return (
            self.initial_communication_complete
            and not self.final_decision_phase
            and not self.communication_finished
            and self._communication_can_affect_pending_decision()
        )

    def enter_final_decision_phase(
            self, reason: str, reason_code: str = "no_progress") -> None:
        self._assert_open()
        if not self.initial_communication_complete:
            raise ProtocolError("final decision phase cannot precede initial communication")
        if not self.final_decision_phase:
            self.final_decision_phase = True
            self.final_decision_phase_reason = reason
            self.final_decision_phase_reason_code = reason_code
            self.communication_close_reason = (
                self.communication_close_reason or reason_code)
            self._record(
                "Protocol", "final_decision_phase",
                reason=reason, reason_code=reason_code)

    def _record(self, actor: str, kind: str, **payload: Any) -> None:
        if self.current_round:
            payload.setdefault("round_number", self.current_round)
        self.events.append(Event(len(self.events) + 1, actor, kind, payload))

    def role_has_filed(self, role: str) -> bool:
        """Return whether this role's final decision has entered protocol state."""
        if self.organization in {"specialist_proactive", "centralized_two_way"}:
            return self.company_actions is not None if role == "Lead" else False
        if self.organization in {"committed_handoff", "informational_handoff", "mutual"}:
            return self._branch_for_role(role) in self.branch_actions
        return self.terminal

    def auto_finish_communication(self, actor: str, reason: str) -> None:
        """Apply a purely mechanical finish without a model request."""
        if self.allowed_actions(actor) != {"finish_communication"}:
            raise ProtocolError("automatic finish requires finish as the only action")
        self.communication_finished.add(actor)
        self.communication_close_reason = self.communication_close_reason or reason
        self._record(
            "Protocol", "auto_protocol_close", role=actor, reason=reason,
            reason_code="finish_only_no_choice")

    def _assert_open(self) -> None:
        if self.closed or self.terminal:
            raise ProtocolError("cell is already terminal")

    def _branch_for_role(self, role: str) -> int:
        if (self.organization in {"independent", "mutual"}
                and role in BRANCH_SPECIALIST_ROLE_BRANCH):
            return BRANCH_SPECIALIST_ROLE_BRANCH[role]
        if role == "Lead":
            return self.lead_branch_index
        if role == "Reporting":
            return self.reporting_branch_index
        raise ProtocolError(f"{role} has no branch-specific decision right")

    def allowed_actions(self, role: str) -> set[str]:
        valid_roles = set(self.spec.initial_roles)
        if self.closed or self.terminal or role not in valid_roles:
            return set()
        org = self.organization
        if org == "single":
            return {"submit_company"} if role == "Owner" else set()
        if org == "independent":
            return {"submit_branch"}
        if org in COMMUNICATING_ORGANIZATIONS:
            if not self.initial_communication_complete:
                if role in self.initial_messages_sent:
                    return set()
                if org == "committed_handoff":
                    return {"commit_and_handoff"} if role == "Reporting" else set()
                if org in ONE_WAY_ORGANIZATIONS:
                    return {"send_report"} if role == "Reporting" else set()
                return {"send_message"}

            decision = self._decision_actions(role)
            if not self.communication_open:
                if (not decision and self.communication_finished
                        and role not in self.communication_finished):
                    decision.add("finish_communication")
                return decision

            communication = {"decline_message", "finish_communication"}
            if org in TWO_WAY_ORGANIZATIONS or role == "Reporting":
                communication.add("send_message")
            return decision | communication
        raise ProtocolError(f"missing protocol for {org}")

    def send_report(self, actor: str, text: str) -> None:
        self._assert_open()
        if "send_report" not in self.allowed_actions(actor):
            raise ProtocolError("report is not allowed at this stage")
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("report text is empty")
        self.report_sent = True
        if self.organization in ONE_WAY_ORGANIZATIONS:
            self.initial_messages_sent.add(actor)
        self._record(actor, "report", recipient="Lead", text=text)

    def send_message(self, actor: str, text: str) -> None:
        self._assert_open()
        if "send_message" not in self.allowed_actions(actor):
            raise ProtocolError("message is not allowed in this organization")
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("message text is empty")
        if self.organization == "mutual":
            roles = self.spec.initial_roles
            recipient = roles[1] if actor == roles[0] else roles[0]
        else:
            recipient = "Reporting" if actor == "Lead" else "Lead"
        if actor in self.required_initial_senders:
            self.initial_messages_sent.add(actor)
        self._record(actor, "message", recipient=recipient, text=text)

    def decline_message(self, actor: str) -> None:
        self._assert_open()
        if "decline_message" not in self.allowed_actions(actor):
            raise ProtocolError("declining a message is not allowed at this stage")
        if self.organization in TWO_WAY_ORGANIZATIONS:
            roles = self.spec.initial_roles
            recipient = roles[1] if actor == roles[0] else roles[0]
        else:
            recipient = "Lead" if actor == "Reporting" else "Reporting"
        self._record(actor, "decline_message", recipient=recipient)

    def finish_communication(self, actor: str) -> None:
        self._assert_open()
        if "finish_communication" not in self.allowed_actions(actor):
            raise ProtocolError("ending communication is not allowed at this stage")
        self.communication_finished.add(actor)
        self.communication_close_reason = (
            self.communication_close_reason or "role_finished_communication")
        if self.organization in TWO_WAY_ORGANIZATIONS:
            roles = self.spec.initial_roles
            recipient = roles[1] if actor == roles[0] else roles[0]
        else:
            recipient = "Lead" if actor == "Reporting" else "Reporting"
        self._record(actor, "finish_communication", recipient=recipient)

    def finish_communication_preauthorized(self, actor: str) -> None:
        """Apply a finish that was legal at the start of a synchronized round."""
        self._assert_open()
        if actor in self.communication_finished:
            raise ProtocolError("communication is already finished for this role")
        self.communication_finished.add(actor)
        self.communication_close_reason = (
            self.communication_close_reason or "role_finished_communication")
        if self.organization in TWO_WAY_ORGANIZATIONS:
            roles = self.spec.initial_roles
            recipient = roles[1] if actor == roles[0] else roles[0]
        else:
            recipient = "Lead" if actor == "Reporting" else "Reporting"
        self._record(actor, "finish_communication", recipient=recipient)

    def commit_and_handoff(self, actor: str, action: str, text: str) -> None:
        self._assert_open()
        if "commit_and_handoff" not in self.allowed_actions(actor):
            raise ProtocolError("committed handoff is not allowed at this stage")
        self._validate_action(action)
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("handoff text is empty")
        branch = self._branch_for_role(actor)
        self.branch_actions[branch] = action
        self.report_sent = True
        self.initial_messages_sent.add(actor)
        self._record(actor, "committed_handoff", recipient="Lead",
                     branch_index=branch, action=action, text=text)

    def submit_branch(self, actor: str, action: str) -> None:
        self._assert_open()
        if "submit_branch" not in self.allowed_actions(actor):
            raise ProtocolError("branch submission is not allowed at this stage")
        self._validate_action(action)
        branch = self._branch_for_role(actor)
        if branch in self.branch_actions:
            raise ProtocolError("branch action is irreversible")
        self.branch_actions[branch] = action
        self._record(actor, "submit_branch", branch_index=branch, action=action)
        if self.terminal and self.communication_close_reason is None:
            self.communication_close_reason = "all_required_decisions_filed"

    def submit_company(self, actor: str, branch1: str, branch2: str) -> None:
        self._assert_open()
        if "submit_company" not in self.allowed_actions(actor):
            raise ProtocolError("company submission is not allowed at this stage")
        self._validate_action(branch1)
        self._validate_action(branch2)
        self.company_actions = (branch1, branch2)
        self._record(actor, "submit_company", branch1=branch1, branch2=branch2)
        if self.communication_close_reason is None:
            self.communication_close_reason = "company_decision_filed"

    @staticmethod
    def _validate_action(action: str) -> None:
        if action not in ACTIONS:
            raise ProtocolError(f"invalid action {action!r}")

    def assembled_actions(self) -> tuple[str, str] | None:
        if self.company_actions is not None:
            return self.company_actions
        if len(self.branch_actions) == 2:
            return self.branch_actions[0], self.branch_actions[1]
        return None
