"""M3e — vòng học tài liệu: cờ của agent → MỘT đề xuất (bản nháp) / tài liệu + một thẻ Hộp việc gộp; đề xuất đi đúng đường
duyệt M3a; ban hành → cờ/lỗ hổng nguồn đóng, chạy lại eval (eval_after); 5 lỗ hổng cùng cụm → 1 nháp không chứa tên/SĐT
khách; agent đề xuất qua MCP company_doc_propose; bảng sức khoẻ đúng số; truy hồi: hai câu trượt M3b (freeship, hotline)
đúng top-1 nhờ loại câu trả lời + bỏ cụm hỏi + vector băm không vào RRF — kiểm bằng câu diễn đạt KHÁC bộ eval.
ORM thật trên SQLite, gateway giả."""
from app.models import KnowledgeDocument
from app.models.doc_ingest import DocProposal
from app.models.documents import DocumentFlag, DocumentVersion
from app.models.extended import InboxItem
from app.models.learning import KnowledgeGap
from app.services import doc_feedback, knowledge_hub, retrieval_eval
from app.services.company_mcp import ToolContext, ToolError, _doc_flag, _doc_propose
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env  # noqa: F401  (fixture)
from tests.test_m3a_document_library import _seats
from tests.test_m3b_doc_retrieval import _agent, seed_corpus


def _doc(E, title):
    return E.db.query(KnowledgeDocument).filter(KnowledgeDocument.title == title).one()


def test_retrieval_fixes_hold_on_paraphrases_outside_the_eval_set(E):
    _seats(E); seed_corpus(E)
    ag, am = _agent(E)
    out = retrieval_eval.run(E.db, E.org.id, am)
    # M3b để lại 2 câu trượt; sau M3e: recall@6 1.0, đúng mục 1.0 (SQLite, vector băm, xác định)
    assert out["recall_new"] == 1.0 and out["section_recall_new"] == 1.0, [r for r in out["rows"] if not r["section"]]
    assert out["recall_old"] == 0.879                       # đường cũ không đổi (mốc so sánh)
    held_out = {   # không có trong app/evals/cskh_gom_moc.json
        "Mua bao nhiêu tiền thì được miễn phí ship vậy shop?": ("Chính sách vận chuyển", "Phí vận chuyển"),
        "cho minh xin so dien thoai cua shop": ("Câu hỏi thường gặp của khách", "Giờ mở cửa và liên hệ"),
        "Giao ra tỉnh mất bao lâu?": ("Chính sách vận chuyển", "Thời gian giao"),
        "Đơn bao nhiêu tiền thì được freeship?": ("Chính sách vận chuyển", "Phí vận chuyển"),
        "so hotline cua tiem": ("Câu hỏi thường gặp của khách", "Giờ mở cửa và liên hệ"),
    }
    for q, (title, section) in held_out.items():
        top = knowledge_hub.search(E.db, E.org.id, q, member=am, agent=ag, log_gap=False, track=False)["hits"][0]
        assert (top["title"], top["section"]) == (title, section), (q, top["cite"], top["section"])
    assert knowledge_hub.answer_types("Đơn bao nhiêu tiền thì được freeship?") == ["amount"]
    assert knowledge_hub.answer_types("so hotline cua tiem") == ["phone"]
    assert "so" not in knowledge_hub._tokens(knowledge_hub.strip_question_phrases("so hotline cua tiem"))


