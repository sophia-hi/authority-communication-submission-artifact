"""Paper-scale, symmetric document binders for the branch-pricing task.

The economic truth is unchanged by this module. It controls only how that
truth is exposed: dated controller records are dispersed through realistic
working files, withdrawn versions, unrelated numeric tables, and office
traffic. The two local binders use the same information architecture so that
branch identity cannot create an attention advantage.
"""
from __future__ import annotations

import hashlib
import random
from typing import Callable

from generator import BranchPrimitives


LOCAL_DOCUMENT_COUNT = 24
INTERACTION_DOCUMENT_COUNT = 20

_FIRST = (
    "Ava", "Ben", "Camila", "Derek", "Elena", "Farid", "Grace", "Hiro",
    "Imani", "Jonas", "Keiko", "Luis", "Mara", "Nia", "Omar", "Priya",
)
_LAST = (
    "Almeida", "Berg", "Chen", "Diaz", "Ellis", "Gupta", "Hart", "Ito",
    "Jensen", "Khan", "Lopez", "Meyer", "Nguyen", "Patel", "Reed", "Shah",
)
_TEAMS = (
    "Retail Operations", "Wholesale", "Brand Studio", "Sourcing",
    "Quality", "IT Service Desk", "People Operations", "Treasury",
    "Sustainability", "Returns", "Legal Operations", "Demand Planning",
)
_TOPICS = (
    "color drift", "carton burst strength", "late ASN messages",
    "store fixture repairs", "sample inventory", "badge access",
    "open purchase orders", "training attendance", "vendor onboarding",
    "travel receipts", "carrier scorecards", "office lease questions",
)
_VENDORS = (
    "Helix Pack", "Redcedar Logistics", "Yama Freight", "Solstice QA",
    "Northwind 3PL", "Orchard Labels", "Pinnacle Poly", "Cedar Bond",
)


def _rng(seed: int | None, namespace: str) -> random.Random:
    raw = f"{0 if seed is None else int(seed)}|{namespace}".encode()
    return random.Random(int.from_bytes(hashlib.sha256(raw).digest()[:8], "big"))


def _name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"


def _date(rng: random.Random, year: int = 2026) -> str:
    return f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"


def _money(rng: random.Random, lo: int = 20, hi: int = 18000) -> str:
    return f"${rng.randint(lo, hi):,}.{rng.randint(0, 99):02d}"


def _noise_block(rng: random.Random, scope: str) -> str:
    """One dense paragraph of non-authoritative operational traffic."""
    sentences = [
        f"{_name(rng)} flagged {rng.choice(_TOPICS)} during the {_date(rng)} review and asked {_name(rng)} to close the ticket before month end; the item covers several product lines and contains no controlled input for the {scope} decision.",
        f"A {rng.choice(_TEAMS)} email quotes {_money(rng)} from a draft purchase order, but the amount mixes taxes, freight, and unrelated SKUs and was never approved by a controller.",
        f"The shared folder still contains a {rng.randint(2022, 2025)} planning assumption of {rng.randint(70, 260):,} thousand units and a {rng.randint(1, 14)} percent adjustment; neither figure identifies a branch, policy, or measurement basis.",
        f"A vendor note from {rng.choice(_VENDORS)} reports {rng.randint(3, 47)} open cases, {rng.randint(0, 19)} returns, and a service level of {rng.uniform(82, 99):.1f} percent for a portfolio that excludes the current controlled record.",
        "Meeting participants parked the question after learning that the source workbook had been superseded; Internal Audit retained the attachment only to preserve the revision trail.",
        f"A later reply mentions {_money(rng, 40, 900)} per shipment and a {rng.uniform(0.5, 18):.1f} percent rate, without saying whether the numbers are revenue, cost, volume, or a one-time accrual.",
    ]
    rng.shuffle(sentences)
    return " ".join(sentences)


