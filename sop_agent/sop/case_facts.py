import re
from datetime import date

from sop_agent.data.repository import Claim, Repository


def claim_facts(claim: Claim, today: date) -> dict:
    facts = claim.model_dump(mode="json", exclude_none=True)
    if claim.appeal_deadline:
        days_left = (claim.appeal_deadline - today).days
        facts["appeal_deadline_passed"] = days_left < 0
        facts["days_until_appeal_deadline"] = days_left
    return facts


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _match_document_key(document: str, keys: list[str]) -> str | None:
    """Fuzzy match by token overlap; a tie between several keys is no match (never pick the first)."""
    query = _tokens(document)
    scored = []
    for key in keys:
        key_tokens = _tokens(key)
        jaccard = len(query & key_tokens) / len(query | key_tokens) if query else 0
        if query and (query <= key_tokens or jaccard >= 0.5):
            scored.append((jaccard, key))
    if not scored:
        return None
    top = max(score for score, _ in scored)
    winners = [key for score, key in scored if score == top]
    return winners[0] if len(winners) == 1 else None


def document_guidance(repo: Repository, document: str, case_type: str) -> dict:
    g = repo.guidelines
    key = _match_document_key(document, list(g["document_guidance"]))
    alternatives = g["document_alternative_guidance"]
    return {
        "document": document,
        "matched_key": key,
        "guidance": g["document_guidance"][key]["en"] if key else g["default_guidance"]["en"],
        "alternatives": alternatives[key if key in alternatives else "default"]["en"],
        "case_type_guidance": g["case_type_guidance"].get(case_type, {}).get("en"),
    }


def followup_guidance(repo: Repository, claim: Claim, question: str, intent: str) -> list[str]:
    g = repo.guidelines
    values = {
        "case_id": claim.case_id,
        "documents": ", ".join(claim.documents_needed),
        "average_processing_time_after_submission": g["claim_followup_settings"][
            "average_processing_time_after_submission"
        ]["en"],
    }
    asked = question.lower()
    return [
        topic["en"].format(**values)
        for topic in g["claim_followup_guidance"]
        if intent in topic["intent_hints"]
        and not (topic.get("requires_documents") and not claim.documents_needed)
        and (not topic.get("match_any") or any(phrase in asked for phrase in topic["match_any"]))
    ]


def build_case_bundle(repo: Repository, claim: Claim, intent: str, question: str, today: date) -> dict:
    """Everything the engine may disclose about one claim (claim must be scoped to the verified party)."""
    g = repo.guidelines
    bundle = {
        "claim": claim_facts(claim, today),
        "documents": [document_guidance(repo, d, claim.case_type) for d in claim.documents_needed],
        "submission": " ".join(
            filter(
                None,
                [g["default_guidance"]["en"], g["case_type_guidance"].get(claim.case_type, {}).get("en")],
            )
        ),
        "followups": followup_guidance(repo, claim, question, intent),
    }
    if not bundle["followups"]:
        bundle["fallback"] = repo.guidelines["claim_followup_fallback"]["en"]
    return bundle
