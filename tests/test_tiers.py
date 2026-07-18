"""
LAYER 4 — TIER / COMMERCIAL BOUNDARY TESTS

The free/enterprise boundary is a product promise. If free-tier limits silently
tighten, we break trust with the community that adopted the tool. If they
silently loosen, we break the business model.

These tests pin the boundary so any change to it is a deliberate, reviewed act.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from limits import (
    FREE, ENTERPRISE, active_tier, check_upload_limits, check_result_limits,
    TierLimitExceeded,
)


# ── Tier resolution ───────────────────────────────────────────────────────────

def test_no_key_yields_free_tier(monkeypatch):
    monkeypatch.delenv("SPC_LICENSE_KEY", raising=False)
    assert active_tier().name == "free"


def test_valid_key_yields_enterprise_tier():
    assert active_tier("SPC-ENT-ABCDEFGH-12345678").name == "enterprise"


@pytest.mark.parametrize("key", ["", "garbage", "SPC-ENT-", "ENT-SPC-XXXXXXXXXXXXXX", None])
def test_invalid_keys_fall_back_to_free(key, monkeypatch):
    monkeypatch.delenv("SPC_LICENSE_KEY", raising=False)
    assert active_tier(key or "").name == "free"


def test_env_var_is_read(monkeypatch):
    monkeypatch.setenv("SPC_LICENSE_KEY", "SPC-ENT-FROMENV-000000000")
    assert active_tier().name == "enterprise"


# ── Free tier boundary is exactly where we documented it ──────────────────────

def test_free_tier_published_limits_are_stable():
    """If you change these numbers you MUST update README and the pricing page."""
    assert FREE.max_files_per_request == 5
    assert FREE.max_file_bytes == 1 * 1024 * 1024
    assert FREE.max_total_bytes == 5 * 1024 * 1024
    assert FREE.max_tables_per_request == 50
    assert FREE.ai_insights is True
    assert FREE.batch_api is False


def test_enterprise_removes_the_ceilings():
    assert ENTERPRISE.max_files_per_request > FREE.max_files_per_request
    assert ENTERPRISE.max_file_bytes > FREE.max_file_bytes
    assert ENTERPRISE.max_tables_per_request > FREE.max_tables_per_request
    assert ENTERPRISE.batch_api is True


# ── Upload limit enforcement ──────────────────────────────────────────────────

def test_free_allows_exactly_the_limit():
    check_upload_limits(FREE, [1000] * 5)  # 5 files, at the boundary — must pass


def test_free_rejects_one_file_over():
    with pytest.raises(TierLimitExceeded) as e:
        check_upload_limits(FREE, [1000] * 6)
    assert e.value.limit_name == "max_files_per_request"
    assert e.value.actual == 6


def test_free_rejects_oversized_single_file():
    with pytest.raises(TierLimitExceeded) as e:
        check_upload_limits(FREE, [FREE.max_file_bytes + 1])
    assert e.value.limit_name == "max_file_bytes"


def test_free_rejects_oversized_total():
    with pytest.raises(TierLimitExceeded) as e:
        check_upload_limits(FREE, [1024 * 1024] * 5 + [1])
    # 6 files trips the file-count limit first — that is correct precedence
    assert e.value.limit_name in {"max_files_per_request", "max_total_bytes"}


def test_enterprise_accepts_what_free_rejects():
    check_upload_limits(ENTERPRISE, [10 * 1024 * 1024] * 100)  # must not raise


# ── Result limit enforcement ──────────────────────────────────────────────────

def test_free_allows_table_count_at_limit():
    check_result_limits(FREE, FREE.max_tables_per_request)


def test_free_rejects_table_count_over_limit():
    with pytest.raises(TierLimitExceeded) as e:
        check_result_limits(FREE, FREE.max_tables_per_request + 1)
    assert e.value.limit_name == "max_tables_per_request"


def test_error_message_tells_user_what_to_do():
    """A limit error must be actionable, not just a 413."""
    with pytest.raises(TierLimitExceeded) as e:
        check_upload_limits(FREE, [1000] * 99)
    msg = e.value.message.lower()
    assert "free" in msg
    assert "upgrade" in msg, "limit errors must state the remedy"


# ── The free tier must stay genuinely useful ──────────────────────────────────

def test_free_tier_handles_a_realistic_evaluation_workload():
    """
    Product promise: a BSA can evaluate the tool on a real report pack without
    paying. If this fails, the free tier is a demo, not a product, and adoption
    dies. 5 files x ~200KB is a realistic first touch.
    """
    check_upload_limits(FREE, [200 * 1024] * 5)
    check_result_limits(FREE, 40)
