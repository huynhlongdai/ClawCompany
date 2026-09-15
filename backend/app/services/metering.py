import json
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models import UsageEvent, BillingInvoice, Customer, Subscription

def record_usage(db: Session, **kwargs):
    quantity = float(kwargs.pop("quantity", 1))
    unit_cost = float(kwargs.pop("unit_cost", 0))
    metadata = kwargs.pop("metadata", {})
    item = UsageEvent(
        quantity=quantity, unit_cost=unit_cost, amount=quantity * unit_cost,
        metadata_json=json.dumps(metadata, ensure_ascii=False), **kwargs,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item

def customer_usage_summary(db: Session, customer_id: int):
    total_events = db.query(func.count(UsageEvent.id)).filter(UsageEvent.customer_id == customer_id).scalar() or 0
    total_qty = db.query(func.coalesce(func.sum(UsageEvent.quantity), 0)).filter(UsageEvent.customer_id == customer_id).scalar() or 0
    total_cost = db.query(func.coalesce(func.sum(UsageEvent.amount), 0)).filter(UsageEvent.customer_id == customer_id).scalar() or 0
    by_type = {k: float(v or 0) for k, v in db.query(UsageEvent.event_type, func.sum(UsageEvent.amount)).filter(UsageEvent.customer_id == customer_id).group_by(UsageEvent.event_type).all()}
    return {"events": int(total_events), "quantity": float(total_qty), "cost": float(total_cost), "by_type": by_type}

def generate_invoice(db: Session, customer_id: int, period_start: str, period_end: str, currency: str = "USD"):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise ValueError("Customer not found")
    usage = customer_usage_summary(db, customer_id)
    sub = db.query(Subscription).filter(Subscription.customer_id == customer_id, Subscription.status == "active").order_by(Subscription.id.desc()).first()
    base = float(sub.mrr if sub else customer.mrr or 0)
    ai_cost = float(usage["cost"])
    lines = [
        {"type": "subscription", "label": sub.plan if sub else customer.plan, "amount": base},
        {"type": "usage_cost_reference", "label": "AI usage cost (internal)", "amount": 0},
    ]
    inv = BillingInvoice(
        customer_id=customer_id, period_start=period_start, period_end=period_end,
        subtotal=base, ai_cost=ai_cost, total=base, currency=currency, status="draft",
        line_items_json=json.dumps(lines, ensure_ascii=False),
    )
    db.add(inv); db.commit(); db.refresh(inv)
    return inv
