"""Email verification uniqueness policy."""

from dataclasses import dataclass
from threading import RLock
from typing import Dict, Set


class DuplicateVerifiedEmailError(ValueError):
    """Raised when a canonical verified email is owned by another user."""


class InvalidEmailAddressError(ValueError):
    """Raised when an email address cannot be canonicalized safely."""


@dataclass(frozen=True)
class EmailProviderPolicy:
    canonical_domain: str
    ignore_dots: bool = False
    ignore_plus_tags: bool = False


@dataclass(frozen=True)
class EmailVerificationResult:
    user_id: str
    email: str
    canonical_email: str
    already_verified: bool

    def to_dict(self) -> Dict[str, object]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "canonical_email": self.canonical_email,
            "already_verified": self.already_verified,
        }


# Provider-specific alias rules used before the verified-email uniqueness
# check. Generic domains only receive case normalization because dots and
# plus-tags are not universally aliases outside these providers.
EMAIL_PROVIDER_POLICIES: Dict[str, EmailProviderPolicy] = {
    "gmail.com": EmailProviderPolicy(
        canonical_domain="gmail.com",
        ignore_dots=True,
        ignore_plus_tags=True,
    ),
    "googlemail.com": EmailProviderPolicy(
        canonical_domain="gmail.com",
        ignore_dots=True,
        ignore_plus_tags=True,
    ),
    "outlook.com": EmailProviderPolicy(
        canonical_domain="outlook.com",
        ignore_plus_tags=True,
    ),
    "hotmail.com": EmailProviderPolicy(
        canonical_domain="hotmail.com",
        ignore_plus_tags=True,
    ),
    "live.com": EmailProviderPolicy(
        canonical_domain="live.com",
        ignore_plus_tags=True,
    ),
}


def email_canonicalization_policy() -> Dict[str, Dict[str, object]]:
    return {
        provider: {
            "canonical_domain": policy.canonical_domain,
            "ignore_dots": policy.ignore_dots,
            "ignore_plus_tags": policy.ignore_plus_tags,
        }
        for provider, policy in EMAIL_PROVIDER_POLICIES.items()
    }


def canonicalize_verified_email(email: str) -> str:
    normalized = email.strip()
    if normalized.count("@") != 1:
        raise InvalidEmailAddressError("Email address must contain one @")

    local_part, domain = normalized.rsplit("@", 1)
    local_part = local_part.strip().casefold()
    domain = domain.strip().casefold()
    if not local_part or not domain:
        raise InvalidEmailAddressError(
            "Email local part and domain are required"
        )
    if any(character.isspace() for character in local_part + domain):
        raise InvalidEmailAddressError(
            "Email address cannot contain whitespace"
        )

    policy = EMAIL_PROVIDER_POLICIES.get(domain)
    if policy:
        if policy.ignore_plus_tags:
            local_part = local_part.split("+", 1)[0]
        if policy.ignore_dots:
            local_part = local_part.replace(".", "")
        domain = policy.canonical_domain

    if not local_part:
        raise InvalidEmailAddressError("Email local part is required")

    return f"{local_part}@{domain}"


class EmailVerificationStore:
    """Stores canonical verified email ownership across user accounts."""

    def __init__(self):
        self._lock = RLock()
        self._owners_by_canonical_email: Dict[str, str] = {}
        self._raw_emails_by_canonical_email: Dict[str, Set[str]] = {}

    def verify_email_claim(
        self,
        user_id: str,
        email: str,
    ) -> EmailVerificationResult:
        canonical_email = canonicalize_verified_email(email)
        cleaned_email = email.strip()

        with self._lock:
            owner = self._owners_by_canonical_email.get(canonical_email)
            if owner is not None and owner != user_id:
                raise DuplicateVerifiedEmailError(
                    "Verified email is already claimed by another user"
                )

            self._owners_by_canonical_email[canonical_email] = user_id
            self._raw_emails_by_canonical_email.setdefault(
                canonical_email,
                set(),
            ).add(cleaned_email)

            return EmailVerificationResult(
                user_id=user_id,
                email=cleaned_email,
                canonical_email=canonical_email,
                already_verified=owner == user_id,
            )

    def owner_for(self, email: str) -> str:
        canonical_email = canonicalize_verified_email(email)
        with self._lock:
            return self._owners_by_canonical_email.get(canonical_email, "")
