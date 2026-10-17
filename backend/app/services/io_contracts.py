"""M2e.3 — hợp đồng dữ liệu vào/ra chuẩn. Spec: docs/m2e-agent-native-company.md (mục M2e.3).

Bài toán: người làm mỗi lần một kiểu (thiếu trường, sai định dạng, quên lý do) → bước sau phải đọc và đoán. Ở công ty
agent, mỗi chức danh / bước quy trình có **hợp đồng**: schema dữ liệu vào, schema kết quả, tiêu chí nghiệm thu.

* Việc sinh từ bước quy trình có hợp đồng → ``task_contracts`` mang **dữ liệu vào** (đầu vào lần chạy + kết quả các
  bước trước) và ảnh chụp schema; brief của việc ghi rõ schema phải nộp.
* Agent nộp kết quả bằng MCP ``company_task_submit_output`` → kiểm máy (tập con JSON Schema + tiêu chí có field).
  Sai → lần nộp bị từ chối với danh sách lỗi; việc đang "Chờ duyệt" bị trả về "Đang làm"; quá ``max_attempts`` lần →
  việc "Bị chặn" + Hộp việc của NGƯỜI theo chuỗi leo thang (chức danh cấp trên → quản lý → trưởng phòng → chủ).
* Lượt chạy kết thúc mà chưa có kết quả đạt chuẩn → tính một lần nộp hỏng ("chưa nộp kết quả") → việc quay lại
  "Cần làm" + đánh thức ghế (``changes_requested``), hoặc leo thang khi hết lượt.
* Agent không tự chuyển việc có hợp đồng sang "Chờ duyệt"/"Xong" khi chưa có kết quả đạt chuẩn (cổng MCP).
  Người (UI/API) vẫn chuyển được — quyết định của người thắng máy.
* Kết quả đạt chuẩn → ``process_step_runs.output_json`` (điều kiện bước sau đọc ``step<N>.output.<trường>``) và
  ``outcome_field`` → ``step<N>.outcome``.
* Tỷ lệ đạt chuẩn = số lần nộp hợp lệ / tổng số lần nộp (cả "chưa nộp") theo ghế / chức danh → KPI
  ``output_conformance_rate`` + scorecard.

Giới hạn thật: kiểm cấu trúc và tiêu chí có field, không chấm được chất lượng nội dung (câu chữ lịch sự, đúng chính
sách) — tiêu chí chỉ có chữ vẫn do người/agent review đọc."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Member, Task
from app.models.agent_native import IoContract, TaskContract, TaskOutput
from app.models.company_foundation import Position

TYPES = ("object", "string", "number", "integer", "boolean", "array", "null")
TYPE_VI = {"object": "đối tượng", "string": "chuỗi", "number": "số", "integer": "số nguyên", "boolean": "đúng/sai",
           "array": "danh sách", "null": "rỗng"}
KEYWORDS = {"type", "properties", "required", "enum", "minimum", "maximum", "minLength", "maxLength", "pattern",
            "items", "minItems", "maxItems", "additionalProperties", "description", "title", "format", "default",
            "examples"}
FORMATS = {"email": r"^[^@\s]+@[^@\s]+\.[^@\s]+$", "date": r"^\d{4}-\d{2}-\d{2}$",
           "date-time": r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", "uri": r"^https?://\S+$"}
MAX_ATTEMPTS = (1, 10)
DEFAULT_MAX_ATTEMPTS = 3
SUBMIT_TOOL = "company_task_submit_output"
OUTCOME_TOOL = "company_process_step_outcome"


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


# ------------------------------------------------------------------ tập con JSON Schema (thuần, test được)

def check_schema(schema, path: str = "") -> list[str]:
    """Lỗi của chính schema (khoá không hỗ trợ, kiểu sai). Rỗng = dùng được."""
    errs: list[str] = []
    if schema is None:
        return errs
    if not isinstance(schema, dict):
        return [f"{path or 'schema'}: phải là một đối tượng JSON"]
    bad = sorted(set(schema) - KEYWORDS)
    if bad:
        errs.append(f"{path or 'schema'}: không hỗ trợ khoá {', '.join(bad)} (dùng: {', '.join(sorted(KEYWORDS))})")
    t = schema.get("type")
    ts = t if isinstance(t, list) else [t] if t else []
    for x in ts:
        if x not in TYPES:
            errs.append(f"{path or 'schema'}: kiểu \"{x}\" không hợp lệ ({', '.join(TYPES)})")
    if "pattern" in schema:
        try:
            re.compile(str(schema["pattern"]))
        except re.error as exc:
            errs.append(f"{path or 'schema'}: pattern lỗi — {exc}")
    if "format" in schema and schema["format"] not in FORMATS:
        errs.append(f"{path or 'schema'}: format chỉ có {', '.join(FORMATS)}")
    if "enum" in schema and not isinstance(schema["enum"], list):
        errs.append(f"{path or 'schema'}: enum phải là danh sách")
    if "required" in schema and not (isinstance(schema["required"], list) and all(isinstance(x, str) for x in schema["required"])):
        errs.append(f"{path or 'schema'}: required phải là danh sách tên trường")
    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict):
            errs.append(f"{path or 'schema'}: properties phải là đối tượng")
        else:
            for k, v in props.items():
                errs += check_schema(v, f"{path}.{k}" if path else k)
            missing = [r for r in schema.get("required") or [] if isinstance(r, str) and r not in props]
            if missing:
                errs.append(f"{path or 'schema'}: required có trường không khai báo: {', '.join(missing)}")
    if isinstance(schema.get("items"), dict):
        errs += check_schema(schema["items"], f"{path}[]")
    return errs


def _type_ok(value, t: str) -> bool:
    if t == "null":
        return value is None
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    return True


def validate(schema: dict | None, value, path: str = "") -> list[dict]:
    """[{path, message}] — rỗng = hợp lệ. Thông báo tiếng Việt để agent đọc và sửa được ngay."""
    if not schema:
        return []
    where = path or "(gốc)"
    out: list[dict] = []
    t = schema.get("type")
    ts = t if isinstance(t, list) else [t] if t else []
    if ts and not any(_type_ok(value, x) for x in ts):
        got = "rỗng" if value is None else TYPE_VI.get({bool: "boolean", int: "integer", float: "number", str: "string",
                                                         list: "array", dict: "object"}.get(type(value), ""), type(value).__name__)
        return [{"path": where, "message": f"phải là {' hoặc '.join(TYPE_VI.get(x, x) for x in ts)}, đang là {got}"}]
    if "enum" in schema and value not in schema["enum"]:
        out.append({"path": where, "message": "chỉ nhận một trong: " + ", ".join(json.dumps(x, ensure_ascii=False) for x in schema["enum"])})
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append({"path": where, "message": f"phải ≥ {schema['minimum']}"})
        if "maximum" in schema and value > schema["maximum"]:
            out.append({"path": where, "message": f"phải ≤ {schema['maximum']}"})
    if isinstance(value, str):
        if "minLength" in schema and len(value.strip()) < schema["minLength"]:
            out.append({"path": where, "message": f"cần ít nhất {schema['minLength']} ký tự (đang {len(value.strip())})"})
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append({"path": where, "message": f"tối đa {schema['maxLength']} ký tự (đang {len(value)})"})
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            out.append({"path": where, "message": f"không đúng mẫu {schema['pattern']}"})
        if schema.get("format") in FORMATS and not re.search(FORMATS[schema["format"]], value):
            out.append({"path": where, "message": f"không đúng định dạng {schema['format']}"})
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append({"path": where, "message": f"cần ít nhất {schema['minItems']} mục"})
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append({"path": where, "message": f"tối đa {schema['maxItems']} mục"})
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(value[:200]):
                out += validate(schema["items"], v, f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for r in schema.get("required") or []:
            v = value.get(r)
            if r not in value or v is None or (isinstance(v, str) and not v.strip()):
                out.append({"path": f"{path}.{r}" if path else r, "message": "bắt buộc, đang thiếu"})
        for k, v in value.items():
            if k in props:
                if v is None and k not in (schema.get("required") or []):
                    continue
                out += validate(props[k], v, f"{path}.{k}" if path else k)
            elif schema.get("additionalProperties") is False:
                out.append({"path": f"{path}.{k}" if path else k, "message": "trường lạ, hợp đồng không có trường này"})
    return out


def _get(value, dotted: str):
    cur = value
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def check_acceptance(acceptance: list | None, output) -> list[dict]:
    """Tiêu chí có field/op → kiểm máy (cùng phép so sánh với điều kiện bước quy trình). Chỉ có chữ → bỏ qua ở đây."""
    from app.services.process_map import eval_condition
    out = []
    for i, c in enumerate(acceptance or []):
        if not isinstance(c, dict) or not c.get("field") or not c.get("op"):
            continue
        ok = eval_condition({"field": "v", "op": c["op"], "value": c.get("value")}, {"v": _get(output, c["field"])})
        if not ok:
            out.append({"path": c["field"], "message": f"không đạt tiêu chí nghiệm thu #{i + 1}: {c.get('text') or ''}".strip()})
    return out


def _clean_acceptance(raw) -> list[dict]:
    from app.services.process_map import CONDITION_OPS
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise _err(422, "Tiêu chí nghiệm thu phải là danh sách, mỗi mục {text, field?, op?, value?}.")
    out = []
    for i, c in enumerate(raw[:20], start=1):
        if isinstance(c, str):
            c = {"text": c}
        if not isinstance(c, dict):
            raise _err(422, f"Tiêu chí #{i} không hợp lệ.")
        text = str(c.get("text") or "").strip()[:300]
        field, op_ = str(c.get("field") or "").strip()[:80], str(c.get("op") or "").strip()
        if not text and not field:
            continue
        item = {"text": text}
        if field or op_:
            if op_ not in CONDITION_OPS:
                raise _err(422, f"Tiêu chí #{i}: phép so sánh \"{op_}\" không hợp lệ ({', '.join(CONDITION_OPS)}).")
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}(\.[A-Za-z0-9_\-]{1,40}){0,3}", field):
                raise _err(422, f"Tiêu chí #{i}: tên trường \"{field}\" không hợp lệ.")
            value = c.get("value")
            if op_ in (">", ">=", "<", "<=") and not isinstance(value, (int, float)):
                try:
                    value = float(str(value))
                except ValueError:
                    raise _err(422, f"Tiêu chí #{i}: phép {op_} cần một con số.") from None
            item.update(field=field, op=op_, value=None if op_ in ("empty", "not_empty") else value)
        out.append(item)
    return out


def describe_fields(schema: dict | None, *, limit: int = 600) -> str:
    """{order_id: chuỗi*, amount_usd: số ≥0*, decision: approve|reject*} — * = bắt buộc."""
    if not schema or not isinstance(schema.get("properties"), dict):
        return "{}"
    req = set(schema.get("required") or [])
    parts = []
    for k, v in schema["properties"].items():
        if not isinstance(v, dict):
            continue
        t = v.get("type")
        d = "|".join(str(x) for x in v["enum"]) if v.get("enum") else TYPE_VI.get(t if isinstance(t, str) else "", str(t or "?"))
        if "minimum" in v:
            d += f" ≥{v['minimum']:g}" if isinstance(v["minimum"], (int, float)) else ""
        if "maximum" in v:
            d += f" ≤{v['maximum']:g}" if isinstance(v["maximum"], (int, float)) else ""
        if v.get("minLength"):
            d += f" ≥{v['minLength']} ký tự"
        parts.append(f"{k}: {d}{'*' if k in req else ''}")
    s = "{" + ", ".join(parts) + "}"
    return s if len(s) <= limit else s[:limit - 2] + "…}"


# ------------------------------------------------------------------ mẫu

def _o(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props),
            "additionalProperties": False}


TEMPLATES = {
    "refund_request": {
        "name": "Đơn hoàn tiền", "description": "Kết quả xử lý một yêu cầu hoàn tiền / đổi trả — bước sau (hoàn tiền, báo khách) "
                                                  "đọc trực tiếp các trường này.",
        "input_schema": _o({"order_id": {"type": "string"}, "amount_usd": {"type": "number", "minimum": 0},
                            "reason": {"type": "string"}}, ["order_id"]),
        "output_schema": _o({"order_id": {"type": "string", "minLength": 3, "description": "Mã đơn"},
                             "amount_usd": {"type": "number", "minimum": 0, "description": "Số tiền đề nghị hoàn (USD)"},
                             "reason": {"type": "string", "minLength": 10, "description": "Lý do, có đối chiếu chính sách"},
                             "decision": {"type": "string", "enum": ["approve", "reject", "escalate"]},
                             "customer_message": {"type": "string", "minLength": 20, "maxLength": 1200,
                                                  "description": "Tin nhắn gửi khách"}}),
        "acceptance": [{"text": "Số tiền đề nghị hoàn lớn hơn 0", "field": "amount_usd", "op": ">", "value": 0},
                       {"text": "Tin nhắn cho khách lịch sự, không hứa hoàn tiền ngoài chính sách"}],
        "outcome_field": "decision"},
    "order_confirm": {
        "name": "Xác nhận đơn hàng", "description": "Đơn đã xác nhận với khách — kho đóng gói theo đúng danh sách này.",
        "input_schema": _o({"order_id": {"type": "string"}}, ["order_id"]),
        "output_schema": _o({"order_id": {"type": "string", "minLength": 3},
                             "customer_name": {"type": "string", "minLength": 2},
                             "items": {"type": "array", "minItems": 1, "items": _o({"sku": {"type": "string"},
                                                                                     "qty": {"type": "integer", "minimum": 1}})},
                             "total_usd": {"type": "number", "minimum": 0},
                             "confirmed": {"type": "boolean"},
                             "note": {"type": "string", "maxLength": 500}}, ["order_id", "customer_name", "items", "total_usd", "confirmed"]),
        "acceptance": [{"text": "Khách đã xác nhận", "field": "confirmed", "op": "==", "value": True}],
        "outcome_field": "confirmed"},
    "product_post": {
        "name": "Bài đăng sản phẩm", "description": "Nội dung một bài đăng sản phẩm mới, đủ để đăng lên kênh bán.",
        "input_schema": _o({"product": {"type": "string"}}, ["product"]),
        "output_schema": _o({"title": {"type": "string", "minLength": 10, "maxLength": 120},
                             "body": {"type": "string", "minLength": 150},
                             "price_usd": {"type": "number", "minimum": 0},
                             "image_urls": {"type": "array", "minItems": 1, "items": {"type": "string", "format": "uri"}},
                             "hashtags": {"type": "array", "items": {"type": "string"}}}, ["title", "body", "price_usd", "image_urls"]),
        "acceptance": [{"text": "Không nêu giá đối thủ, không chê đối thủ"}], "outcome_field": ""},
    "daily_report": {
        "name": "Báo cáo ngày", "description": "Báo cáo cuối ngày/ca của một ghế — cùng một khuôn để gộp được.",
        "input_schema": None,
        "output_schema": _o({"done": {"type": "array", "items": {"type": "string"}},
                             "blockers": {"type": "array", "items": {"type": "string"}},
                             "next": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                             "metrics": {"type": "object"}}, ["done", "blockers", "next"]),
        "acceptance": [], "outcome_field": ""},
}


# ------------------------------------------------------------------ CRUD hợp đồng

def _contract(db: Session, org_id: int, cid: int) -> IoContract:
    c = db.get(IoContract, cid)
    if c is None or c.organization_id != org_id:
        raise _err(404, "Không thấy hợp đồng dữ liệu này. Tải lại tab Hợp đồng dữ liệu.")
    from app.core import company_scope as _cs
    _cs.check(c.company_id)  # R1 vai trò theo công ty
    return c


def _apply(db: Session, c: IoContract, data: dict, fields: set[str]) -> bool:
    """Trả True khi phần ràng buộc (schema/tiêu chí/số lần) đổi → tăng version."""
    before = (c.input_schema, c.output_schema, c.acceptance, c.max_attempts, c.outcome_field)
    if "name" in fields:
        c.name = (data.get("name") or "").strip()[:200]
    if "description" in fields:
        c.description = (data.get("description") or "").strip()[:2000]
    for key in ("input_schema", "output_schema"):
        if key in fields:
            raw = data.get(key)
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw) if raw.strip() else None
                except ValueError as exc:
                    raise _err(422, f"{'Schema vào' if key == 'input_schema' else 'Schema ra'} không phải JSON hợp lệ: {exc}") from exc
            errs = check_schema(raw)
            if errs:
                raise _err(422, f"{'Schema vào' if key == 'input_schema' else 'Schema ra'} không dùng được: " + "; ".join(errs[:5]))
            if raw is not None and raw.get("type") not in (None, "object"):
                raise _err(422, "Schema gốc phải là object (một bộ trường có tên).")
            setattr(c, key, raw or None)
    if "acceptance" in fields:
        c.acceptance = _clean_acceptance(data.get("acceptance"))
    if "max_attempts" in fields:
        n = data.get("max_attempts")
        if not isinstance(n, int) or isinstance(n, bool) or not MAX_ATTEMPTS[0] <= n <= MAX_ATTEMPTS[1]:
            raise _err(422, f"Số lần nộp tối đa phải từ {MAX_ATTEMPTS[0]} tới {MAX_ATTEMPTS[1]}.")
        c.max_attempts = n
    if "outcome_field" in fields:
        c.outcome_field = (data.get("outcome_field") or "").strip()[:80]
    if "position_id" in fields:
        v = data.get("position_id")
        if v is not None:
            p = db.get(Position, v)
            if p is None or p.company_id != c.company_id or p.status == "archived":
                raise _err(422, f"Chức danh #{v} không thuộc công ty này.")
        c.position_id = v
    if "status" in fields and data.get("status") in ("active", "archived"):
        c.status = data["status"]
    if not c.name:
        raise _err(422, "Hợp đồng cần có tên, ví dụ \"Đơn hoàn tiền\".")
    if not c.output_schema or not (c.output_schema.get("properties") or {}):
        raise _err(422, "Hợp đồng cần schema kết quả có ít nhất một trường (chọn một mẫu nếu chưa quen JSON Schema).")
    props = c.output_schema.get("properties") or {}
    if c.outcome_field and c.outcome_field not in props:
        raise _err(422, f"Trường kết quả bước \"{c.outcome_field}\" không có trong schema kết quả.")
    for a in c.acceptance or []:
        if a.get("field") and a["field"].split(".")[0] not in props:
            raise _err(422, f"Tiêu chí \"{a.get('text') or a['field']}\" xét trường {a['field']} không có trong schema kết quả.")
    return before != (c.input_schema, c.output_schema, c.acceptance, c.max_attempts, c.outcome_field)


def public_contract(db: Session, c: IoContract, *, stats: dict | None = None) -> dict:
    from app.models.company_ops import ProcessStep
    pos = db.get(Position, c.position_id) if c.position_id else None
    steps = db.query(ProcessStep).filter(ProcessStep.contract_id == c.id).all()
    return {"id": c.id, "company_id": c.company_id, "position_id": c.position_id, "position": pos.title if pos else None,
            "name": c.name, "description": c.description or "", "input_schema": c.input_schema,
            "output_schema": c.output_schema, "acceptance": c.acceptance or [], "max_attempts": c.max_attempts,
            "outcome_field": c.outcome_field or "", "template_key": c.template_key or "", "version": c.version,
            "status": c.status, "fields": describe_fields(c.output_schema),
            "steps": [{"id": s.id, "process_id": s.process_id, "seq": s.seq, "name": s.name} for s in steps],
            "stats": stats if stats is not None else conformance(db, contract_id=c.id),
            "updated_at": c.updated_at.isoformat() if c.updated_at else None}


def list_contracts(db: Session, org_id: int, company_id: int | None, *, include_archived: bool = False) -> dict:
    from app.services.company_foundation import _company
    co = _company(db, org_id, company_id)
    q = db.query(IoContract).filter(IoContract.company_id == co.id)
    if not include_archived:
        q = q.filter(IoContract.status != "archived")
    rows = q.order_by(IoContract.id).all()
    recent = (db.query(TaskOutput).filter(TaskOutput.company_id == co.id).order_by(TaskOutput.id.desc()).limit(20).all())
    names = {m.id: m.name for m in db.query(Member).filter(Member.company_id == co.id).all()}
    return {"company_id": co.id, "company_name": co.name, "items": [public_contract(db, c) for c in rows],
            "templates": [{"key": k, "name": v["name"], "description": v["description"],
                           "fields": describe_fields(v["output_schema"])} for k, v in TEMPLATES.items()],
            "keywords": sorted(KEYWORDS), "types": list(TYPES),
            "company_rate": conformance(db, company_id=co.id),
            "seats": seat_conformance(db, co.id), "positions": position_conformance(db, co.id),
            "recent": [public_output(o, names) for o in recent]}


def create_contract(db: Session, org_id: int, data: dict) -> IoContract:
    from app.services.company_foundation import _company
    co = _company(db, org_id, data.get("company_id"), write=True)
    key = data.get("template") or ""
    tpl = TEMPLATES.get(key)
    if key and tpl is None:
        raise _err(422, f"Không có mẫu hợp đồng \"{key}\". Chọn một trong: {', '.join(TEMPLATES)}.")
    body = {**copy.deepcopy(tpl or {}), **{k: v for k, v in data.items() if v is not None and k not in ("company_id", "template")}}
    c = IoContract(organization_id=org_id, company_id=co.id, name="", template_key=key if tpl else "",
                   max_attempts=DEFAULT_MAX_ATTEMPTS, version=1, status="active")
    _apply(db, c, body, set(body) & {"name", "description", "input_schema", "output_schema", "acceptance",
                                     "max_attempts", "outcome_field", "position_id"})
    db.add(c); db.commit(); db.refresh(c)
    return c


def update_contract(db: Session, org_id: int, cid: int, data: dict) -> IoContract:
    c = _contract(db, org_id, cid)
    if _apply(db, c, data, set(data)):
        c.version = (c.version or 1) + 1
    db.add(c); db.commit(); db.refresh(c)
    return c


def archive_contract(db: Session, org_id: int, cid: int) -> dict:
    c = _contract(db, org_id, cid)
    c.status = "archived"
    db.commit()
    return {"id": c.id, "status": c.status}


def try_output(db: Session, org_id: int, cid: int, output) -> dict:
    c = _contract(db, org_id, cid)
    errors = _all_errors(c.output_schema, c.acceptance, output)
    return {"valid": not errors, "errors": errors}


def _all_errors(schema, acceptance, output) -> list[dict]:
    if not isinstance(output, dict):
        return [{"path": "(gốc)", "message": "kết quả phải là một đối tượng JSON {trường: giá trị}"}]
    errs = validate(schema, output)
    return errs or check_acceptance(acceptance, output)


def check_step_contract(db: Session, company_id: int, contract_id) -> int | None:
    """Kiểm ``contract_id`` của một bước quy trình (gọi từ ``process_map.save_steps``)."""
    if contract_id in (None, "", 0):
        return None
    c = db.get(IoContract, int(contract_id))
    if c is None or c.company_id != company_id or c.status == "archived":
        raise _err(422, f"Hợp đồng dữ liệu #{contract_id} không thuộc công ty của quy trình (hoặc đã lưu trữ).")
    return c.id


# ------------------------------------------------------------------ hợp đồng của một việc

def task_contract(db: Session, task_id: int) -> TaskContract | None:
    return db.query(TaskContract).filter(TaskContract.task_id == task_id).first()


def attach(db: Session, task: Task, contract: IoContract, *, input_data: dict | None = None,
           step_run_id: int | None = None) -> TaskContract:
    """Gắn hợp đồng vào việc (ảnh chụp schema). Gắn lại khi việc chưa có lần nộp nào → thay; đã nộp → 409."""
    tc = task_contract(db, task.id)
    if tc is not None and tc.attempts:
        raise _err(409, "Việc này đã có lần nộp kết quả theo hợp đồng cũ — không đổi hợp đồng giữa chừng được.")
    if tc is None:
        tc = TaskContract(task_id=task.id)
        db.add(tc)
    tc.contract_id, tc.contract_version, tc.name = contract.id, contract.version or 1, contract.name
    tc.output_schema, tc.acceptance = copy.deepcopy(contract.output_schema), copy.deepcopy(contract.acceptance or [])
    tc.outcome_field, tc.max_attempts = contract.outcome_field or "", contract.max_attempts or DEFAULT_MAX_ATTEMPTS
    tc.step_run_id = step_run_id or tc.step_run_id
    tc.status, tc.attempts, tc.last_errors = "open", 0, None
    set_input(db, tc, contract, input_data, commit=False)
    db.commit(); db.refresh(tc)
    return tc


def set_input(db: Session, tc: TaskContract, contract: IoContract | None, input_data: dict | None, *, commit: bool = True) -> None:
    contract = contract or (db.get(IoContract, tc.contract_id) if tc.contract_id else None)
    tc.input_json = input_data or None
    errs = validate(contract.input_schema, input_data or {}) if contract is not None and contract.input_schema else []
    tc.input_errors = errs or None
    if commit:
        db.commit()


def contract_brief(tc: TaskContract) -> str:
    """Phần "## Hợp đồng dữ liệu" ghi vào mô tả việc."""
    lines = ["## Hợp đồng dữ liệu: " + tc.name,
             f"Nộp kết quả bằng `{SUBMIT_TOOL}` (task_id, output = JSON đúng schema dưới). Sai chuẩn → bị trả làm lại; "
             f"tối đa {tc.max_attempts} lần nộp hỏng thì việc chuyển cho người xử lý. Không chuyển việc sang Chờ duyệt/Xong "
             f"khi chưa nộp kết quả đạt chuẩn.",
             "Trường (* = bắt buộc): " + describe_fields(tc.output_schema, limit=1200)]
    crit = [a.get("text") for a in tc.acceptance or [] if a.get("text")]
    if crit:
        lines.append("Tiêu chí nghiệm thu: " + "; ".join(crit))
    if tc.output_schema:
        lines += ["```json", json.dumps(tc.output_schema, ensure_ascii=False)[:2500], "```"]
    if tc.input_json:
        lines += ["Dữ liệu vào:", "```json", json.dumps(tc.input_json, ensure_ascii=False, indent=1)[:2500], "```"]
    if tc.input_errors:
        lines.append("⚠ Dữ liệu vào thiếu/sai: " + "; ".join(f"{e['path']}: {e['message']}" for e in tc.input_errors[:6])
                     + " — hỏi lại người giao trước khi làm.")
    return "\n".join(lines)


def public_output(o: TaskOutput, names: dict[int, str] | None = None) -> dict:
    return {"id": o.id, "task_id": o.task_id, "contract_id": o.contract_id, "member_id": o.member_id,
            "seat": (names or {}).get(o.member_id or -1), "attempt": o.attempt, "valid": bool(o.valid),
            "errors": o.errors or [], "output": o.output_json, "via": o.via,
            "created_at": o.created_at.isoformat() if o.created_at else None}


def public_task_contract(db: Session, tc: TaskContract | None) -> dict | None:
    if tc is None:
        return None
    outs = db.query(TaskOutput).filter(TaskOutput.task_id == tc.task_id).order_by(TaskOutput.id).all()
    esc = db.get(Member, tc.escalated_to_member_id) if tc.escalated_to_member_id else None
    return {"task_id": tc.task_id, "contract_id": tc.contract_id, "contract_version": tc.contract_version,
            "name": tc.name, "status": tc.status, "attempts": tc.attempts, "max_attempts": tc.max_attempts,
            "fields": describe_fields(tc.output_schema), "output_schema": tc.output_schema,
            "acceptance": tc.acceptance or [], "outcome_field": tc.outcome_field or "",
            "input": tc.input_json, "input_errors": tc.input_errors or [], "last_errors": tc.last_errors or [],
            "step_run_id": tc.step_run_id, "escalated_to": esc.name if esc else None,
            "accepted_output": next((o.output_json for o in outs if o.id == tc.accepted_output_id), None),
            "outputs": [public_output(o) for o in outs]}


def attach_by_id(db: Session, org_id: int, task: Task, contract_id: int, input_data: dict | None) -> dict:
    c = _contract(db, org_id, contract_id)
    from app.models import Project
    pr = db.get(Project, task.project_id) if task.project_id else None
    if pr is None or pr.company_id != c.company_id:
        raise _err(422, "Hợp đồng và việc phải cùng một công ty.")
    if c.status == "archived":
        raise _err(409, "Hợp đồng đã lưu trữ.")
    tc = attach(db, task, c, input_data=input_data)
    block = contract_brief(tc)
    desc = task.description or ""
    marker = "\n\n## Hợp đồng dữ liệu: "
    task.description = (desc.split(marker)[0] if marker in desc else desc) + "\n\n" + block
    db.commit()
    return public_task_contract(db, tc)


# ------------------------------------------------------------------ nộp kết quả

class SubmitError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _company_of(db: Session, task: Task) -> int | None:
    from app.models import Project
    pr = db.get(Project, task.project_id) if task.project_id else None
    return pr.company_id if pr else None


def submit(db: Session, task: Task, member: Member | None, output, *, via: str = "api", run_id: str = "",
           session_key: str = "", forced_error: str = "") -> dict:
    """Một lần nộp. ``forced_error`` = lượt chạy kết thúc mà chưa nộp (tính như một lần nộp hỏng)."""
    from app.services import task_journal
    tc = task_contract(db, task.id)
    if tc is None:
        raise SubmitError(409, "no_contract", f"Việc #{task.id} không có hợp đồng dữ liệu — báo kết quả bằng company_task_comment.")
    if tc.status == "accepted":
        raise SubmitError(409, "already_accepted", "Việc này đã có kết quả đạt chuẩn; không nộp lại.")
    if tc.status == "escalated":
        raise SubmitError(409, "escalated", "Việc này đã chuyển cho người xử lý sau nhiều lần nộp sai chuẩn.")
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            output = {"__raw__": output}
    errors = ([{"path": "(gốc)", "message": forced_error}] if forced_error
              else (_all_errors(tc.output_schema, tc.acceptance, output) if "__raw__" not in (output or {})
                    else [{"path": "(gốc)", "message": "output không phải JSON — gửi một đối tượng {trường: giá trị}"}]))
    # giọng thương hiệu: kết quả đúng schema nhưng văn bản gửi khách lệch giọng → làm lại (cài đặt rework / sàn bên cho thuê)
    vres = None
    if not errors:
        try:
            from app.services import brand_voice
            vres = brand_voice.check_output(db, member, output)
        except Exception as exc:  # noqa: BLE001 — bộ chấm giọng không được làm hỏng đường nộp
            print(f"[brand_voice] check: {exc}"); vres = None
        if vres and vres["action"] == "rework":
            errors = vres["errors"]
    tc.attempts = (tc.attempts or 0) + 1
    o = TaskOutput(organization_id=member.organization_id if member else 0, company_id=_company_of(db, task),
                   task_id=task.id, contract_id=tc.contract_id, member_id=member.id if member else task.assignee_member_id,
                   position_id=getattr(member, "position_id", None) if member else None, attempt=tc.attempts,
                   output_json=None if forced_error else output, valid=not errors, errors=errors or None,
                   via=via[:16], run_id=(run_id or "")[:120], session_key=(session_key or "")[:240])
    if o.organization_id == 0:
        from app.models import Company
        co = db.get(Company, o.company_id) if o.company_id else None
        o.organization_id = co.organization_id if co else 0
    db.add(o); db.flush()
    actor = member.id if member else None
    if vres:
        try:
            from app.services import brand_voice
            brand_voice.after_submit(db, task, member, vres, o.id)
        except Exception as exc:  # noqa: BLE001
            print(f"[brand_voice] record: {exc}")
    if not errors:
        tc.status, tc.accepted_output_id, tc.last_errors = "accepted", o.id, None
        db.commit()
        _to_step(db, tc, output)
        try:
            task_journal.append(db, task, kind="result", outcome="success", actor_member_id=actor,
                                summary=f"Kết quả đạt hợp đồng \"{tc.name}\" (lần {tc.attempts})"[:390],
                                detail=json.dumps(output, ensure_ascii=False, indent=1)[:20000],
                                runtime_run_id=run_id or "", runtime_session_key=session_key or "")
        except Exception as exc:  # noqa: BLE001
            db.rollback(); print(f"[m2e.3] journal: {exc}")
        # trong lượt chạy của agent: lượt kết thúc sẽ tự đưa việc sang Chờ duyệt (không đổi trạng thái giữa lượt,
        # để lượt chạy được đóng + quyết toán đúng đường cũ); nộp từ UI/API → chuyển luôn
        moved = (_move(db, task, "review", f"đã nộp kết quả đạt hợp đồng {tc.name}", actor)
                 if task.status == "in_progress" and via not in ("mcp", "runtime") else None)
        return {"valid": True, "attempt": tc.attempts, "status": "accepted", "task_status": task.status, "moved": moved,
                "message": "Kết quả đạt chuẩn hợp đồng — đã ghi vào sổ việc" + (
                    ", việc chuyển sang Chờ duyệt." if moved else ". Kết thúc lượt: việc sẽ sang Chờ duyệt.")}
    tc.last_errors = errors
    left = (tc.max_attempts or DEFAULT_MAX_ATTEMPTS) - tc.attempts
    db.commit()
    lines = "; ".join(f"{e['path']}: {e['message']}" for e in errors[:8])
    try:
        task_journal.append(db, task, kind="review", outcome="rejected", actor_member_id=None,
                            summary=f"Kết quả sai hợp đồng \"{tc.name}\" (lần {tc.attempts}/{tc.max_attempts})"[:390],
                            detail=lines[:4000], runtime_run_id=run_id or "", runtime_session_key=session_key or "")
    except Exception as exc:  # noqa: BLE001
        db.rollback(); print(f"[m2e.3] journal: {exc}")
    if left <= 0:
        target = escalate(db, task, tc, member, lines)
        return {"valid": False, "attempt": tc.attempts, "status": "escalated", "errors": errors, "task_status": task.status,
                "escalated_to": target,
                "message": f"Sai chuẩn {tc.attempts}/{tc.max_attempts} lần — việc đã chuyển cho người xử lý, dừng tại đây."}
    # trả làm lại: việc đã nộp duyệt/xong → về Đang làm; nộp từ ngoài lượt chạy → đánh thức ghế
    if task.status in ("review", "done"):
        _move(db, task, "in_progress", f"kết quả sai hợp đồng (lần {tc.attempts}): {lines}"[:480], None)
    if via != "mcp" and via != "runtime":
        from app.services import wakeup
        wakeup.enqueue_for_task(db, task, "changes_requested", dedupe_key=f"contract:t{task.id}:a{tc.attempts}",
                                payload={"contract": tc.name, "errors": errors[:8]})
    return {"valid": False, "attempt": tc.attempts, "attempts_left": left, "status": "rework", "errors": errors,
            "task_status": task.status,
            "message": f"Kết quả chưa đạt hợp đồng (lần {tc.attempts}/{tc.max_attempts}). Sửa các lỗi rồi nộp lại: {lines}"}


def _move(db: Session, task: Task, to: str, reason: str, actor: int | None) -> str | None:
    from app.services import task_lifecycle as lifecycle
    path = {("review", "in_progress"): ["in_progress"], ("done", "in_progress"): ["review", "in_progress"],
            ("in_progress", "review"): ["review"], ("in_progress", "blocked"): ["blocked"],
            ("review", "blocked"): ["in_progress", "blocked"], ("todo", "blocked"): ["in_progress", "blocked"],
            ("backlog", "blocked"): ["todo", "in_progress", "blocked"], ("done", "blocked"): ["review", "in_progress", "blocked"]}
    steps = path.get((task.status, to))
    if not steps:
        return None
    try:
        for s in steps:
            lifecycle.transition(db, task, s, reason=reason, via="contract", system=True, actor_member_id=actor)
        return to
    except HTTPException as exc:
        db.rollback()
        print(f"[m2e.3] move task #{task.id} → {to}: {exc.detail}")
        return None


def escalate(db: Session, task: Task, tc: TaskContract, member: Member | None, lines: str) -> str | None:
    from app.services import escalation, inbox
    target, why = escalation.human_target(db, member or (db.get(Member, task.assignee_member_id) if task.assignee_member_id else None))
    tc.status, tc.escalated_to_member_id = "escalated", target
    db.commit()
    _move(db, task, "blocked", f"sai hợp đồng {tc.name} {tc.attempts} lần — chuyển người xử lý", None)
    if target:
        who = member.name if member else "Ghế"
        inbox.notify(db, organization_id=task_org(db, task), recipients=[target], kind="output_escalated",
                     title=f"{who}: kết quả \"{tc.name}\" sai chuẩn {tc.attempts} lần — cần người"[:220], task_id=task.id,
                     line=f"Lỗi lần cuối: {lines}"[:400], source="contract", priority="high",
                     company_id=_company_of(db, task))
    m = db.get(Member, target) if target else None
    return f"{m.name} ({why})" if m else None


def task_org(db: Session, task: Task) -> int:
    from app.models import Company
    co = db.get(Company, _company_of(db, task)) if _company_of(db, task) else None
    return co.organization_id if co else 0


def _to_step(db: Session, tc: TaskContract, output: dict) -> None:
    """Kết quả đạt chuẩn của việc thuộc bước quy trình → step run (điều kiện bước sau đọc được)."""
    from app.models.company_ops import ProcessStepRun
    run = db.get(ProcessStepRun, tc.step_run_id) if tc.step_run_id else \
        db.query(ProcessStepRun).filter(ProcessStepRun.task_id == tc.task_id).first()
    if run is None:
        return
    run.output_json = output
    if tc.outcome_field and not run.outcome:
        v = output.get(tc.outcome_field)
        if v is not None:
            run.outcome = (json.dumps(v) if isinstance(v, bool) else str(v))[:200]
    db.commit()


# ------------------------------------------------------------------ cổng: chuyển trạng thái + kết thúc lượt chạy

def gate_transition(db: Session, task: Task, to: str) -> str | None:
    """Agent chuyển việc có hợp đồng (chưa đạt) sang Chờ duyệt/Xong → lý do chặn (None = cho qua)."""
    if to not in ("review", "done"):
        return None
    tc = task_contract(db, task.id)
    if tc is None or tc.status == "accepted":
        return None
    if tc.status == "escalated":
        return f"Việc #{task.id} đã chuyển cho người xử lý (sai hợp đồng {tc.name} quá số lần)."
    return (f"Việc #{task.id} có hợp đồng dữ liệu \"{tc.name}\": nộp kết quả bằng {SUBMIT_TOOL} trước "
            f"(đạt chuẩn thì việc tự sang Chờ duyệt). Trường cần nộp: {describe_fields(tc.output_schema)}")


def on_run_end(db: Session, task: Task, member_id: int | None, *, run_id: str = "", session_key: str = "") -> tuple[str, str] | None:
    """Lượt chạy xong ("complete" → review) mà việc có hợp đồng chưa đạt → (trạng thái mới, lý do).
    Còn lượt → "todo" (đánh thức lại sau); hết lượt → leo thang (việc đã bị chuyển Bị chặn)."""
    tc = task_contract(db, task.id)
    if tc is not None and tc.status == "escalated":
        return "blocked", "contract_escalated"      # đã leo thang giữa lượt → giữ Bị chặn
    if tc is None or tc.status != "open":
        return None
    member = db.get(Member, member_id) if member_id else None
    r = submit(db, task, member, None, via="runtime", run_id=run_id, session_key=session_key,
               forced_error=f"Lượt chạy kết thúc mà chưa nộp kết quả bằng {SUBMIT_TOOL}")
    if r["status"] == "escalated":
        return "blocked", "contract_escalated"
    return "todo", "contract_missing_output"


# ------------------------------------------------------------------ tỷ lệ đạt chuẩn

def conformance(db: Session, *, member_ids: list[int] | None = None, company_id: int | None = None,
                contract_id: int | None = None, position_id: int | None = None, days: int = 30,
                start: datetime | None = None, end: datetime | None = None) -> dict:
    """Tỷ lệ lần nộp hợp lệ / tổng lần nộp (gồm "chưa nộp") + tỷ lệ đạt ngay lần đầu (theo việc)."""
    q = db.query(TaskOutput)
    if start is None:
        start = datetime.utcnow() - timedelta(days=days)
    q = q.filter(TaskOutput.created_at >= start)
    if end is not None:
        q = q.filter(TaskOutput.created_at < end)
    if member_ids is not None:
        q = q.filter(TaskOutput.member_id.in_(member_ids or [-1]))
    if company_id is not None:
        q = q.filter(TaskOutput.company_id == company_id)
    if contract_id is not None:
        q = q.filter(TaskOutput.contract_id == contract_id)
    if position_id is not None:
        q = q.filter(TaskOutput.position_id == position_id)
    rows = q.all()
    valid = sum(1 for o in rows if o.valid)
    tasks: dict[int, list[TaskOutput]] = {}
    for o in rows:
        tasks.setdefault(o.task_id, []).append(o)
    firsts = [min(v, key=lambda x: x.attempt) for v in tasks.values()]
    first_ok = [o for o in firsts if o.attempt == 1]
    return {"submissions": len(rows), "valid": valid, "rate": round(valid / len(rows), 4) if rows else None,
            "tasks": len(tasks), "first_try_rate": round(sum(1 for o in first_ok if o.valid) / len(first_ok), 4) if first_ok else None}


def seat_conformance(db: Session, company_id: int) -> list[dict]:
    out = []
    for m in db.query(Member).filter(Member.company_id == company_id, Member.status.notin_(("retired", "archived"))).order_by(Member.id).all():
        c = conformance(db, member_ids=[m.id])
        if c["submissions"] or m.member_type == "agent":
            out.append({"member_id": m.id, "name": m.name, "member_type": m.member_type, **c})
    return out


def position_conformance(db: Session, company_id: int) -> list[dict]:
    out = []
    for p in db.query(Position).filter(Position.company_id == company_id, Position.status != "archived").order_by(Position.id).all():
        c = conformance(db, position_id=p.id)
        n = db.query(IoContract).filter(IoContract.position_id == p.id, IoContract.status == "active").count()
        if c["submissions"] or n:
            out.append({"position_id": p.id, "title": p.title, "contracts": n, **c})
    return out


# ------------------------------------------------------------------ AGENTS.md

def agents_md_lines(db: Session, position_id: int) -> list[str]:
    """Dòng "## Hợp đồng dữ liệu" của chức danh: hợp đồng gắn chức danh + hợp đồng của các bước quy trình do chức danh làm."""
    from app.models.company_ops import Process, ProcessStep
    rows = db.query(IoContract).filter(IoContract.position_id == position_id, IoContract.status == "active").all()
    seen = {c.id for c in rows}
    step_of: dict[int, list[str]] = {}
    for s, p in (db.query(ProcessStep, Process).join(Process, Process.id == ProcessStep.process_id)
                 .filter(ProcessStep.position_id == position_id, ProcessStep.contract_id.isnot(None),
                         Process.status != "archived").all()):
        step_of.setdefault(s.contract_id, []).append(f"{p.name} B{s.seq}")
        if s.contract_id not in seen:
            c = db.get(IoContract, s.contract_id)
            if c is not None and c.status == "active":
                rows.append(c); seen.add(c.id)
    out = []
    for c in rows[:10]:
        crit = "; ".join(a["text"] for a in c.acceptance or [] if a.get("text"))
        where = f" (bước: {', '.join(step_of[c.id][:3])})" if c.id in step_of else ""
        out.append(f"- **{c.name}**{where}: {describe_fields(c.output_schema, limit=400)}"
                   + (f" · tiêu chí: {crit}" if crit else "")
                   + (f" · `{c.outcome_field}` là kết quả bước" if c.outcome_field else ""))
    return out
