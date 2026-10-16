"""M2c D8 — Chẩn đoán "sẵn sàng agent" của một công ty.

Bảng hỏi ngắn (khối lượng việc lặp lại, quy trình đã viết ra chưa, dữ liệu số hoá tới đâu, có người duyệt ngoại lệ
hằng ngày không, mức chấp nhận sai sót) + kiểm tra TỰ ĐỘNG trên dữ liệu thật của các lớp công ty đã dựng ở M2b–M2c:
pháp nhân & hiến chương, tổ chức (chức danh, định biên, JD), quyền quyết (ma trận), quy trình (có chủ, bước gắn chức
danh, đã chạy), KPI, tri thức (tài liệu cốt lõi, SOP gắn bước), nhịp vận hành, tuân thủ. Mỗi kiểm tra có đường dẫn
tới đúng tab để sửa. Kết quả: điểm từng lớp (0–100), điểm chung có trọng số, mức (mới bắt đầu / đang xây nền / sẵn
sàng thí điểm) và một quy trình **lighthouse** đề xuất (lặp nhiều, luật rõ, có người làm, rủi ro tiền thấp, đo được)
— đúng bước 0 và 2 của lộ trình trong ``docs/company-anatomy-and-agent-company.md`` mục C.

Chạy tự động khi tạo công ty (``provisioning.seed_authority`` gọi ``assess(trigger="company_created")``) và khi bấm
"Chấm lại". Không gọi model: điểm là luật rõ ràng để người quản lý thấy vì sao.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import SOP, Company, KnowledgeDocument, Member
from app.models.company_foundation import AuthorityRule, CompanyProfile, Position
from app.models.company_ops import (ComplianceRule, KpiDefinition, Process, ProcessInstance, ProcessStep,
                                    ReadinessAssessment, RhythmConfig)

QUESTIONS = [
    {"key": "volume", "options": ["lt10", "10_50", "50_200", "gt200"]},
    {"key": "documented", "options": ["none", "partial", "most"]},
    {"key": "digital", "options": ["paper", "sheet", "system"]},
    {"key": "reviewers", "options": ["no", "sometimes", "daily"]},
    {"key": "risk", "options": ["low", "medium", "high"]},
]
ANSWER_SCORE = {"documented": {"none": 0, "partial": 0.5, "most": 1}, "digital": {"paper": 0, "sheet": 0.6, "system": 1},
                "reviewers": {"no": 0, "sometimes": 0.5, "daily": 1}, "volume": {"lt10": 0.3, "10_50": 0.7, "50_200": 1, "gt200": 1},
                "risk": {"low": 0.6, "medium": 1, "high": 1}}
LAYERS = [  # khoá, nhãn, trọng số, tab để sửa
    ("legal", "Pháp nhân & hiến chương", 10, "profile"),
    ("org", "Tổ chức & chức danh", 15, "positions"),
    ("authority", "Ma trận phân quyền", 15, "authority"),
    ("process", "Quy trình", 20, "processes"),
    ("kpi", "Mục tiêu & KPI", 10, "kpi"),
    ("knowledge", "Tri thức", 15, "training"),
    ("documents", "Hồ sơ & tài liệu", 10, "records"),     # M3d: hồ sơ bắt buộc + độ tươi tài liệu
    ("rhythm", "Nhịp vận hành", 5, "rhythm"),
    ("compliance", "Tuân thủ", 10, "compliance"),
    ("operations", "Mức sẵn sàng vận hành (bảng hỏi)", 10, "readiness"),
]
LEVELS = [(70, "pilot_ready", "Sẵn sàng thí điểm"), (40, "building", "Đang xây nền"), (0, "starting", "Mới bắt đầu")]
MONEY_ACTIONS = ("spend", "refund", "contract")


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


def _href(tab: str, company_id: int) -> str:
    return f"/app/team?tab={tab}&company={company_id}"


def _check(cid: int, layer: str, key: str, label: str, value: float, detail: str, tab: str) -> dict:
    return {"layer": layer, "key": key, "label": label, "score": round(max(0.0, min(1.0, value)), 2),
            "ok": value >= 0.999, "detail": detail, "fix_href": _href(tab, cid)}


def checks(db: Session, co: Company, answers: dict) -> list[dict]:
    cid, out = co.id, []
    p = db.query(CompanyProfile).filter(CompanyProfile.company_id == cid).first()
    legal = [bool(p and p.legal_name), bool(p and p.entity_type), bool(p and p.tax_code), bool(p and p.legal_representative)]
    out.append(_check(cid, "legal", "legal_profile", "Hồ sơ pháp nhân đủ (tên, loại hình, MST, người đại diện)",
                      sum(legal) / 4, f"{sum(legal)}/4 trường đã điền", "profile"))
    charter = [bool(p and p.mission), bool(p and p.brand_voice), bool(p and p.prohibitions)]
    out.append(_check(cid, "legal", "charter", "Hiến chương có sứ mệnh, giọng thương hiệu, điều cấm (agent đọc trong AGENTS.md)",
                      sum(charter) / 3, f"{sum(charter)}/3 phần đã có", "profile"))
    pos = db.query(Position).filter(Position.company_id == cid, Position.status != "archived").all()
    seats = db.query(Member).filter(Member.company_id == cid, Member.status != "archived").all()
    filled = {m.position_id for m in seats if m.position_id}
    hc = sum(x.headcount or 0 for x in pos)
    nseated = sum(1 for m in seats if m.position_id)
    out.append(_check(cid, "org", "positions", "Có chức danh tách khỏi người ngồi", 1.0 if pos else 0.0,
                      f"{len(pos)} chức danh", "positions"))
    out.append(_check(cid, "org", "headcount", "Định biên đã có người ngồi", (nseated / hc) if hc else 0.0,
                      f"{nseated}/{hc} ghế có người", "positions"))
    jd = sum(1 for x in pos if (x.job_description or "").strip())
    out.append(_check(cid, "org", "jd", "Chức danh có mô tả công việc (JD)", (jd / len(pos)) if pos else 0.0,
                      f"{jd}/{len(pos)} chức danh có JD", "positions"))
    rules = db.query(AuthorityRule).filter(AuthorityRule.company_id == cid, AuthorityRule.enabled.is_(True)).all()
    kinds = {r.action_type for r in rules}
    need = ("spend", "refund", "external_message")
    out.append(_check(cid, "authority", "matrix", "Ma trận phân quyền có luật cho chi tiền, hoàn tiền, gửi ra ngoài",
                      sum(1 for k in need if k in kinds) / len(need), f"{len(rules)} luật, có {', '.join(sorted(kinds & set(need))) or 'chưa loại nào'}",
                      "authority"))
    procs = db.query(Process).filter(Process.company_id == cid, Process.status != "archived").all()
    steps = db.query(ProcessStep).filter(ProcessStep.process_id.in_([x.id for x in procs] or [-1])).all()
    out.append(_check(cid, "process", "processes", "Có quy trình chuỗi giá trị trên bản đồ", min(1.0, len(procs) / 2),
                      f"{len(procs)} quy trình", "processes"))
    owned = sum(1 for x in procs if x.owner_position_id)
    out.append(_check(cid, "process", "owners", "Quy trình có chức danh làm chủ", (owned / len(procs)) if procs else 0.0,
                      f"{owned}/{len(procs)} có chủ", "processes"))
    bound = sum(1 for s in steps if s.position_id and s.position_id in filled)
    out.append(_check(cid, "process", "step_owners", "Bước quy trình gắn chức danh đang có người", (bound / len(steps)) if steps else 0.0,
                      f"{bound}/{len(steps)} bước", "processes"))
    runs = db.query(ProcessInstance).filter(ProcessInstance.company_id == cid, ProcessInstance.status == "done").count()
    out.append(_check(cid, "process", "runs", "Đã chạy trọn ít nhất một quy trình (có thời gian chu trình)", 1.0 if runs else 0.0,
                      f"{runs} lần chạy xong", "processes"))
    kpis = db.query(KpiDefinition).filter(KpiDefinition.company_id == cid, KpiDefinition.status == "active").all()
    out.append(_check(cid, "kpi", "company_kpi", "Có KPI cấp công ty / phòng ban", 1.0 if any(k.level in ("company", "department") for k in kpis) else 0.0,
                      f"{sum(1 for k in kpis if k.level in ('company', 'department'))} KPI", "kpi"))
    out.append(_check(cid, "kpi", "seat_kpi", "KPI chia xuống tới seat", 1.0 if any(k.level == "seat" for k in kpis) else 0.0,
                      f"{sum(1 for k in kpis if k.level == 'seat')} KPI seat", "kpi"))
    core = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == co.organization_id,
                                              KnowledgeDocument.is_core.is_(True),
                                              (KnowledgeDocument.company_id == cid) | (KnowledgeDocument.company_id.is_(None))).count()
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == co.organization_id,
                                              (KnowledgeDocument.company_id == cid) | (KnowledgeDocument.company_id.is_(None))).count()
    out.append(_check(cid, "knowledge", "core_docs", "Có tài liệu cốt lõi (chính sách) trong AGENTS.md", 1.0 if core else 0.0,
                      f"{core} tài liệu cốt lõi, {docs} tài liệu", "training"))
    sop = sum(1 for s in steps if s.sop_id)
    out.append(_check(cid, "knowledge", "sop_steps", "Bước quy trình có SOP", (sop / len(steps)) if steps else 0.0,
                      f"{sop}/{len(steps)} bước có SOP", "processes"))
    from app.services import doc_requirements
    for key, label, val, detail in doc_requirements.readiness_checks(db, co):
        out.append(_check(cid, "documents", key, label, val, detail, "records"))
    rc = db.query(RhythmConfig).filter(RhythmConfig.company_id == cid).first()
    out.append(_check(cid, "rhythm", "rhythm", "Bật giao ban sáng / báo cáo tuần tự động",
                      1.0 if rc and (rc.standup_enabled or rc.weekly_enabled) else 0.0, "đang bật" if rc else "chưa bật", "rhythm"))
    cr = db.query(ComplianceRule).filter(ComplianceRule.company_id == cid).count()
    configured = bool(p and p.compliance)
    out.append(_check(cid, "compliance", "compliance", "Có lịch tuân thủ và đã khai cách kê khai",
                      (0.5 if cr else 0) + (0.5 if configured else 0), f"{cr} nghĩa vụ; cài đặt kê khai: {'có' if configured else 'chưa'}",
                      "compliance"))
    for q in ("documented", "digital", "reviewers"):
        a = answers.get(q)
        label = {"documented": "Quy trình chính đã viết ra", "digital": "Dữ liệu đã số hoá",
                 "reviewers": "Có người duyệt ngoại lệ hằng ngày"}[q]
        out.append(_check(cid, "operations", q, label, ANSWER_SCORE[q].get(a, 0.0) if a else 0.0,
                          "chưa trả lời" if not a else f"trả lời: {a}", "readiness"))
    return out


def lighthouse(db: Session, co: Company, answers: dict) -> dict:
    """Chọn quy trình thí điểm: lặp nhiều × luật rõ × có người làm × đo được, trừ điểm bước dính tiền chưa có luật."""
    procs = db.query(Process).filter(Process.company_id == co.id, Process.status != "archived").all()
    if not procs:
        return {"process_id": None, "name": None, "score": 0,
                "reasons": ["Chưa có quy trình nào — gieo bộ quy trình mẫu ở tab Quy trình rồi chấm lại."],
                "fix_href": _href("processes", co.id)}
    filled = {m.position_id for m in db.query(Member).filter(Member.company_id == co.id, Member.status != "archived").all() if m.position_id}
    rules = {r.action_type for r in db.query(AuthorityRule).filter(AuthorityRule.company_id == co.id, AuthorityRule.enabled.is_(True)).all()}
    since = datetime.utcnow() - timedelta(days=30)
    vol = ANSWER_SCORE["volume"].get(answers.get("volume") or "", 0.5)
    best = None
    for pr in procs:
        steps = db.query(ProcessStep).filter(ProcessStep.process_id == pr.id).all()
        if not steps:
            continue
        n = len(steps)
        runs = db.query(ProcessInstance).filter(ProcessInstance.process_id == pr.id, ProcessInstance.started_at >= since).count()
        freq = min(1.0, 0.5 * vol + 0.5 * min(1.0, runs / 5))
        clear = sum(1 for s in steps if s.sop_id or (s.instructions or "").strip()) / n
        staffed = sum(1 for s in steps if s.position_id in filled) / n
        measured = sum(1 for s in steps if s.expected_minutes) / n
        money = [s for s in steps if s.action_type in MONEY_ACTIONS]
        risk_ok = 1.0 if not money else (0.8 if all(s.action_type in rules for s in money) else 0.3)
        # CSKH (6) / giao hàng (4) có ROI rõ ở doanh nghiệp nhỏ — ưu tiên nhẹ
        roi = 1.0 if pr.category in ("4", "5", "6") else 0.7
        score = round(100 * (0.25 * freq + 0.2 * clear + 0.2 * staffed + 0.15 * measured + 0.1 * risk_ok + 0.1 * roi))
        reasons = [f"tần suất {'cao' if freq >= 0.7 else 'vừa' if freq >= 0.4 else 'thấp'} ({runs} lần chạy 30 ngày)",
                   f"{round(clear * 100)}% bước có SOP/hướng dẫn", f"{round(staffed * 100)}% bước có người ngồi chức danh",
                   f"{round(measured * 100)}% bước có thời lượng kỳ vọng (đo được chu trình)",
                   ("bước dính tiền đã có luật duyệt" if money and risk_ok >= 0.8 else
                    "bước dính tiền CHƯA có luật duyệt — thêm vào ma trận" if money else "không có bước chi/hoàn tiền")]
        if best is None or score > best["score"]:
            best = {"process_id": pr.id, "name": pr.name, "score": score, "reasons": reasons,
                    "fix_href": _href("processes", co.id),
                    "next_steps": ["Giữ agent ở mức thử việc, người duyệt nhiều trong 2 tuần đầu",
                                   "Chạy quy trình này hằng ngày, theo dõi thời gian chu trình ở tab Quy trình",
                                   "Đặt KPI chu trình + % đúng hạn cho quy trình ở tab KPI"]}
    return best or {"process_id": None, "name": None, "score": 0, "reasons": ["Các quy trình chưa có bước."],
                    "fix_href": _href("processes", co.id)}


def assess(db: Session, org_id: int, company_id: int | None, *, answers: dict | None = None, trigger: str = "manual",
           member_id: int | None = None) -> dict:
    from app.services.company_foundation import _company
    co = _company(db, org_id, company_id, write=True)
    if answers is None:
        prev = (db.query(ReadinessAssessment).filter(ReadinessAssessment.company_id == co.id)
                .order_by(ReadinessAssessment.id.desc()).first())
        answers = dict(prev.answers or {}) if prev else {}
    for q in QUESTIONS:
        v = answers.get(q["key"])
        if v is not None and v not in q["options"]:
            raise _err(422, f"Câu \"{q['key']}\": chọn một trong {', '.join(q['options'])}.")
    goal = (answers.get("goal") or "")[:400]
    cs = checks(db, co, answers)
    layers = []
    for key, label, weight, tab in LAYERS:
        mine = [c for c in cs if c["layer"] == key]
        sc = round(100 * sum(c["score"] for c in mine) / len(mine)) if mine else 0
        layers.append({"key": key, "label": label, "weight": weight, "score": sc, "fix_href": _href(tab, co.id),
                       "todo": sum(1 for c in mine if not c["ok"])})
    total = round(sum(x["score"] * x["weight"] for x in layers) / sum(x["weight"] for x in layers))
    level = next((k, vi) for th, k, vi in LEVELS if total >= th)
    lh = lighthouse(db, co, answers)
    a = ReadinessAssessment(organization_id=org_id, company_id=co.id, trigger=trigger,
                            answers={**{k: v for k, v in answers.items() if k != "goal"}, **({"goal": goal} if goal else {})},
                            score=total, level=level[0], layers=layers, checks=cs, lighthouse=lh, created_by_member_id=member_id)
    db.add(a); db.commit(); db.refresh(a)
    return public(db, a)


def public(db: Session, a: ReadinessAssessment) -> dict:
    prev = (db.query(ReadinessAssessment).filter(ReadinessAssessment.company_id == a.company_id, ReadinessAssessment.id < a.id)
            .order_by(ReadinessAssessment.id.desc()).first())
    return {"id": a.id, "company_id": a.company_id, "trigger": a.trigger, "answers": a.answers or {}, "score": a.score,
            "level": a.level, "level_vi": next((vi for _, k, vi in LEVELS if k == a.level), a.level),
            "previous_score": prev.score if prev else None, "layers": a.layers or [], "checks": a.checks or [],
            "lighthouse": a.lighthouse or {}, "created_at": a.created_at.isoformat() if a.created_at else None}


def latest(db: Session, org_id: int, company_id: int | None) -> dict:
    from app.services.company_foundation import _company
    co = _company(db, org_id, company_id)
    a = db.query(ReadinessAssessment).filter(ReadinessAssessment.company_id == co.id).order_by(ReadinessAssessment.id.desc()).first()
    hist = (db.query(ReadinessAssessment).filter(ReadinessAssessment.company_id == co.id)
            .order_by(ReadinessAssessment.id.desc()).limit(10).all())
    return {"company_id": co.id, "company_name": co.name, "questions": QUESTIONS,
            "assessment": public(db, a) if a else None,
            "history": [{"id": h.id, "score": h.score, "level": h.level, "trigger": h.trigger,
                         "created_at": h.created_at.isoformat() if h.created_at else None} for h in hist]}