def _filler_email(rng: random.Random, scope: str, ordinal: int,
                  blocks: int) -> str:
    parts = [
        f"# Shared mailbox export {ordinal:02d}",
        f"From: {_name(rng)}  To: {_name(rng)}; {_name(rng)}",
        f"Date: {_date(rng)}  Team: {rng.choice(_TEAMS)}",
        "Status: WORKING CORRESPONDENCE — not a controller lock",
    ]
    for _ in range(blocks):
        parts.extend(["", _noise_block(rng, scope)])
    return "\n".join(parts) + "\n"


def _filler_meeting(rng: random.Random, scope: str, ordinal: int,
                    blocks: int) -> str:
    parts = [
        f"# Weekly operations notes {ordinal:02d}",
        f"Date: {_date(rng)}  Chair: {_name(rng)}",
        "Status: UNAPPROVED NOTES — decisions remain in dated controlled records",
        "Attendees: " + ", ".join(_name(rng) for _ in range(8)),
    ]
    for i in range(blocks):
        parts.append(f"\n{i + 1}. {_noise_block(rng, scope)}")
    parts.append("\nNo policy economics were approved in this meeting.")
    return "\n".join(parts) + "\n"


def _filler_chat(rng: random.Random, scope: str, ordinal: int,
                 blocks: int) -> str:
    parts = [
        f"# Chat export {ordinal:02d}",
        "Status: INFORMAL THREAD — figures may be stale or lack units",
    ]
    for _ in range(blocks):
        text = _noise_block(rng, scope)
        midpoint = len(text) // 2
        cut = text.find(". ", midpoint)
        if cut < 0:
            cut = midpoint
        for fragment in (text[:cut + 1], text[cut + 2:]):
            parts.append(
                f"[{_date(rng)} {rng.randint(8, 18):02d}:{rng.randint(0, 59):02d}] "
                f"{_name(rng)}: {fragment.strip()}"
            )
    return "\n".join(parts) + "\n"


def _filler_table(rng: random.Random, scope: str, ordinal: int,
                  blocks: int) -> str:
    parts = [
        f"# Retired dashboard extract {ordinal:02d}",
        "Status: ARCHIVED — mixed products, undefined units, no branch-policy mapping",
        "row,period,channel,region,quantity,rate,amount,comment",
    ]
    for i in range(blocks * 9):
        parts.append(
            f"{i + 1},{rng.randint(1, 52)},"
            f"{rng.choice(('retail','wholesale','outlet','sample'))},"
            f"{rng.choice(('west','east','international','unassigned'))},"
            f"{rng.randint(12, 980)},{rng.uniform(0.01, 1.75):.4f},"
            f"{rng.uniform(-9000, 26000):.2f},"
            f"{rng.choice(('draft','reversal','other SKU','unreconciled','duplicate'))}"
        )
    parts.extend(["", _noise_block(rng, scope), "", _noise_block(rng, scope)])
    return "\n".join(parts) + "\n"


def _filler_report(rng: random.Random, scope: str, ordinal: int,
                   blocks: int) -> str:
    parts = [
        f"# Portfolio working paper {ordinal:02d}",
        f"Prepared by: {rng.choice(_TEAMS)}  Date: {_date(rng)}",
        "Status: DRAFT PORTFOLIO REVIEW — not approved for the current lock",
        "## Background",
    ]
    headings = ("Scope", "Open items", "Vendor notes", "Appendix", "Follow-up")
    for i in range(blocks):
        parts.extend([f"\n## {headings[i % len(headings)]} {i + 1}",
                      _noise_block(rng, scope)])
    return "\n".join(parts) + "\n"


_FILLERS: tuple[Callable[[random.Random, str, int, int], str], ...] = (
    _filler_email, _filler_meeting, _filler_chat, _filler_table, _filler_report,
)


def _controlled(title: str, body: str) -> str:
    return (
        f"# {title}\n"
        "Record class: CONTROLLED FINANCE INPUT\n"
        "Effective date: 2026-09-30\n"
        "Approval: Controller and Commercial Finance\n"
        "Use this record for the current decision unless a later controlled record explicitly replaces it.\n\n"
        f"{body.strip()}\n"
    )


