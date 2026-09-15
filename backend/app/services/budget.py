from sqlalchemy.orm import Session
from app.models import BudgetEnvelope, BudgetLedgerEntry


def remaining(budget: BudgetEnvelope) -> float:
    return max(0.0, float(budget.amount_limit or 0) - float(budget.amount_reserved or 0) - float(budget.amount_spent or 0))


def can_reserve(budget: BudgetEnvelope, amount: float) -> tuple[bool, str]:
    if budget.status != "active":
        return False, f"Budget is {budget.status}"
    if amount < 0:
        return False, "Amount must be non-negative"
    if amount > remaining(budget) + 1e-9:
        return False, f"Budget exceeded: need {amount:.2f}, remaining {remaining(budget):.2f}"
    return True, "ok"


def reserve(db: Session, budget: BudgetEnvelope, amount: float, *, source_type: str, source_id: str, memo: str = ""):
    ok, reason = can_reserve(budget, amount)
    if not ok:
        raise ValueError(reason)
    budget.amount_reserved = float(budget.amount_reserved or 0) + amount
    entry = BudgetLedgerEntry(
        organization_id=budget.organization_id, budget_id=budget.id, entry_type="reserve", amount=amount,
        source_type=source_type, source_id=source_id, memo=memo,
    )
    db.add_all([budget, entry]); db.commit(); db.refresh(budget); db.refresh(entry)
    return entry


def settle_reserved(db: Session, budget: BudgetEnvelope, amount: float, *, source_type: str, source_id: str, memo: str = ""):
    amount = min(amount, float(budget.amount_reserved or 0))
    budget.amount_reserved = max(0.0, float(budget.amount_reserved or 0) - amount)
    budget.amount_spent = float(budget.amount_spent or 0) + amount
    entry = BudgetLedgerEntry(
        organization_id=budget.organization_id, budget_id=budget.id, entry_type="spend", amount=amount,
        source_type=source_type, source_id=source_id, memo=memo,
    )
    db.add_all([budget, entry]); db.commit(); db.refresh(budget); db.refresh(entry)
    return entry


def release_reserved(db: Session, budget: BudgetEnvelope, amount: float, *, source_type: str, source_id: str, memo: str = ""):
    amount = min(amount, float(budget.amount_reserved or 0))
    budget.amount_reserved = max(0.0, float(budget.amount_reserved or 0) - amount)
    entry = BudgetLedgerEntry(
        organization_id=budget.organization_id, budget_id=budget.id, entry_type="release", amount=amount,
        source_type=source_type, source_id=source_id, memo=memo,
    )
    db.add_all([budget, entry]); db.commit(); db.refresh(budget); db.refresh(entry)
    return entry
