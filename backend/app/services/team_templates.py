"""M2 — 3 mẫu công ty (shop, agency, kế toán) và nhập sơ đồ từ CSV.

Mẫu dựng qua ``provisioning.provision_company`` (mỗi agent → ``runtime.create_agent``
trên gateway thật), rồi gán trưởng phòng + quản lý: nhân viên → trưởng phòng →
Giám đốc (trưởng Ban điều hành)."""
from __future__ import annotations

import csv
import io
import re
import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, Company, Department, Invitation, Member, User, UserOrganizationAccess
from app.core.authz import Principal
from app.services import provisioning
from app.services.team import _bump, create_invitation, set_department_head, slug_ascii, would_cycle

EXEC = "Ban điều hành"


def _a(name, slug, role, prompt):
    return {"name": name, "slug": slug, "role": role, "system_prompt": prompt}


TEMPLATES: dict[str, dict] = {
    "shop": {
        "name": "Cửa hàng online", "industry": "Bán lẻ / thương mại điện tử",
        "description": "Shop bán hàng đa kênh: chốt đơn, chăm sóc khách, kho vận, nội dung quảng cáo.",
        "departments": [
            {"name": EXEC, "guide": "Giám đốc đặt mục tiêu tuần, duyệt chi tiêu và điều phối các phòng.",
             "head": _a("Giám đốc cửa hàng", "giam-doc", "Giám đốc", "Bạn điều hành cửa hàng online, đặt mục tiêu doanh thu và điều phối các trưởng phòng.")},
            {"name": "Bán hàng & CSKH", "guide": "Đơn mới và hỏi giá → nhân viên CSKH; khiếu nại/hoàn tiền → trưởng phòng.",
             "head": _a("Trưởng phòng bán hàng", "truong-ban-hang", "Trưởng phòng bán hàng", "Bạn quản lý chốt đơn và chăm sóc khách hàng."),
             "staff": [_a("Nhân viên CSKH", "cskh", "Chăm sóc khách hàng", "Bạn trả lời khách, tư vấn sản phẩm, xác nhận đơn.")]},
            {"name": "Kho vận", "guide": "Đóng gói, giao vận, tồn kho; báo hết hàng cho Giám đốc.",
             "head": _a("Trưởng kho", "truong-kho", "Trưởng kho vận", "Bạn quản lý tồn kho, đóng gói và giao vận.")},
            {"name": "Marketing", "guide": "Bài đăng, quảng cáo, khuyến mãi → nhân viên nội dung; ngân sách ads → trưởng phòng.",
             "head": _a("Trưởng phòng marketing", "truong-marketing", "Trưởng phòng marketing", "Bạn lập kế hoạch marketing và ngân sách quảng cáo."),
             "staff": [_a("Nhân viên nội dung", "noi-dung", "Viết nội dung & ảnh sản phẩm", "Bạn viết mô tả sản phẩm, bài đăng mạng xã hội.")]},
        ],
    },
    "agency": {
        "name": "Agency marketing", "industry": "Dịch vụ marketing / quảng cáo",
        "description": "Agency nhận brief khách, làm sáng tạo và chạy quảng cáo theo hợp đồng.",
        "departments": [
            {"name": EXEC, "guide": "Giám đốc nhận hợp đồng mới, phân bổ nguồn lực, duyệt báo giá.",
             "head": _a("Giám đốc agency", "giam-doc", "Giám đốc", "Bạn điều hành agency, chốt hợp đồng và phân bổ đội.")},
            {"name": "Khách hàng (Account)", "guide": "Brief, báo cáo, phản hồi khách → trưởng account.",
             "head": _a("Trưởng nhóm account", "truong-account", "Trưởng nhóm account", "Bạn làm việc với khách, nhận brief và báo cáo kết quả.")},
            {"name": "Sáng tạo", "guide": "Ý tưởng, kịch bản → giám đốc sáng tạo; thiết kế banner/video → nhà thiết kế.",
             "head": _a("Giám đốc sáng tạo", "giam-doc-sang-tao", "Giám đốc sáng tạo", "Bạn phát triển ý tưởng chiến dịch và duyệt sản phẩm sáng tạo."),
             "staff": [_a("Nhà thiết kế", "thiet-ke", "Thiết kế đồ hoạ", "Bạn thiết kế banner, ảnh và video ngắn theo brief.")]},
            {"name": "Quảng cáo (Media)", "guide": "Lên/tối ưu chiến dịch → chuyên viên ads; phân bổ ngân sách → trưởng media.",
             "head": _a("Trưởng nhóm media", "truong-media", "Trưởng nhóm media", "Bạn lập kế hoạch media và phân bổ ngân sách quảng cáo."),
             "staff": [_a("Chuyên viên chạy ads", "chay-ads", "Chạy quảng cáo", "Bạn dựng và tối ưu chiến dịch Facebook/Google Ads.")]},
        ],
    },
    "ketoan": {
        "name": "Văn phòng kế toán", "industry": "Dịch vụ kế toán / thuế",
        "description": "Dịch vụ kế toán trọn gói: sổ sách, khai thuế, lương & bảo hiểm cho doanh nghiệp nhỏ.",
        "departments": [
            {"name": EXEC, "guide": "Giám đốc nhận khách hàng mới, ký báo cáo và chịu trách nhiệm hồ sơ.",
             "head": _a("Giám đốc văn phòng", "giam-doc", "Giám đốc", "Bạn điều hành văn phòng kế toán và duyệt hồ sơ trước khi nộp.")},
            {"name": "Kế toán tổng hợp", "guide": "Hạch toán chứng từ → kế toán viên; báo cáo tài chính → kế toán trưởng.",
             "head": _a("Kế toán trưởng", "ke-toan-truong", "Kế toán trưởng", "Bạn kiểm soát sổ sách và lập báo cáo tài chính."),
             "staff": [_a("Kế toán viên", "ke-toan-vien", "Hạch toán chứng từ", "Bạn nhập chứng từ, đối chiếu công nợ và ngân hàng.")]},
            {"name": "Thuế", "guide": "Tờ khai GTGT, TNCN, TNDN và quyết toán năm.",
             "head": _a("Trưởng nhóm thuế", "truong-thue", "Trưởng nhóm thuế", "Bạn lập và kiểm tra tờ khai thuế đúng hạn.")},
            {"name": "Lương & bảo hiểm", "guide": "Bảng lương, BHXH, hợp đồng lao động.",
             "head": _a("Trưởng nhóm lương", "truong-luong", "Trưởng nhóm lương & BHXH", "Bạn tính lương và làm hồ sơ bảo hiểm xã hội.")},
        ],
    },
}


