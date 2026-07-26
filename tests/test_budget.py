"""Tests for budget tracking and enforcement."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from broadside.budget import BudgetGuard, SpendLedger, SpendEntry, LEDGER_PATH


def _make_ledger(entries: list[SpendEntry]) -> SpendLedger:
    return SpendLedger(entries=entries)


def test_empty_ledger_weekly_spend():
    ledger = _make_ledger([])
    assert ledger.weekly_spend() == 0.0


def test_weekly_spend_sums_recent():
    now = datetime.now()
    entries = [
        SpendEntry(timestamp=(now - timedelta(hours=1)).isoformat(), service="heygen", description="test", amount_usd=5.0),
        SpendEntry(timestamp=(now - timedelta(days=2)).isoformat(), service="heygen", description="test", amount_usd=3.0),
    ]
    ledger = _make_ledger(entries)
    assert ledger.weekly_spend() == 8.0


def test_weekly_spend_excludes_old():
    now = datetime.now()
    entries = [
        SpendEntry(timestamp=(now - timedelta(days=10)).isoformat(), service="heygen", description="old", amount_usd=100.0),
        SpendEntry(timestamp=(now - timedelta(hours=1)).isoformat(), service="heygen", description="new", amount_usd=5.0),
    ]
    ledger = _make_ledger(entries)
    assert ledger.weekly_spend() == 5.0


def test_budget_guard_allows_within_limits():
    guard = BudgetGuard(max_batch_usd=25.0, max_weekly_usd=40.0)
    guard.ledger = _make_ledger([])
    result = guard.check_batch(10.0)
    assert result.allowed is True


def test_budget_guard_refuses_over_batch():
    guard = BudgetGuard(max_batch_usd=25.0, max_weekly_usd=40.0)
    guard.ledger = _make_ledger([])
    result = guard.check_batch(30.0)
    assert result.allowed is False
    assert "per-batch cap" in result.reason


def test_budget_guard_refuses_over_weekly():
    now = datetime.now()
    guard = BudgetGuard(max_batch_usd=25.0, max_weekly_usd=40.0)
    guard.ledger = _make_ledger([
        SpendEntry(timestamp=(now - timedelta(hours=1)).isoformat(), service="heygen", description="prior", amount_usd=35.0),
    ])
    result = guard.check_batch(10.0)
    assert result.allowed is False
    assert "weekly" in result.reason.lower()


def test_budget_check_result_summary():
    guard = BudgetGuard(max_batch_usd=25.0, max_weekly_usd=40.0)
    guard.ledger = _make_ledger([])
    result = guard.check_batch(10.0)
    summary = result.summary()
    assert "APPROVED" in summary
    assert "$10.00" in summary


def test_prune_old_entries():
    now = datetime.now()
    ledger = _make_ledger([
        SpendEntry(timestamp=(now - timedelta(days=60)).isoformat(), service="heygen", description="old", amount_usd=5.0),
        SpendEntry(timestamp=(now - timedelta(days=1)).isoformat(), service="heygen", description="new", amount_usd=3.0),
    ])
    pruned = ledger.prune_old(days=30)
    assert pruned == 1
    assert len(ledger.entries) == 1