def test_flags_become_one_draft_proposal_through_the_m3a_approval_path_and_close_on_publish(E):
    _seats(E); seed_corpus(E)
    ag, am = _agent(E)
    doc = _doc(E, "Chính sách vận chuyển")
    ctx = ToolContext(db=E.db, member=am, agent=ag, scopes=["*"])
    _doc_flag(ctx, {"doc_code": doc.doc_code, "reason": "outdated", "note": "Phí đi tỉnh nay là 50.000đ, không còn 45.000đ"})
    _doc_flag(ctx, {"doc_code": doc.doc_code, "reason": "missing_case", "note": "Chưa nói phí giao hoả tốc cuối tuần"})
    r = E.c.post(f"/api/team/doc-learning/propose?company_id={E.co.id}", headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    props = E.db.query(DocProposal).filter(DocProposal.document_id == doc.id).all()
    assert len(props) == 1 and props[0].kind == "flag" and props[0].status == "open"
    p = props[0]
    v = E.db.get(DocumentVersion, p.version_id)
    assert v.status == "draft" and v.version_no == 2 and "50.000đ" in v.content and "hoả tốc" in v.content
    # running again does not create a second proposal / version
    E.c.post(f"/api/team/doc-learning/propose?company_id={E.co.id}", headers=E.tok("manager"))
    assert E.db.query(DocProposal).filter(DocProposal.document_id == doc.id).count() == 1
    assert E.db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).count() == 2
    assert E.db.query(InboxItem).filter(InboxItem.item_type == "doc_proposal").count() >= 1
    # agents still read v1 until approval
    hit = knowledge_hub.search(E.db, E.org.id, "phí giao đi tỉnh", member=am, agent=ag, log_gap=False)["hits"][0]
    assert "45.000đ" in hit["content"]
    # editor fixes the draft, submits; M3a matrix (policy = high risk → owner) approves → published
    fixed = v.content.split("## [Cần bổ sung]")[0].replace("45.000đ đi tỉnh", "50.000đ đi tỉnh").strip()
    assert E.c.patch(f"/api/team/docs/{doc.id}/versions/{v.id}", json={"content": fixed}, headers=E.tok("owner")).status_code == 200
    s = E.c.post(f"/api/team/docs/{doc.id}/versions/{v.id}/submit", headers=E.tok("manager"))
    assert s.status_code == 200, s.text
    # (lỗi test, sửa 2026-10-16: "status" trong phản hồi submit là trạng thái TÀI LIỆU — v1 đã ban hành nên luôn
    # "published"; phiên bản mới đã ban hành hay chưa nằm ở "published")
    if not s.json().get("published"):
        d = E.c.post(f"/api/team/docs/{doc.id}/versions/{v.id}/decide", json={"decision": "approved"}, headers=E.tok("owner"))
        assert d.status_code == 200, d.text
    E.db.expire_all()
    p = E.db.get(DocProposal, p.id)
    assert p.status == "published" and p.eval_pending
    assert {f.status for f in E.db.query(DocumentFlag).filter(DocumentFlag.document_id == doc.id)} == {"resolved"}
    hit = knowledge_hub.search(E.db, E.org.id, "phí giao đi tỉnh", member=am, agent=ag, log_gap=False)["hits"][0]
    assert "50.000đ" in hit["content"]
    # re-run eval → eval_after recorded on the proposal
    ev = E.c.post(f"/api/team/doc-learning/eval?company_id={E.co.id}", headers=E.tok("manager")).json()
    assert ev["status"] == "ok" and ev["recall"] == 1.0
    E.db.expire_all()
    p = E.db.get(DocProposal, p.id)
    assert not p.eval_pending and p.eval_after["recall"] == 1.0