def list_templates() -> list[dict]:
    out = []
    for key, t in TEMPLATES.items():
        deps = [{"name": d["name"], "head": d["head"]["name"],
                 "staff": [s["name"] for s in d.get("staff", [])]} for d in t["departments"]]
        out.append({"key": key, "name": t["name"], "industry": t["industry"], "description": t["description"],
                    "departments": deps, "agents": sum(1 + len(d.get("staff", [])) for d in t["departments"])})
    return out


def _unique_prefix(db: Session, key: str) -> str:
    for _ in range(20):
        prefix = f"{key}-{secrets.token_hex(2)}"
        if not db.query(Agent).filter(Agent.runtime_agent_id.like(prefix + "-%")).first():
            return prefix
    raise HTTPException(500, "Không sinh được mã agent duy nhất")


def build_manifest(db: Session, key: str, model: str = "") -> tuple[dict, dict]:
    t = TEMPLATES.get(key)
    if not t:
        raise HTTPException(404, "Không có mẫu này")
    prefix = _unique_prefix(db, key)
    roles: dict[str, dict] = {}  # runtime_agent_id → {dept, head}
    departments = []
    for d in t["departments"]:
        agents = []
        for i, spec in enumerate([d["head"], *d.get("staff", [])]):
            rid = f"{prefix}-{spec['slug']}"
            roles[rid] = {"dept": d["name"], "head": i == 0}
            agents.append({"name": spec["name"], "role": spec["role"], "runtime_agent_id": rid,
                           "system_prompt": spec["system_prompt"], "model": model})
        departments.append({"name": d["name"], "access_level": "restricted", "agents": agents})
    return {"industry": t["industry"], "departments": departments}, roles


