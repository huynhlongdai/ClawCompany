#!/usr/bin/env python3
"""D2.2 UI — panel "Chặng duyệt" trên TaskDetail (bản chạy thật), có bấm thật.

usage: .venv/bin/python tools/shot_d22.py <task_done_id> <task_missing_report_id>
1. Ảnh stepper của task đã DUYỆT (vòng 2) và task bị chặn missing_report.
2. Trình soạn: thêm 1 chặng review trên task mới → lưu → stepper có 1 chặng.
3. Bấm "Yêu cầu sửa" (kèm nhận xét) → task về in_progress; đưa lại review; bấm "Duyệt" → done.
0 lỗi console.
"""
import asyncio, sys, uuid
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_reports" / "ui"
WEB, API = "http://127.0.0.1:3000", "http://127.0.0.1:8000"
CHROME = "/vercel/sandbox/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
DONE_ID, MISSING_ID = int(sys.argv[1]), int(sys.argv[2])


async def main() -> int:
    c = httpx.Client(base_url=API, timeout=60)
    tok = c.post("/api/auth/login", json={"email": "admin@clawcompany.local", "password": "ChangeMe123!"}).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    sfx = uuid.uuid4().hex[:5]
    qa = c.post("/api/v18/workspace/members", headers=H, json={"organization_id": 1, "name": f"Hà QA {sfx}",
                                                                "member_type": "human", "role": "QA"}).json()
    comp = c.post("/api/v18/workspace/companies", headers=H, json={"organization_id": 1, "name": f"UI D22 {sfx}"}).json()
    proj = c.post("/api/v18/workspace/projects", headers=H, json={"company_id": comp["id"], "name": f"Dự án {sfx}"}).json()
    t = c.post("/api/v18/workspace/tasks", headers=H, json={"project_id": proj["id"], "title": f"Soạn quy trình {sfx}"}).json()
    tid = t["id"]
    c.post(f"/api/v18/workspace/tasks/{tid}/assign", headers=H, json={"assignee_member_id": qa["id"]})
    c.post(f"/api/v18/workspace/tasks/{tid}/move", headers=H, json={"status": "todo"})
    c.post(f"/api/v18/workspace/tasks/{tid}/move", headers=H, json={"status": "in_progress"})
    problems: list[str] = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME)
        ctx = await b.new_context(viewport={"width": 1440, "height": 1100})
        await ctx.add_init_script(f"localStorage.setItem('clawcompany_token','{tok}')")
        page = await ctx.new_page()
        page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))

        async def open_task(i):
            await page.goto(f"{WEB}/app/tasks/{i}", wait_until="networkidle")
            panel = page.locator('[data-testid="task-policy"]')
            await panel.wait_for(timeout=20_000)
            await page.wait_for_timeout(1200)
            await panel.scroll_into_view_if_needed()
            return panel

        panel = await open_task(DONE_ID)
        states = [await s.get_attribute("data-state") for s in await panel.locator('[data-testid="policy-stage"]').all()]
        print("done task stages:", states, (await panel.inner_text()).replace("\n", " | ")[:300])
        if states != ["passed"]:
            problems.append(f"task {DONE_ID}: stepper {states}")
        await panel.locator('[data-testid="policy-history"] summary').click()
        await panel.screenshot(path=str(OUT / "d22-policy-approved.png"))

        panel = await open_task(MISSING_ID)
        if not await panel.locator('[data-testid="policy-missing-report"]').count():
            problems.append("không thấy cảnh báo missing_report")
        await panel.screenshot(path=str(OUT / "d22-policy-missing-report.png"))

        # trình soạn
        panel = await open_task(tid)
        await panel.locator('[data-testid="policy-edit"]').click()
        await panel.locator('[data-testid="policy-type"]').select_option("review")
        await panel.locator('[data-testid="policy-participant"]').select_option(str(1))
        await panel.screenshot(path=str(OUT / "d22-policy-editor.png"))
        await panel.locator('[data-testid="policy-save"]').click()
        await page.wait_for_timeout(1200)
        n = await panel.locator('[data-testid="policy-stage"]').count()
        print("stages after save:", n)
        if n != 1:
            problems.append(f"lưu xong stepper có {n} chặng")
        # người làm báo xong → chặng review đang chờ Long
        c.post(f"/api/v18/workspace/tasks/{tid}/move", headers=H, json={"status": "review"})
        panel = await open_task(tid)
        await panel.screenshot(path=str(OUT / "d22-policy-in-review.png"))
        await panel.locator('[data-testid="review-note"]').fill("Thêm bước rollback")
        await panel.locator('[data-testid="review-revise"]').click()
        await page.wait_for_timeout(1500)
        st1 = c.get(f"/api/tasks/{tid}/execution-policy", headers=H).json()
        print("after revise:", st1["status"], st1["state"]["status"])
        if st1["status"] != "in_progress":
            problems.append(f"bấm 'Yêu cầu sửa' → {st1['status']}")
        c.post(f"/api/v18/workspace/tasks/{tid}/move", headers=H, json={"status": "review"})
        panel = await open_task(tid)
        await panel.locator('[data-testid="review-approve"]').click()
        await page.wait_for_timeout(1500)
        st2 = c.get(f"/api/tasks/{tid}/execution-policy", headers=H).json()
        print("after approve:", st2["status"], st2["state"]["status"], [(h["round"], h["decision"]) for h in st2["state"]["history"]])
        if st2["status"] != "done":
            problems.append(f"bấm 'Duyệt' → {st2['status']}")
        await panel.locator('[data-testid="policy-history"] summary').click()
        await panel.screenshot(path=str(OUT / "d22-policy-ui-approved.png"))
        await page.close(); await b.close()
    print("task", tid, "PROBLEMS:", problems or "none")
    return 1 if problems else 0

sys.exit(asyncio.run(main()))
