from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import RunnerLease, PortfolioObjective
from app.services.runner_broker import reap_expired_leases
from app.services.telemetry_slo import evaluate_due_slos
from app.services.nina_portfolio import review_portfolio


@celery_app.task(name="v14.reap_runner_leases")
def reap_runner_leases():
    db = SessionLocal()
    try: return {"expired": reap_expired_leases(db)}
    finally: db.close()


@celery_app.task(name="v14.evaluate_slos")
def evaluate_slos():
    db = SessionLocal()
    try: return {"evaluated": evaluate_due_slos(db)}
    finally: db.close()


@celery_app.task(name="v14.review_portfolios")
def review_portfolios():
    db = SessionLocal(); count = 0
    try:
        for objective in db.query(PortfolioObjective).filter(PortfolioObjective.status == "active").all():
            review_portfolio(db, organization_id=objective.organization_id, objective=objective, nina_member_id=objective.owner_member_id); count += 1
        return {"reviewed": count}
    finally: db.close()