async def create_from_template(db: Session, principal: Principal, org_id: int, key: str, company_name: str,
                               model: str = "") -> dict:
    t = TEMPLATES.get(key)
    if not t:
        raise HTTPException(404, "Không có mẫu này")
    name = (company_name or t["name"]).strip()
    manifest, roles = build_manifest(db, key, model)
    job = await provisioning.provision_company(db, organization_id=org_id, company_name=name, industry=t["industry"],
                                               manifest=manifest, requested_by_user_id=principal.user_id)
    if not job.company_id:
        raise HTTPException(502, f"Dựng công ty thất bại: {job.error or job.status}")
    company = db.get(Company, job.company_id)
    depts = {d.name: d for d in db.query(Department).filter(Department.company_id == company.id).all()}
    guides = {d["name"]: d.get("guide", "") for d in t["departments"]}
    by_rid = {a.runtime_agent_id: a for a in db.query(Agent).filter(Agent.runtime_agent_id.in_(list(roles))).all()}
    heads: dict[str, Member] = {}
    for rid, info in roles.items():
        ag = by_rid.get(rid)
        if ag and info["head"]:
            heads[info["dept"]] = db.get(Member, ag.member_id)
    actor = f"user:{principal.user_id}"
    for dname, dept in depts.items():
        dept.guide = guides.get(dname, ""); db.add(dept)
    db.commit()
    director = heads.get(EXEC)
    for dname, dept in depts.items():
        head = heads.get(dname)
        if head is None:
            continue
        if director is not None and head.id != director.id:
            head.manager_id = director.id; _bump(head); db.add(head); db.commit()
        set_department_head(db, org_id, dept, head.id, actor=actor)
    issues = []
    for rid, ag in by_rid.items():
        if ag.lifecycle != "active":
            j = db.query(provisioning.AgentProvisioningJob).filter(
                provisioning.AgentProvisioningJob.agent_id == ag.id).order_by(provisioning.AgentProvisioningJob.id.desc()).first()
            issues.append({"runtime_agent_id": rid, "lifecycle": ag.lifecycle, "hint": (j.error if j else "")})
    return {"company_id": company.id, "company_name": company.name, "template": key, "job_id": job.id,
            "job_status": job.status, "departments": len(depts), "agents": len(by_rid),
            "agents_bound": len(by_rid) - len(issues), "runtime_issues": issues}


# --------------------------------------------------------------------- CSV

HEADER_ALIASES = {
    "name": "name", "ten": "name", "ho ten": "name", "ho va ten": "name",
    "type": "type", "loai": "type",
    "role": "role", "chuc danh": "role", "vai tro": "role", "title": "role",
    "department": "department", "phong ban": "department", "phong": "department",
    "manager": "manager", "quan ly": "manager", "bao cao cho": "manager",
    "email": "email",
    "is head": "is_head", "head": "is_head", "truong phong": "is_head", "la truong phong": "is_head",
}
TYPE_ALIASES = {"human": "human", "nguoi": "human", "person": "human", "nhan vien": "human",
                "agent": "agent", "ai": "agent", "bot": "agent"}
TRUTHY = {"1", "x", "yes", "y", "true", "co", "truong phong", "head"}
MAX_ROWS = 500


def _key(v: str) -> str:
    return slug_ascii(v, 200).replace("-", " ")


def _parse(csv_text: str) -> tuple[list[dict], list[str]]:
    text = (csv_text or "").lstrip("\ufeff")
    if not text.strip():
        raise HTTPException(422, "File CSV rỗng")
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    header = [HEADER_ALIASES.get(_key(h)) for h in rows[0]]
    if "name" not in header:
        raise HTTPException(422, "CSV cần cột name (hoặc 'tên')")
    unknown = [rows[0][i] for i, h in enumerate(header) if h is None and rows[0][i].strip()]
    out = []
    for n, raw in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in raw):
            continue
        rec = {"line": n}
        for i, h in enumerate(header):
            if h and i < len(raw):
                rec[h] = raw[i].strip()
        out.append(rec)
    if len(out) > MAX_ROWS:
        raise HTTPException(422, f"Tối đa {MAX_ROWS} dòng mỗi lần nhập")
    return out, unknown


