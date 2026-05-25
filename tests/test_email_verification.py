import pytest

from src.common.email_verification import (
    DuplicateVerifiedEmailError,
    EmailVerificationStore,
    InvalidEmailAddressError,
    canonicalize_verified_email,
    email_canonicalization_policy,
)


def test_gmail_case_dot_and_plus_variants_are_duplicate_claims():
    store = EmailVerificationStore()

    first = store.verify_email_claim("user-1", "First.Last+promo@Gmail.com")

    assert first.canonical_email == "firstlast@gmail.com"
    with pytest.raises(DuplicateVerifiedEmailError):
        store.verify_email_claim("user-2", "firstlast@googlemail.com")


def test_same_user_can_reverify_canonical_email_variant():
    store = EmailVerificationStore()

    store.verify_email_claim("user-1", "first.last@gmail.com")
    result = store.verify_email_claim("user-1", "firstlast+tag@gmail.com")

    assert result.already_verified is True
    assert result.canonical_email == "firstlast@gmail.com"


def test_outlook_plus_tags_are_aliases_but_dots_are_preserved():
    store = EmailVerificationStore()

    store.verify_email_claim("user-1", "owner+tag@outlook.com")

    with pytest.raises(DuplicateVerifiedEmailError):
        store.verify_email_claim("user-2", "OWNER@outlook.com")

    dotted = store.verify_email_claim("user-2", "ow.ner@outlook.com")
    assert dotted.canonical_email == "ow.ner@outlook.com"


def test_generic_domains_do_not_apply_provider_alias_rules():
    store = EmailVerificationStore()

    store.verify_email_claim("user-1", "first.last+tag@example.com")
    result = store.verify_email_claim("user-2", "firstlast@example.com")

    assert result.canonical_email == "firstlast@example.com"


def test_email_provider_alias_policy_is_documented():
    policy = email_canonicalization_policy()

    assert policy["gmail.com"] == {
        "canonical_domain": "gmail.com",
        "ignore_dots": True,
        "ignore_plus_tags": True,
    }
    assert policy["outlook.com"] == {
        "canonical_domain": "outlook.com",
        "ignore_dots": False,
        "ignore_plus_tags": True,
    }


def test_invalid_email_addresses_are_rejected():
    with pytest.raises(InvalidEmailAddressError):
        canonicalize_verified_email("missing-at.example.com")

    with pytest.raises(InvalidEmailAddressError):
        canonicalize_verified_email("two@@example.com")
