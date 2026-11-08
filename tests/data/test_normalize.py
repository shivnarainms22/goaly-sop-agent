import pytest

from sop_agent.data.normalize import norm_dob, norm_email, norm_last4, norm_name, norm_phone


@pytest.mark.parametrize(
    "raw,exp",
    [("Margaret Chen", "margaret chen"), ("  MARGARET   chen ", "margaret chen"), ("", None), (None, None)],
)
def test_norm_name(raw, exp):
    assert norm_name(raw) == exp


@pytest.mark.parametrize(
    "raw,exp",
    [
        ("1985-03-15", "1985-03-15"),
        ("03/15/1985", "1985-03-15"),
        ("March 15, 1985", "1985-03-15"),
        ("15 March 1985", "1985-03-15"),
        ("not a date", None),
        ("", None),
        (None, None),
        ("1985", None),  # incomplete dates must not be completed from defaults
        ("March 1985", None),
        ("03/15/85", None),  # no 4-digit year
    ],
)
def test_norm_dob(raw, exp):
    assert norm_dob(raw) == exp


@pytest.mark.parametrize(
    "raw,exp",
    [
        ("+16505212836", "+16505212836"),
        ("(650) 521-2836", "+16505212836"),
        ("650.521.2836", "+16505212836"),
        ("1 650 521 2836", "+16505212836"),
        ("12345", None),
        (None, None),
    ],
)
def test_norm_phone(raw, exp):
    assert norm_phone(raw) == exp


def test_norm_email():
    assert norm_email(" Margaret@Email.COM ") == "margaret@email.com"
    assert norm_email("nope") is None
    assert norm_email(None) is None


@pytest.mark.parametrize(
    "raw,exp",
    [("4472", "4472"), ("ssn ends in 4472", "4472"), ("447", None), ("123-45-4472", "4472"), (None, None)],
)
def test_norm_last4(raw, exp):
    assert norm_last4(raw) == exp