async def import_csv(db: Session, principal: Principal, org_id: int, company_id: int, csv_text: str,
                     dry_run: bool = True) -> dict:
    company = db.get(Company, company_id)
    if not company or company.organization_id != org_id:
        raise HTTPException(404, "Không thấy công ty")
    recs, unknown = _parse(csv_text)
    existing = {m.name.casefold(): m for m in db.query(Member).filter(Member.company_id == company.id).all()}
    depts = {d.name.casefold(): d for d in db.query(Department).filter(Department.company_id == company.id).all()}
    names: dict[str, dict] = {}
    rows = []
    for r in recs:
        errs, warns = [], []
        name = r.get("name", "")
        if not name:
            errs.append("thiếu tên")
        elif name.casefold() in names:
            errs.append(f"trùng tên với dòng {names[name.casefold()]['line']}")
        typ_raw = r.get("type", "") or ("human" if r.get("email") else "agent")
        typ = TYPE_ALIASES.get(_key(typ_raw))
        if typ is None:
            errs.append(f"loại '{typ_raw}' không hợp lệ (human/agent)")
        ex = existing.get(name.casefold()) if name else None
        if ex is not None and typ and ex.member_type != typ:
            errs.append(f"đã có '{ex.name}' nhưng là {ex.member_type}")
        email = (r.get("email") or "").strip().lower()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errs.append("email không hợp lệ")
        if email and typ == "agent":
            warns.append("agent không cần email — bỏ qua")
            email = ""
        dept = r.get("department", "")
        is_head = _key(r.get("is_head", "")) in TRUTHY
        if is_head and not dept:
            errs.append("trưởng phòng phải có phòng ban")
        row = {"line": r["line"], "name": name, "type": typ, "role": r.get("role", ""), "department": dept,
               "manager": r.get("manager", ""), "email": email, "is_head": is_head,
               "action": "update" if ex is not None else "create", "member_id": ex.id if ex else None,
               "department_new": bool(dept) and dept.casefold() not in depts, "errors": errs, "warnings": warns}
        rows.append(row)
        if name and name.casefold() not in names:
            names[name.casefold()] = row
    # quản lý + trưởng phòng
    head_of: dict[str, dict] = {}
    for row in rows:
        mgr = row["manager"]
        if mgr:
            if mgr.casefold() == row["name"].casefold():
                row["errors"].append("không thể tự quản lý chính mình")
            elif mgr.casefold() not in names and mgr.casefold() not in existing:
                row["errors"].append(f"không thấy người quản lý '{mgr}'")
        if row["is_head"]:
            k = row["department"].casefold()
            if k in head_of:
                row["errors"].append(f"phòng '{row['department']}' đã có trưởng phòng ở dòng {head_of[k]['line']}")
            else:
                head_of[k] = row
    # vòng quản lý trên đồ thị sau khi nhập
    graph = {m.name.casefold(): (m.manager_id, m) for m in existing.values()}
    id_to_name = {m.id: m.name.casefold() for m in existing.values()}
    parent = {k: id_to_name.get(v[0]) for k, v in graph.items()}
    for row in rows:
        if row["name"] and names.get(row["name"].casefold()) is row:   # dòng trùng tên không ghi đè
            parent[row["name"].casefold()] = row["manager"].casefold() if row["manager"] else None
    for row in rows:
        if not row["name"]:
            continue
        seen, cur = set(), parent.get(row["name"].casefold())
        while cur is not None and cur not in seen:
            if cur == row["name"].casefold():
                row["errors"].append("tạo vòng quản lý"); break
            seen.add(cur); cur = parent.get(cur)
    errors = sum(1 for r in rows if r["errors"])
    summary = {
        "rows": len(rows), "errors": errors,
        "create": sum(1 for r in rows if r["action"] == "create" and not r["errors"]),
        "update": sum(1 for r in rows if r["action"] == "update" and not r["errors"]),
        "departments_new": sorted({r["department"] for r in rows if r["department_new"]}),
        "invitations": sum(1 for r in rows if r["email"] and r["type"] == "human" and not r["errors"]),
        "agents": sum(1 for r in rows if r["type"] == "agent" and r["action"] == "create" and not r["errors"]),
    }
    report = {"dry_run": dry_run, "ok": errors == 0, "company_id": company.id, "summary": summary,
              "rows": rows, "ignored_columns": unknown, "invitations": [], "runtime_issues": []}
    if dry_run or errors:
        if not dry_run:
            report["applied"] = False
        return report

    # ---- áp dụng
    actor = f"user:{principal.user_id}"
    for r in rows:
        if r["department"] and r["department_new"] and r["department"].casefold() not in depts:
            d = Department(company_id=company.id, name=r["department"], access_level="restricted")
            db.add(d); db.commit(); db.refresh(d); depts[d.name.casefold()] = d
    made: dict[str, Member] = dict(existing)
    prefix = f"csv-{secrets.token_hex(2)}"
    for r in rows:
        dept = depts.get(r["department"].casefold()) if r["department"] else None
        if r["action"] == "update":
            m = existing[r["name"].casefold()]
            if r["role"]:
                m.role = r["role"]
            if dept is not None:
                m.department_id = dept.id
            _bump(m); db.add(m); db.commit()
        elif r["type"] == "agent":
            job = await provisioning.provision_agent(
                db, organization_id=org_id, company_id=company.id, department_id=dept.id if dept else None,
                name=r["name"], role=r["role"] or "Nhân sự AI",
                runtime_agent_id=f"{prefix}-{slug_ascii(r['name'])}", requested_by_user_id=principal.user_id)
            m = db.get(Member, job.member_id) if job.member_id else None
            if m is None:
                report["runtime_issues"].append({"name": r["name"], "error": job.error or job.status}); continue
            if job.status != "ready":
                report["runtime_issues"].append({"name": r["name"], "status": job.status, "error": job.error})
        else:
            m = Member(organization_id=org_id, company_id=company.id, department_id=dept.id if dept else None,
                       name=r["name"], member_type="human", role=r["role"], status="active")
            db.add(m); db.commit(); db.refresh(m)
        made[r["name"].casefold()] = m
        r["member_id"] = m.id
    for r in rows:
        m = made.get(r["name"].casefold())
        mgr = made.get(r["manager"].casefold()) if r["manager"] else None
        if m is not None and mgr is not None and m.manager_id != mgr.id and not would_cycle(db, m.id, mgr.id):
            m.manager_id = mgr.id; _bump(m); db.add(m); db.commit()
    for k, r in head_of.items():
        m = made.get(r["name"].casefold())
        if m is not None and k in depts:
            set_department_head(db, org_id, depts[k], m.id, actor=actor)
    for r in rows:
        if r["type"] != "human" or not r["email"]:
            continue
        m = made.get(r["name"].casefold())
        user = db.query(User).filter(User.email == r["email"]).first()
        acc = db.query(UserOrganizationAccess).filter(UserOrganizationAccess.user_id == user.id,
                                                      UserOrganizationAccess.organization_id == org_id,
                                                      UserOrganizationAccess.status == "active").first() if user else None
        if acc is not None:
            if user.member_id is None and m is not None and not db.query(User).filter(User.member_id == m.id).first():
                user.member_id = m.id; db.add(user); db.commit()
            r["warnings"].append("đã có tài khoản trong tổ chức — gắn vào ghế")
            continue
        if m is not None and db.query(User).filter(User.member_id == m.id).first():
            continue
        try:
            inv, raw = create_invitation(db, principal, org_id, email=r["email"], role="member",
                                         display_name=r["name"], job_title=r["role"], company_id=company.id,
                                         member_id=m.id if m else None)
            report["invitations"].append({"email": r["email"], "name": r["name"], "token": raw, "id": inv.id})
        except HTTPException as exc:
            r["warnings"].append(f"không tạo được lời mời: {exc.detail}")
    report["applied"] = True
    return report