def _local_cards(branch_name: str, p: dict,
                 label_map: dict[str, str]) -> list[str]:
    x = BranchPrimitives(**p)
    low = label_map["standard"]
    high = label_map["premium"]
    return [
        _controlled(
            f"{branch_name} annual demand normalization",
            f"Annual reference demand is {x.base_units:.2f} units. The approved seasonal index is {x.seasonal_index:.6f}, and expected availability is {x.availability:.6f}. Use all three quantities in the policy-demand calculation. Earlier weekly run-rate and market-size estimates elsewhere in the binder do not replace these locked inputs."
        ),
        _controlled(
            f"{branch_name} posted-price policy register",
            f"Reference price is ${x.reference_price:.6f}. Policy {low} changes the reference by {x.standard_price_change:.8f}; policy {high} changes it by {x.premium_price_change:.8f}. A policy's posted price equals reference price multiplied by one plus that policy's signed change. The changes are rates, not dollar amounts."
        ),
        _controlled(
            f"{branch_name} demand response method",
            f"Approved own-price elasticity is {x.elasticity:.8f}. For either policy, demand factor equals 1 plus elasticity multiplied by that policy's signed price change. Annual policy units equal annual reference demand multiplied by seasonal index, availability, and demand factor. Do not apply the price response twice."
        ),
        _controlled(
            f"{branch_name} commercial deductions",
            f"Policy {low} discount rate is {x.standard_discount:.8f}; policy {high} discount rate is {x.premium_discount:.8f}. Realized price equals posted price multiplied by one minus the applicable discount. Both policies use a return rate of {x.return_rate:.8f}; kept units equal policy units multiplied by one minus that return rate."
        ),
        _controlled(
            f"{branch_name} current unit-cost ledger",
            f"Landed unit cost is ${x.landed_unit_cost:.6f}. Fulfillment unit cost is ${x.fulfillment_unit_cost:.6f}. Warranty accrual equals {x.warranty_rate:.8f} multiplied by posted policy price. Policy unit cost is the sum of landed cost, fulfillment cost, and warranty accrual. Unit margin equals realized price minus policy unit cost."
        ),
        _controlled(
            f"{branch_name} policy fixed-cost and profit method",
            f"Policy {low} annual fixed cost is ${x.standard_fixed_cost:.8f} million; policy {high} annual fixed cost is ${x.premium_fixed_cost:.8f} million. Local annual profit in millions equals kept units multiplied by unit margin, divided by one million, less the applicable annual fixed cost. Calculate and retain both policies."
        ),
        (
            f"# Withdrawn {branch_name} commercial forecast\n"
            "Record class: WITHDRAWN MODEL — retained for audit history only\n"
            "Date withdrawn: 2026-06-18\n\n"
            "This version assumed 200,000 units, a $99 ticket, elasticity -1.0, and a 10 percent return rate. It predates the controlled records and must not supply any current input or result. Its draft recommendation was never approved.\n"
        ),
        (
            f"# Archived {branch_name} cost assumptions\n"
            "Record class: SUPERSEDED COST NOTE — not valid for the current lock\n"
            "Archive date: 2026-07-02\n\n"
            "The scenario used $44 landed cost, $8 fulfillment cost, a 1 percent warranty rate, and equal fixed costs for both policies. Finance retained it to explain an old variance. Every number in this note was replaced by later controlled records.\n"
        ),
    ]


