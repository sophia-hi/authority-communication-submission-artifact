"""Frozen organization protocols, independent of any model SDK."""
from __future__ import annotations

from dataclasses import dataclass


BRANCH_SPECIALIST_ROLE_BRANCH = {
    "Branch 1 Specialist": 0,
    "Branch 2 Specialist": 1,
}


@dataclass(frozen=True)
class OrganizationSpec:
    organization: str
    display_name: str
    agents: int
    decision_authority: str
    reporting_process: str
    final_rights: dict[str, tuple[str, ...]]
    initial_roles: tuple[str, ...]
    concurrent_private_analysis: bool
    message_graph: dict[str, tuple[str, ...]]
    message_limit: int | None
    report_sender: str | None = None
    report_receiver: str | None = None
    sender_commits_before_report: bool = False
    receiver_may_request: bool = False


SPECS = {
    "single": OrganizationSpec(
        organization="single", display_name="Single", agents=1,
        decision_authority="centralized", reporting_process="none",
        final_rights={"Owner": ("both",)}, initial_roles=("Owner",),
        concurrent_private_analysis=False, message_graph={}, message_limit=0),
    "independent": OrganizationSpec(
        organization="independent", display_name="Independent", agents=2,
        decision_authority="decentralized", reporting_process="none",
        final_rights={"Branch 1 Specialist": ("branch_1",),
                      "Branch 2 Specialist": ("branch_2",)},
        initial_roles=("Branch 1 Specialist", "Branch 2 Specialist"),
        concurrent_private_analysis=True,
        message_graph={}, message_limit=0),
    "committed_handoff": OrganizationSpec(
        organization="committed_handoff", display_name="Committed Handoff",
        agents=2, decision_authority="decentralized",
        reporting_process="one_way_channel",
        final_rights={"Lead": ("lead_branch",),
                      "Reporting": ("reporting_branch",)},
        initial_roles=("Lead", "Reporting"), concurrent_private_analysis=True,
        message_graph={"Reporting": ("Lead",)}, message_limit=None,
        report_sender="Reporting", report_receiver="Lead",
        sender_commits_before_report=True),
    "informational_handoff": OrganizationSpec(
        organization="informational_handoff",
        display_name="Informational Handoff", agents=2,
        decision_authority="decentralized",
        reporting_process="one_way_channel",
        final_rights={"Lead": ("lead_branch",),
                      "Reporting": ("reporting_branch",)},
        initial_roles=("Lead", "Reporting"), concurrent_private_analysis=True,
        message_graph={"Reporting": ("Lead",)}, message_limit=None,
        report_sender="Reporting", report_receiver="Lead"),
    "mutual": OrganizationSpec(
        organization="mutual", display_name="Mutual", agents=2,
        decision_authority="decentralized", reporting_process="two_way_channel",
        final_rights={"Branch 1 Specialist": ("branch_1",),
                      "Branch 2 Specialist": ("branch_2",)},
        initial_roles=("Branch 1 Specialist", "Branch 2 Specialist"),
        concurrent_private_analysis=True,
        message_graph={
            "Branch 1 Specialist": ("Branch 2 Specialist",),
            "Branch 2 Specialist": ("Branch 1 Specialist",),
        },
        message_limit=None),
    "specialist_proactive": OrganizationSpec(
        organization="specialist_proactive",
        display_name="Specialist-Proactive", agents=2,
        decision_authority="centralized",
        reporting_process="one_way_channel",
        final_rights={"Lead": ("both",)},
        initial_roles=("Lead", "Reporting"), concurrent_private_analysis=True,
        message_graph={"Reporting": ("Lead",)}, message_limit=None,
        report_sender="Reporting", report_receiver="Lead"),
    "centralized_two_way": OrganizationSpec(
        organization="centralized_two_way",
        display_name="Centralized Two-way", agents=2,
        decision_authority="centralized", reporting_process="two_way_channel",
        final_rights={"Lead": ("both",)},
        initial_roles=("Lead", "Reporting"), concurrent_private_analysis=True,
        message_graph={"Lead": ("Reporting",), "Reporting": ("Lead",)},
        message_limit=None),
}

ACTIVE_ORGANIZATIONS = tuple(SPECS)


def validate_specs() -> None:
    assert len(SPECS) == 7
    assert len(ACTIVE_ORGANIZATIONS) == 7
    for spec in SPECS.values():
        held = [decision for rights in spec.final_rights.values()
                for decision in rights]
        assert (held == ["both"] or
                sorted(held) in (["lead_branch", "reporting_branch"],
                                 ["branch_1", "branch_2"])), spec.organization
        if spec.reporting_process in {"one_way_channel", "two_way_channel"}:
            assert spec.message_limit is None
        if spec.report_sender:
            assert spec.report_sender == "Reporting"
            assert spec.report_receiver == "Lead"
    assert SPECS["committed_handoff"].sender_commits_before_report
    assert not SPECS["informational_handoff"].sender_commits_before_report
    for name in ("independent", "mutual"):
        assert SPECS[name].initial_roles == tuple(BRANCH_SPECIALIST_ROLE_BRANCH)
    for name in ("specialist_proactive", "centralized_two_way"):
        assert SPECS[name].final_rights == {"Lead": ("both",)}


validate_specs()
