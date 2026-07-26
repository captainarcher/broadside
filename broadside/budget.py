"""Budget tracking and enforcement for Broadside.

Spend ledger lives at ~/.broadside/spend.json — a rolling weekly window
of all API spend across HeyGen, Replicate, ElevenLabs, Claude, Descript.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

LEDGER_DIR = Path.home() / ".broadside"
LEDGER_PATH = LEDGER_DIR / "spend.json"


class SpendEntry(BaseModel):
    timestamp: str
    service: str
    description: str
    amount_usd: float


class SpendLedger(BaseModel):
    entries: list[SpendEntry] = Field(default_factory=list)

    @classmethod
    def load(cls) -> SpendLedger:
        if not LEDGER_PATH.exists():
            return cls()
        with open(LEDGER_PATH) as f:
            data = json.load(f)
        return cls.model_validate(data)

    def save(self) -> None:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, "w") as f:
            json.dump(self.model_dump(), f, indent=2)

    def record(self, service: str, description: str, amount_usd: float) -> None:
        self.entries.append(
            SpendEntry(
                timestamp=datetime.now().isoformat(),
                service=service,
                description=description,
                amount_usd=amount_usd,
            )
        )
        self.save()

    def weekly_spend(self) -> float:
        cutoff = datetime.now() - timedelta(days=7)
        return sum(
            e.amount_usd
            for e in self.entries
            if datetime.fromisoformat(e.timestamp) > cutoff
        )

    def today_spend(self) -> float:
        today = datetime.now().date()
        return sum(
            e.amount_usd
            for e in self.entries
            if datetime.fromisoformat(e.timestamp).date() == today
        )

    def prune_old(self, days: int = 30) -> int:
        cutoff = datetime.now() - timedelta(days=days)
        before = len(self.entries)
        self.entries = [
            e
            for e in self.entries
            if datetime.fromisoformat(e.timestamp) > cutoff
        ]
        pruned = before - len(self.entries)
        if pruned:
            self.save()
        return pruned


class BudgetGuard:
    """Enforces per-batch and weekly spend caps."""

    def __init__(self, max_batch_usd: float, max_weekly_usd: float) -> None:
        self.max_batch_usd = max_batch_usd
        self.max_weekly_usd = max_weekly_usd
        self.ledger = SpendLedger.load()

    def check_batch(self, estimated_cost: float) -> BudgetCheckResult:
        weekly = self.ledger.weekly_spend()
        if estimated_cost > self.max_batch_usd:
            return BudgetCheckResult(
                allowed=False,
                reason=(
                    f"Batch cost ${estimated_cost:.2f} exceeds per-batch cap "
                    f"${self.max_batch_usd:.2f}"
                ),
                estimated_cost=estimated_cost,
                weekly_spend=weekly,
            )
        if weekly + estimated_cost > self.max_weekly_usd:
            return BudgetCheckResult(
                allowed=False,
                reason=(
                    f"Batch cost ${estimated_cost:.2f} would push weekly spend "
                    f"to ${weekly + estimated_cost:.2f}, exceeding weekly cap "
                    f"${self.max_weekly_usd:.2f}"
                ),
                estimated_cost=estimated_cost,
                weekly_spend=weekly,
            )
        return BudgetCheckResult(
            allowed=True,
            reason="Within budget",
            estimated_cost=estimated_cost,
            weekly_spend=weekly,
        )

    def record_spend(self, service: str, description: str, amount: float) -> None:
        self.ledger.record(service, description, amount)


class BudgetCheckResult(BaseModel):
    allowed: bool
    reason: str
    estimated_cost: float
    weekly_spend: float

    def summary(self) -> str:
        status = "APPROVED" if self.allowed else "REFUSED"
        return (
            f"Budget check: {status}\n"
            f"  Estimated cost: ${self.estimated_cost:.2f}\n"
            f"  Weekly spend so far: ${self.weekly_spend:.2f}\n"
            f"  Reason: {self.reason}"
        )
