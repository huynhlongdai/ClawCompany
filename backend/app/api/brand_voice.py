"""Giọng thương hiệu (văn bản + giọng nói) — Công ty › Pháp nhân & quản trị › Giọng thương hiệu.
Vai trò (R1): xem = member/viewer; soạn nháp, gửi duyệt, cấu hình giọng nói, nghe thử = manager; ban hành/từ chối, cài
đặt cưỡng chế = admin (chủ / quản trị công ty). Khai trong company_guard.AWARE."""
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_company_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.services import brand_voice as bv

router = APIRouter(prefix="/team", tags=["brand-voice"])


def _resync(background: BackgroundTasks, principal: Principal, org_id: int, company_id: int, db: Session) -> None:
    """Ban hành → sinh lại AGENTS.md mọi seat của tổ chức + ghế đang được công ty này cho thuê (sàn đổi)."""
    from app.api.team import _resync as team_resync
    team_resync(background, principal, org_id, None)
    from app.models.leases import SeatLease
    from app.services import seat_leases
    for ls in db.query(SeatLease).filter(SeatLease.provider_company_id == company_id,
                                         SeatLease.status.in_(("active", "suspended"))).all():
        seat_leases._resync_later(ls)


@router.get("/brand-voice")
def get_voice(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")),
              db: Session = Depends(get_db)):
    return bv.overview(db, active_org(principal), company_id)


@router.put("/brand-voice/draft")
def save_draft(payload: dict, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    return bv.save_draft(db, active_org(principal), principal, payload)


@router.get("/brand-voice/versions/{version_id}")
def get_version(version_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    return bv.get_version(db, active_org(principal), version_id)


@router.post("/brand-voice/versions/{version_id}/submit")
def submit(version_id: int, payload: dict | None = None, principal: Principal = Depends(require_company_role("manager")),
           db: Session = Depends(get_db)):
    return bv.submit(db, active_org(principal), principal, version_id, (payload or {}).get("note", ""))


@router.post("/brand-voice/versions/{version_id}/discard")
def discard(version_id: int, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    return bv.discard(db, active_org(principal), version_id)


@router.post("/brand-voice/versions/{version_id}/decide")
def decide(version_id: int, payload: dict, background: BackgroundTasks,
           principal: Principal = Depends(require_company_role("admin")), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    out, published = bv.decide(db, org_id, principal, version_id, str(payload.get("decision") or ""), str(payload.get("note") or ""))
    if published:
        v = db.get(bv.BrandVoice, version_id)
        _resync(background, principal, org_id, v.company_id, db)
    return {**out, "core_sync": published}


@router.put("/brand-voice/settings")
def save_settings(payload: dict, principal: Principal = Depends(require_company_role("admin")), db: Session = Depends(get_db)):
    return bv.save_settings(db, active_org(principal), principal, payload)


@router.post("/brand-voice/check")
def check(payload: dict, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    return bv.try_text(db, active_org(principal), payload)


@router.get("/brand-voice/checks")
def checks(company_id: int | None = None, limit: int = 30, principal: Principal = Depends(require_company_role("member")),
           db: Session = Depends(get_db)):
    return bv.recent_checks(db, active_org(principal), company_id, limit)


@router.post("/brand-voice/selftest")
def selftest(payload: dict, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    """Kiểm bộ quy tắc trên chính các ví dụ (bản nháp gửi lên hoặc bản ban hành)."""
    if payload.get("spec") is not None:
        bv._company(db, active_org(principal), payload.get("company_id"))
        return bv.selftest(bv.clean_spec(payload["spec"]))
    ov = bv.overview(db, active_org(principal), payload.get("company_id"))
    return ov["example_check"] or {"examples": [], "all_ok": False, "good_pass": 0, "bad_caught": 0, "total": 0}


@router.post("/brand-voice/eval-suite")
def eval_suite(payload: dict, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    return bv.ensure_eval_suite(db, active_org(principal), payload.get("company_id"))


@router.get("/brand-voice/agent-view/{agent_id}")
def agent_view(agent_id: int, channel: str = "", principal: Principal = Depends(require_company_role("member")),
               db: Session = Depends(get_db)):
    """Đúng thứ agent nhận (tool company_doc_get VOICE) + phần giọng trong AGENTS.md của ghế."""
    from app.models import Agent, Member
    from app.core import company_scope
    ag = db.get(Agent, agent_id)
    m = db.get(Member, ag.member_id) if ag else None
    if m is None or m.organization_id != active_org(principal):
        raise bv._err(404, "not_found", "Không thấy agent.")
    company_scope.check(m.company_id)
    return {"agent_id": agent_id, "name": m.name, "tool": bv.agent_view(db, m, channel), "core": bv.core_block(db, m.company_id)}


@router.get("/voice-profile")
def get_profile(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")),
                db: Session = Depends(get_db)):
    return bv.get_profile(db, active_org(principal), company_id)


@router.put("/voice-profile")
def save_profile(payload: dict, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    return bv.save_profile(db, active_org(principal), principal, payload)


@router.post("/voice-profile/preview")
def preview(payload: dict, principal: Principal = Depends(require_company_role("manager")), db: Session = Depends(get_db)):
    return bv.preview(db, active_org(principal), principal, payload)


@router.post("/voice-profile/spoken-text")
def spoken_text(payload: dict, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    """Văn bản sau khi áp từ điển phát âm (không gọi TTS, không tốn quota)."""
    co = bv._company(db, active_org(principal), payload.get("company_id"))
    return {"text": bv.apply_lexicon(str(payload.get("text") or ""), bv._lexicon(db, co.id))}


@router.get("/voice-samples")
def samples(company_id: int | None = None, principal: Principal = Depends(require_company_role("member")),
            db: Session = Depends(get_db)):
    return bv.list_samples(db, active_org(principal), company_id)


@router.get("/voice-samples/{sample_id}/audio")
def sample_audio(sample_id: int, principal: Principal = Depends(require_company_role("member")), db: Session = Depends(get_db)):
    s = bv.sample_audio(db, active_org(principal), sample_id)
    ext = "wav" if "wav" in s.mime else "mp3"
    return Response(content=s.audio, media_type=s.mime,
                    headers={"Content-Disposition": f'inline; filename="voice-sample-{s.id}.{ext}"', "Cache-Control": "private, max-age=3600"})