def _assemble(cards: list[str], rng: random.Random, scope: str,
              total_documents: int, filler_blocks: int,
              card_slots: tuple[int, ...]) -> dict[str, str]:
    if len(card_slots) != len(cards):
        raise ValueError("one insertion slot is required for every evidence card")
    if any(not 1 <= x <= total_documents for x in card_slots):
        raise ValueError("card slot outside binder")
    card_by_slot = dict(zip(card_slots, cards))
    docs: dict[str, str] = {}
    filler_ordinal = 0
    for slot in range(1, total_documents + 1):
        if slot in card_by_slot:
            body = card_by_slot[slot]
        else:
            filler_ordinal += 1
            fn = _FILLERS[(filler_ordinal - 1) % len(_FILLERS)]
            body = fn(rng, scope, filler_ordinal, filler_blocks)
        docs[f"{slot:03d}_record.md"] = body
    return docs


def render_local_documents(branch_name: str, p: dict,
                           label_map: dict[str, str],
                           document_seed: int | None = None) -> dict[str, str]:
    """Render one 24-file local binder with dispersed controlled records."""
    cards = _local_cards(branch_name, p, label_map)
    return _assemble(
        cards, _rng(document_seed, "local-parallel-template"), branch_name,
        LOCAL_DOCUMENT_COUNT, filler_blocks=5,
        card_slots=(3, 6, 9, 12, 15, 18, 21, 24),
    )


def _interaction_cards(interaction: dict, rho: float,
                       label_maps: list[dict[str, str]]) -> list[str]:
    lower_pair = label_maps[0]["standard"] + label_maps[1]["standard"]
    higher_pair = label_maps[0]["premium"] + label_maps[1]["premium"]
    return [
        _controlled(
            "Market-integration weight",
            f"The current rho is {rho:.2f}. Multiply every cross-branch interaction value by the market integration index {interaction['market_integration_index']:.8f} and then by rho. Rho never changes either branch's local profit. Values in old regional rollout decks are descriptive and do not replace this weight."
        ),
        _controlled(
            "Aligned-policy economics",
            f"The aligned lower-price pair is {lower_pair}; the aligned higher-price pair is {higher_pair}. For either aligned pair, add a brand-coherence value of ${interaction['coherence_bonus_per_unit']:.8f} per combined policy unit. For the higher-price pair, also add ${interaction['premium_campaign_synergy_m']:.8f} million. For the lower-price pair, also add ${interaction['standard_service_synergy_m']:.8f} million."
        ),
        _controlled(
            "Cross-policy mismatch and migration",
            f"Every pair other than {lower_pair} and {higher_pair} is a cross-branch policy mismatch. For a mismatch, subtract ${interaction['mismatch_penalty_per_unit']:.8f} per combined policy unit. In addition, {interaction['migration_rate']:.8f} of the higher-posted-price branch's policy units migrate to the lower-posted-price branch. The company migration effect equals migrated units multiplied by (lower-price branch unit margin minus higher-price branch unit margin), divided by one million."
        ),
        _controlled(
            "Company profit formula and pair notation",
            "For branch labels x for Branch 1 and y for Branch 2, company annual profit for pair xy equals Branch 1 local profit under x plus Branch 2 local profit under y plus rho times the applicable cross-branch interaction value after applying the market-integration index. Pair order is always Branch 1 followed by Branch 2. Thus AA, AB, BA, and BB denote the four possible pairs. No draft 2x2 table in this binder is an answer key."
        ),
    ]


def render_interaction_documents(interaction: dict, rho: float,
                                 label_maps: list[dict[str, str]],
                                 document_seed: int | None = None) -> dict[str, str]:
    """Render one 20-file interaction binder with dispersed joint rules."""
    cards = _interaction_cards(interaction, rho, label_maps)
    return _assemble(
        cards, _rng(document_seed, "interaction-template"), "company interaction",
        INTERACTION_DOCUMENT_COUNT, filler_blocks=3,
        card_slots=(4, 9, 14, 19),
    )


def difficulty_signature(documents: dict[str, str]) -> dict[str, float]:
    """Observable binder scale diagnostics; not used in scoring."""
    return {
        "documents": len(documents),
        "whitespace_words": sum(len(x.split()) for x in documents.values()),
        "characters": sum(len(x) for x in documents.values()),
    }
