import json
from dataclasses import dataclass
from datetime import date
from functools import cache, cached_property
from pathlib import Path

from pydantic import BaseModel

from sop_agent.config import Settings
from sop_agent.data.normalize import norm_email, norm_name, norm_phone


class Policyholder(BaseModel):
    party_id: str
    name: str
    policy_number: str
    dob: str
    id_type: str
    id_last4: str
    phone: str
    email: str
    name_aliases: list[str] = []
    phone_aliases: list[str] = []
    email_aliases: list[str] = []

    @cached_property
    def name_set(self) -> frozenset[str]:
        return frozenset(norm_name(n) for n in [self.name, *self.name_aliases])

    @cached_property
    def phone_set(self) -> frozenset[str]:
        return frozenset(norm_phone(p) for p in [self.phone, *self.phone_aliases])

    @cached_property
    def email_set(self) -> frozenset[str]:
        return frozenset(norm_email(e) for e in [self.email, *self.email_aliases])


class Claim(BaseModel):
    case_id: str
    party_id: str
    case_type: str
    created_at: date
    status: str
    summary: str
    denial_reason: str | None = None
    documents_needed: list[str] = []
    appeal_deadline: date | None = None
    expected_reimbursement_amount: str
    allowed_max_amount: str
    net_pay: str
    net_fee: str


class Representative(BaseModel):
    rep_name: str
    relationship: str
    buyer_name: str
    buyer_party_id: str


@dataclass(frozen=True)
class Repository:
    policyholders: list[Policyholder]
    claims: list[Claim]
    representatives: list[Representative]
    guidelines: dict
    consent_scenarios: dict[str, list[str]]

    @classmethod
    def load(cls, fixtures_dir: Path | None = None) -> "Repository":
        return _load(fixtures_dir or Settings().fixtures_dir)

    def policyholder(self, party_id: str) -> Policyholder | None:
        return next((p for p in self.policyholders if p.party_id == party_id), None)

    def claims_for(self, party_id: str) -> list[Claim]:
        return [c for c in self.claims if c.party_id == party_id]

    def representatives_for(self, party_id: str) -> list[Representative]:
        return [r for r in self.representatives if r.buyer_party_id == party_id]

    def claim_for_party(self, party_id: str, case_id: str) -> Claim | None:
        return next((c for c in self.claims_for(party_id) if c.case_id.lower() == case_id.lower()), None)


@cache
def _load(fixtures_dir: Path) -> Repository:
    def read(name: str):
        return json.loads((fixtures_dir / name).read_text(encoding="utf-8"))

    return Repository(
        policyholders=[Policyholder(**p) for p in read("policyholders.json")],
        claims=[Claim(**c) for c in read("claims.json")],
        representatives=[Representative(**r) for r in read("representatives.json")],
        guidelines=read("required_document_guideline.json"),
        consent_scenarios={k: v["status_sequence"] for k, v in read("consent_scenarios.json").items()},
    )
