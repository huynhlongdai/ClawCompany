"""D1.1 — duyệt lệnh qua UI thật: agent xin chạy lệnh → thẻ trong Hộp việc →
bấm Duyệt → gateway chạy lệnh → việc sang chờ duyệt. Chụp ảnh từng bước."""
import asyncio, json, sys, time, uuid
import httpx
from playwright.async_api import async_playwright

WEB, API = "http://127.0.0.1:3000", "http://127.0.0.1:8000"
CH = "/vercel/sandbox/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
OUT = sys.argv[1] if len(sys.argv) > 1 else "_shots/d11"


async def main():
    c = httpx.Client(base_url=API, timeout=60)
    tok = c.post("/api/auth/login", json={"email": "admin@clawcompany.local", "password": "ChangeMe123!"}).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    c.post("/api/v19/openclaw/bind", params={"organization_id": 1}, headers=H, json={"member_id": 2, "runtime_agent_id": "dev"})
    sfx = uuid.uuid4().hex[:5]
    comp = c.post("/api/v18/workspace/companies", headers=H, json={"organization_id": 1, "name": f"UI Approval {sfx}"}).json()
    proj = c.post("/api/v18/workspace/projects", headers=H, json={"company_id": comp["id"], "name": f"Dự án {sfx}"}).json()
    task = c.post("/api/v18/workspace/tasks", headers=H, json={"project_id": proj["id"], "title": f"Kiểm tra máy chủ {sfx}"}).json()
    tid = task["id"]
    c.post(f"/api/v18/workspace/tasks/{tid}/move", headers=H, json={"status": "todo"})
    c.post(f"/api/v18/workspace/tasks/{tid}/assign", headers=H, json={"assignee_member_id": 2})
    started = c.post(f"/api/v19/tasks/{tid}/start", params={"organization_id": 1}, headers=H).json()
    c.post(f"/api/v20/tasks/{tid}/follow", headers=H, json={"session_key": started["session_key"]})
    appr = None
    for _ in range(60):
        rows = c.get("/api/approvals", params={"status": "pending"}, headers=H).json()
        appr = next((a for a in rows if started["session_key"] in (a.get("policy_key") or "")), None)
        if appr: break
        time.sleep(1)
    out = {"task_id": tid, "approval_id": appr and appr["id"]}
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CH, args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 1440, "height": 1000}, locale="vi-VN")
        await ctx.add_init_script(f"localStorage.setItem('clawcompany_token','{tok}')")
        pg = await ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:150]))
        pg.on("console", lambda m: errs.append(m.text[:150]) if m.type == "error" else None)
        await pg.goto(WEB + "/app/inbox", wait_until="networkidle"); await pg.wait_for_timeout(1200)
        card = pg.locator("article.ui-row", has_text=f"#{appr['id']}")
        out["command_shown"] = await card.locator("[data-testid=approval-command]").inner_text()
        await pg.screenshot(path=f"{OUT}/1-inbox-pending.png", full_page=False)
        await card.get_by_role("button", name="Duyệt").click()
        await card.locator("textarea").fill("Lệnh chỉ đọc, cho chạy một lần")
        await pg.screenshot(path=f"{OUT}/2-inbox-confirm.png", full_page=False)
        await card.get_by_role("button", name="Xác nhận duyệt").click()
        await pg.wait_for_timeout(1500)
        out["card_gone"] = await pg.locator("article.ui-row", has_text=f"#{appr['id']}").count() == 0
        status = None
        for _ in range(30):
            status = next((t["status"] for t in c.get("/api/tasks", headers=H).json() if t["id"] == tid), None)
            if status == "review": break
            time.sleep(1)
        out["task_status"] = status
        await pg.goto(WEB + f"/app/tasks/{tid}", wait_until="networkidle"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/3-task-after.png", full_page=True)
        out["errors"] = errs
        await b.close()
    tr = c.get(f"/api/v19/tasks/{tid}/transcript", params={"organization_id": 1}, headers=H).json()
    res = [m for m in tr.get("messages", []) if m.get("role") == "toolResult"]
    out["exec_result"] = [json.dumps(m.get("content"), ensure_ascii=False)[:200] for m in res]
    audit = c.get("/api/activity", params={"limit": 50}, headers=H).json()
    out["audit"] = [a["action"] for a in reversed(audit) if a.get("object_type") == "approval" and a.get("object_id") == str(appr["id"])]
    print(json.dumps(out, ensure_ascii=False, indent=1))

asyncio.run(main())
