import re
from datetime import datetime

from dateutil import parser as dateparser


def norm_name(raw: str | None) -> str | None:
    return " ".join(raw.lower().split()) or None if raw else None


def norm_dob(raw: str | None) -> str | None:
    """Any common date format -> ISO. Requires a 4-digit year and a complete date."""
    if not raw or not re.search(r"\d{4}", raw):
        return None
    try:
        # Parse against two different defaults: a result that depends on the default means a part is missing.
        a = dateparser.parse(raw, dayfirst=False, default=datetime(2000, 1, 1))
        b = dateparser.parse(raw, dayfirst=False, default=datetime(2001, 2, 2))
    except (ValueError, OverflowError):
        return None
    return a.date().isoformat() if a == b else None


def norm_phone(raw: str | None) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def norm_email(raw: str | None) -> str | None:
    email = (raw or "").strip().lower()
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else None


def norm_last4(raw: str | None) -> str | None:
    runs = re.findall(r"\d{4,}", raw or "")
    return runs[-1][-4:] if runs else None


def mask_email(raw: str | None) -> str | None:
    email = norm_email(raw)
    if email is None:
        return None
    local, domain = email.split("@")
    return local[0] + "*" * (len(local) - 1) + "@" + domain
