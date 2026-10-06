#!/usr/bin/env python3
"""D2.1 UI — panel Đánh thức + ô bình luận @nhắc trên TaskDetail (bản chạy thật).

usage: .venv/bin/python tools/shot_d21.py <task_id>
Kiểm: panel có đúng số dòng API trả về; gửi bình luận @Nina → API trả woke,
panel hiện thêm một dòng 'mentioned' trong ≤ 30s; 0 lỗi console.
"""
import asyncio, sys
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_reports" / "ui"
WEB, API = "http://127.0.0.1:3000", "http://127.0.0.1:8000"
EMAIL, PASSWORD = "admin@clawcompany.local", "ChangeMe123!"
TID = int(sys.argv[1])


async def main() -> int:
    c = httpx.Client(base_url=API, timeout=60)
    tok = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    api_rows = c.get("/api/tasks/wakeups", headers=H, params={"task_id": TID}).json()
    problems: list[str] = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/vercel/sandbox/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome")
        ctx = await b.new_context(viewport={"width": 1440, "height": 1100})
        await ctx.add_init_script(f"localStorage.setItem('clawcompany_token','{tok}')")
        page = await ctx.new_page()
        page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        await page.goto(f"{WEB}/app/tasks/{TID}", wait_until="networkidle")
        panel = page.locator('[data-testid="task-wakeups"]')
        await panel.wait_for(timeout=20_000)
        await page.wait_for_timeout(1500)
        n0 = await panel.locator('[data-testid="wakeup-row"]').count()
        print("api rows", len(api_rows), "ui rows", n0, await panel.inner_text())
        if n0 != len(api_rows):
            problems.append(f"panel {n0} dòng ≠ API {len(api_rows)}")
        await panel.scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "d21-task-wakeups.png"))
        await panel.screenshot(path=str(OUT / "d21-wakeups-panel.png"))

        box = page.locator('[data-testid="journal-input"]')
        await box.scroll_into_view_if_needed()
        await box.fill("@Nina xem lại kết quả giúp nhé")
        await page.locator('[data-testid="journal-send"]').click()
        await page.locator('[data-testid="journal-sent"]').wait_for(timeout=10_000)
        print("sent:", await page.locator('[data-testid="journal-sent"]').inner_text())
        ok = False
        for _ in range(30):
            await page.wait_for_timeout(1000)
            if await panel.locator('[data-testid="wakeup-row"]').count() > n0:
                ok = True
                break
        if not ok:
            problems.append("panel không hiện dòng đánh thức mới sau 30s")
        settled = False
        for _ in range(40):  # cửa sổ gộp 10s + vòng drain 5s; panel tự hỏi lại 4s/lần
            await page.wait_for_timeout(1000)
            if "đang chờ gộp" not in await panel.inner_text():
                settled = True
                break
        if not settled:
            problems.append("panel vẫn 'đang chờ gộp' sau 40s — không tự cập nhật")
        print("after:", await panel.inner_text())
        await page.screenshot(path=str(OUT / "d21-task-after-mention.png"), full_page=True)
        await panel.screenshot(path=str(OUT / "d21-wakeups-after-mention.png"))
        await page.close(); await b.close()
    print("PROBLEMS:", problems or "none")
    return 1 if problems else 0

sys.exit(asyncio.run(main()))
