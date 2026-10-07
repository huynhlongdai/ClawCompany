"""Gate M2 trên VM (chạy trong container api): dựng công ty từ mẫu với gateway
OpenClaw thật → đủ phòng ban & sơ đồ đúng; mời người → đăng nhập thấy đúng quyền.

    docker cp tools/gate_m2.py clawcompany-api-1:/tmp/g.py
    docker exec clawcompany-api-1 python /tmp/g.py http://127.0.0.1:8000 [shop|agency|ketoan]
"""
import json, secrets, sys, urllib.request, urllib.error

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/") + "/api"
KEY = sys.argv[2] if len(sys.argv) > 2 else "shop"
OK = []; BAD = []


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw.decode(errors="replace")


def flat(t):
    return [x for n in t for x in [n] + flat(n["children"])]


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("OK   " if cond else "FAIL ") + name + (f" — {info}" if info else ""), flush=True)


s, login = call("POST", "/auth/login", {"email": "admin@clawcompany.local", "password": "ChangeMe123!"})
adm = login["access_token"]
s, me = call("GET", "/team/me", token=adm)
check("admin /team/me", s == 200 and me["capabilities"]["create_company"], f"{me.get('role')}")

tag = secrets.token_hex(2)
s, out = call("POST", "/team/companies/from-template", {"template_key": KEY, "company_name": f"Gate M2 {KEY} {tag}"}, adm)
check("dựng công ty từ mẫu", s == 200, json.dumps(out, ensure_ascii=False)[:300])
cid = out["company_id"]
check("mọi agent đã có trên gateway", out["agents_bound"] == out["agents"] and out["job_status"] == "ready",
      f"{out['agents_bound']}/{out['agents']} · {out['job_status']} · {out['runtime_issues']}")

s, tpls = call("GET", "/team/templates", token=adm)
spec = next(t for t in tpls if t["key"] == KEY)
s, chart = call("GET", f"/team/org-chart?company_id={cid}", token=adm)
names = [d["name"] for d in chart["departments"]]
check("đủ phòng ban theo mẫu", names == [d["name"] for d in spec["departments"]], ", ".join(names))
check("mọi phòng có trưởng phòng", chart["stats"]["without_head"] == 0)
heads = {d["name"]: d["head_name"] for d in chart["departments"]}
check("trưởng phòng đúng mẫu", heads == {d["name"]: d["head"] for d in spec["departments"]}, json.dumps(heads, ensure_ascii=False))
tree = chart["tree"]
check("một gốc là Giám đốc", len(tree) == 1 and tree[0]["department"] == "Ban điều hành", tree[0]["name"] if tree else "-")
ok_shape = all(h["is_head"] and all(c["department_id"] == h["department_id"] and not c["is_head"] for c in h["children"])
               for h in tree[0]["children"])
check("trưởng phòng báo cáo Giám đốc, nhân viên báo cáo trưởng phòng", ok_shape and len(tree[0]["children"]) == len(spec["departments"]) - 1)

# gateway thật có đủ agent
from app.runtime.factory import get_runtime  # noqa: E402
import asyncio  # noqa: E402
roster = asyncio.run(get_runtime().list_agents())
ids = {str(a.get("id") or a.get("agentId")) for a in roster}
want = {n["runtime_agent_id"] for n in [tree[0]] + [x for h in tree[0]["children"] for x in [h] + h["children"]]}
check("agents.list trên gateway có đủ id", want <= ids, f"thiếu {sorted(want - ids)}" if want - ids else f"{len(want)} id")

# mời người: member và manager
for role in ("member", "manager"):
    email = f"gate-{role}-{tag}@clawcompany.local"
    s, inv = call("POST", "/team/invitations", {"email": email, "role": role, "company_id": cid,
                                                  "department_id": chart["departments"][1]["id"], "job_title": f"Gate {role}"}, adm)
    check(f"tạo lời mời {role}", s == 200, inv.get("invite_path", inv) if isinstance(inv, dict) else inv)
    s, look = call("GET", f"/team/invitations/lookup?token={inv['token']}")
    check(f"xem lời mời {role} (công khai)", s == 200 and look["department"] == chart["departments"][1]["name"])
    s, acc = call("POST", "/team/invitations/accept", {"token": inv["token"], "password": "GateM2-Pass1", "display_name": f"Gate {role}"})
    check(f"nhận lời mời {role}", s == 200 and acc["role"] == role)
    s, lg = call("POST", "/auth/login", {"email": email, "password": "GateM2-Pass1"})
    tok = lg["access_token"]
    s, m2 = call("GET", "/team/me", token=tok)
    check(f"{role} đăng nhập thấy đúng vai", m2["role"] == role, json.dumps(m2["capabilities"]))
    s, _ = call("POST", "/team/invitations", {"email": f"x-{role}-{tag}@x.vn", "role": "member"}, tok)
    check(f"{role} mời người: {'được' if role == 'manager' else 'bị chặn'}", s == (200 if role == "manager" else 403), str(s))
    s, _ = call("POST", "/team/companies/from-template", {"template_key": KEY}, tok)
    check(f"{role} dựng công ty bị chặn", s == 403, str(s))
    s, c2 = call("GET", f"/team/org-chart?company_id={cid}", token=tok)
    check(f"{role} xem được sơ đồ có mình", s == 200 and any(n.get("email") == email for n in flat(c2["tree"])))
    if role == "member":
        s, _ = call("PUT", f"/team/departments/{chart['departments'][1]['id']}/head", {"member_id": None}, tok)
        check("member sửa trưởng phòng bị chặn", s == 403, str(s))
        uid = acc["user_id"]; member_tok = tok

s, r = call("PATCH", f"/team/access/{uid}", {"role": "manager"}, adm)
check("admin nâng member → manager", s == 200)
s, m3 = call("GET", "/team/me", token=member_tok)
check("token cũ có quyền mới ngay", m3["role"] == "manager")
s, r = call("DELETE", f"/team/access/{uid}", token=adm)
s, m4 = call("GET", "/team/me", token=member_tok)
check("thu hồi chặn token cũ ngay", s == 401, str(s))
s, r = call("PATCH", f"/team/access/{me['user_id']}", {"role": "member"}, adm)
check("admin không tự hạ quyền mình", s == 403, str(s))
print(f"\n{len(OK)}/{len(OK) + len(BAD)} OK · company_id={cid}")
sys.exit(1 if BAD else 0)
