"""UI v2: làm giàu dữ liệu seed qua HTTP để chụp ảnh có nội dung thật (API mock, SQLite).
Chạy sau `python seed.py` và khi API đang chạy ở :8000.  python tools/seed_ui_v2.py"""
import json, urllib.request, sys
API = "http://127.0.0.1:8000/api"
OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # bỏ proxy của môi trường

def call(method, path, body=None, tok=None, ok=(200, 201)):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {tok}"} if tok else {})})
    try:
        with OPEN.open(req, timeout=60) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        print("!", method, path, e.code, e.read()[:200].decode(errors="ignore")); return None

tok = call("POST", "/auth/login", {"email": "admin@clawcompany.local", "password": "ChangeMe123!"})["access_token"]
tpl = call("GET", "/team/templates", tok=tok) or []
print("templates", [t["key"] for t in tpl])
built = call("POST", "/team/companies/from-template", {"template_key": tpl[0]["key"], "company_name": "Tiệm Gốm Mộc"}, tok) if tpl else None
print("built", built and {k: built.get(k) for k in ("company_id", "company_name", "departments", "agents")})
meta = call("GET", "/work/meta", tok=tok)
projects = meta["projects"]; members = [m for m in meta["members"] if m["assignable"]]
agents = [m for m in members if m["type"] == "agent"]
pid = projects[0]["id"]
specs = [("Viết 5 caption cho bộ sưu tập hè", "high"), ("Chụp lại ảnh sản phẩm bình men lam", "medium"), ("Đối soát đơn Shopee tuần 41", "urgent"),
         ("Lên lịch đăng TikTok 2 tuần", "medium"), ("Trả lời 12 bình luận tồn", "low"), ("Báo giá cho khách sỉ Đà Nẵng", "high"),
         ("Tổng hợp phản hồi khách tháng 9", "medium"), ("Kiểm kho men rạn trước sale", "high")]
ids = []
for i, (title, prio) in enumerate(specs):
    a = agents[i % len(agents)]
    t = call("POST", "/work/tasks", {"title": title, "project_id": pid, "priority": prio, "assignee_member_id": a["id"], "start": i % 3 != 2,
                                     "description": "Dữ liệu mẫu cho ảnh chụp UI v2", "acceptance_criteria": "Có kết quả ghi trong sổ việc"}, tok)
    if t: ids.append(t["id"])
for tid in ids[:4]:
    call("POST", f"/work/tasks/{tid}/run", {}, tok)
def walk(tid, path):
    for st in path:
        t = call("GET", f"/work/tasks/{tid}", tok=tok)
        if t and t["status"] != st: call("POST", f"/work/tasks/{tid}/move", {"status": st, "expected_revision": t["revision"]}, tok)
if len(ids) > 5:
    walk(ids[4], ["in_progress", "blocked"]); walk(ids[5], ["todo", "in_progress"]); walk(ids[6], ["in_progress", "review"])
b = call("GET", "/costs/budgets", tok=tok)
scopes = (b or {}).get("scopes", {})
for typ, lim in (("company", 50), ("department", 20), ("member", 5)):
    opts = scopes.get(typ) or []
    if opts: call("POST", "/costs/budgets", {"scope_type": typ, "scope_id": opts[0]["id"], "amount_limit": lim, "warn_pct": 80, "soft_stop_pct": 90}, tok)
print("tasks", ids)