def test_gap_cluster_becomes_one_draft_without_customer_pii(E):
    _seats(E); seed_corpus(E)
    ag, am = _agent(E)
    qs = ["Chị Lan 0912345678 hỏi tiệm có xuất hoá đơn đỏ cho đơn lẻ không?",
          "khách Minh Anh hỏi có xuất hóa đơn đỏ cho đơn lẻ được không, email minhanh@gmail.com",
          "xuất hoá đơn đỏ cho đơn lẻ có được không",
          "anh Tuấn 0987654321 cần xuất hoá đơn đỏ cho đơn lẻ",
          "shop có xuất hoá đơn đỏ đơn lẻ không ạ"]   # (sửa dữ liệu test: bản cũ cùng bộ từ khoá với câu 3 → record_gap
    # gộp đúng thành 1 dòng count=2, nên "5 dòng mở" là giả định sai của test, không phải lỗi code)
    for q in qs:
        knowledge_hub.record_gap(E.db, E.org.id, am.id, q, source="search")
    assert E.db.query(KnowledgeGap).filter(KnowledgeGap.status == "open").count() == 5
    made = doc_feedback.propose_from_gaps(E.db, E.org.id, E.co.id)
    assert len(made) == 1, [m.title for m in made]
    p = made[0]
    v = E.db.get(DocumentVersion, p.version_id)
    for pii in ("0912345678", "0987654321", "minhanh@gmail.com", "Lan", "Tuấn", "Minh Anh"):
        assert pii not in v.content and pii not in (p.title + p.rationale), pii
    assert "hoá đơn đỏ" in v.content.lower() or "hóa đơn đỏ" in v.content.lower()
    assert v.status == "draft" and len(p.source_refs["gaps"]) == 5
    # a second run does not duplicate the cluster
    assert doc_feedback.propose_from_gaps(E.db, E.org.id, E.co.id) == []
    dash = E.c.get(f"/api/team/doc-learning?company_id={E.co.id}", headers=E.tok("member")).json()
    assert dash["proposals"]["open"] == 1 and dash["gaps"]["open"] == 5 and dash["gaps"]["closed_by_docs"] == 0
    assert dash["kpi"]["published_docs"] == 8 and dash["kpi"]["doc_freshness_rate"] == 1.0
    assert dash["kpi"]["knowledge_gap_rate"] is None          # chưa có bộ đếm lượt tra — không bịa


def test_agent_propose_tool_creates_a_draft_and_rejection_closes_it(E):
    _seats(E); seed_corpus(E)
    ag, am = _agent(E)
    doc = _doc(E, "Câu hỏi thường gặp của khách")
    ctx = ToolContext(db=E.db, member=am, agent=ag, scopes=["*"])
    new = doc.content.replace("8:00–21:00", "8:30–21:30")
    out = _doc_propose(ctx, {"doc_code": doc.doc_code, "content": new, "note": "Tiệm đổi giờ mở cửa từ tháng 11"})
    assert out["draft_version"] == 2
    try:
        _doc_propose(ctx, {"doc_code": doc.doc_code, "content": new, "note": "lần 2"})
        raise AssertionError("second open proposal must be refused")
    except ToolError as exc:
        assert exc.code == "conflict"
    E.db.refresh(doc)
    assert "8:00–21:00" in doc.content                         # chưa duyệt → agent vẫn đọc bản cũ
    p = E.db.get(DocProposal, out["proposal_id"])
    v = E.db.get(DocumentVersion, p.version_id)
    E.c.post(f"/api/team/docs/{doc.id}/versions/{v.id}/submit", headers=E.tok("manager"))
    E.db.refresh(v)
    if v.status == "in_review":
        r = E.c.post(f"/api/team/docs/{doc.id}/versions/{v.id}/decide", json={"decision": "rejected", "note": "chưa chốt"},
                     headers=E.tok("owner"))
        assert r.status_code == 200, r.text
        E.db.expire_all()
        assert E.db.get(DocProposal, p.id).status == "rejected"


def test_eval_misses_feed_the_gap_loop(E, monkeypatch):
    _seats(E); seed_corpus(E)
    ag, am = _agent(E)
    real = retrieval_eval.run

    def fake(db, org_id, member, **kw):    # mô phỏng corpus thiếu: 2 câu trượt
        out = real(db, org_id, member, **kw)
        for r in out["rows"][:2]:
            r["new"] = False
        return out
    monkeypatch.setattr(retrieval_eval, "run", fake)
    ev = doc_feedback.run_eval(E.db, E.org.id, E.co.id)
    assert ev["status"] == "ok" and len(ev["misses"]) == 2
    gaps = E.db.query(KnowledgeGap).filter(KnowledgeGap.source == "eval").all()
    assert len(gaps) == 2 and all(g.member_id == am.id for g in gaps)
