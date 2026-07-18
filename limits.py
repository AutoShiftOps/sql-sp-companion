"""
Tier limits for sql-sp-companion.

Free tier is generous enough to be genuinely useful for evaluation and small
migrations. Enterprise tier is unlocked by a license key and removes limits.

IMPORTANT — read before changing:
This module is in the Apache-2.0 core, which means anyone can fork it and
remove the limits. That is intentional and legal. The limits exist to make
the free/paid boundary *explicit and honest* for users who want to comply,
not as a technical DRM measure. Real enterprise value lives in features that
are hard to fork (hosted service, support SLA, Purview/Collibra exports,
air-gapped AI) — not in these constants.

See LICENSING.md for the full rationale.
"""

import os
from dataclasses import dataclass, asdict
from typing import Optional


class TierLimitExceeded(Exception):
    """Raised when a request exceeds the active tier's limits."""

    def __init__(self, message: str, limit_name: str, limit_value: int, actual: int):
        super().__init__(message)
        self.message = message
        self.limit_name = limit_name
        self.limit_value = limit_value
        self.actual = actual


@dataclass(frozen=True)
class Tier:
    name: str
    max_files_per_request: int
    max_file_bytes: int
    max_total_bytes: int
    max_tables_per_request: int
    ai_insights: bool
    batch_api: bool

    def as_dict(self) -> dict:
        return asdict(self)


FREE = Tier(
    name="free",
    max_files_per_request=5,
    max_file_bytes=1 * 1024 * 1024,        # 1 MB per file
    max_total_bytes=5 * 1024 * 1024,       # 5 MB per request
    max_tables_per_request=50,             # ~a small migration wave
    ai_insights=True,                      # allowed, but user supplies HF_TOKEN
    batch_api=False,
)

ENTERPRISE = Tier(
    name="enterprise",
    max_files_per_request=10_000,
    max_file_bytes=100 * 1024 * 1024,
    max_total_bytes=2 * 1024 * 1024 * 1024,
    max_tables_per_request=1_000_000,
    ai_insights=True,
    batch_api=True,
)

_TIERS = {"free": FREE, "enterprise": ENTERPRISE}


def _validate_license_key(key: str) -> bool:
    """
    Placeholder validation. Real implementation lives in the proprietary
    enterprise package and performs signature verification against a public
    key. The core deliberately does not contain the verification logic.
    """
    return bool(key) and key.startswith("SPC-ENT-") and len(key) >= 20


def active_tier(license_key: Optional[str] = None) -> Tier:
    """Resolve the active tier from an explicit key or the environment."""
    key = license_key if license_key is not None else os.getenv("SPC_LICENSE_KEY", "")
    if _validate_license_key(key):
        return ENTERPRISE
    return FREE


def check_upload_limits(tier: Tier, file_sizes: list[int]) -> None:
    """Validate an incoming upload against the tier. Raises TierLimitExceeded."""
    n = len(file_sizes)
    if n > tier.max_files_per_request:
        raise TierLimitExceeded(
            f"{tier.name} tier allows {tier.max_files_per_request} files per request "
            f"(received {n}). Upgrade for unlimited batch analysis.",
            "max_files_per_request", tier.max_files_per_request, n,
        )

    for size in file_sizes:
        if size > tier.max_file_bytes:
            raise TierLimitExceeded(
                f"{tier.name} tier allows {tier.max_file_bytes // 1024 // 1024} MB per file "
                f"(received {size / 1024 / 1024:.1f} MB).",
                "max_file_bytes", tier.max_file_bytes, size,
            )

    total = sum(file_sizes)
    if total > tier.max_total_bytes:
        raise TierLimitExceeded(
            f"{tier.name} tier allows {tier.max_total_bytes // 1024 // 1024} MB per request "
            f"(received {total / 1024 / 1024:.1f} MB).",
            "max_total_bytes", tier.max_total_bytes, total,
        )


def check_result_limits(tier: Tier, table_count: int) -> None:
    """Validate analysis output size against the tier."""
    if table_count > tier.max_tables_per_request:
        raise TierLimitExceeded(
            f"{tier.name} tier reports up to {tier.max_tables_per_request} distinct tables "
            f"(found {table_count}). Upgrade to analyze full estates.",
            "max_tables_per_request", tier.max_tables_per_request, table_count,
        )
