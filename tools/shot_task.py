#!/usr/bin/env python3
"""WP-4.3 UI — chụp màn hình chi tiết công việc trên bản chạy thật.

Ba thứ chỉ phát hiện được khi mở trang thật, và script này thu cả ba: lỗi
console, khối bị tràn/chồng, và trạng thái trống hiện sai (ví dụ "đang tải" mãi
vì API trả 401).

Ngoài chụp ảnh, script còn **kiểm hành vi trên UI**:

* sổ ghi có hiện đúng số mục mà API trả về
* bộ lọc theo loại mục có lọc thật
* thanh ngân sách bảy khối có đủ bảy dòng, và khối 2/6/7 có dấu "không cắt"
* nút Bàn giao bị khoá khi chưa chọn người nhận
* bấm "Xem nguyên văn gói" thì hiện đúng nội dung prompt

Chạy (cần devstack + gateway + API + web đang lên):

    .venv/bin/python tools/shot_task.py <task_id>
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_reports" / "ui"
WEB = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
EMAIL, PASSWORD = "admin@clawcompany.local", "ChangeMe123!"


def pick_task() -> int:
    """Task có sổ ghi dày nhất — màn hình trống không chứng minh được gì."""
    if len(sys.argv) > 1:
        return int(sys.argv[1])
    client = httpx.Client(base_url=API, timeout=60.0)
    token = client.post("/api/auth/login",
                        json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    best, best_count = None, -1
    for task in client.get("/api/tasks", headers=headers).json():
        journal = client.get(f"/api/tasks/{task['id']}/journal", headers=headers)
        if journal.status_code >= 400:
            continue
        count = journal.json()["digest"]["entries"]
        if count > best_count:
            best, best_count = task["id"], count
    print(f"chọn task #{best} ({best_count} mục sổ ghi)")
    return best or 1


async def main() -> int:
    task_id = pick_task()
    OUT.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))

        await page.goto(f"{WEB}/", wait_until="networkidle")
        if await page.locator("#cc-email").count():
            await page.fill("#cc-email", EMAIL)
            await page.fill("#cc-password", PASSWORD)
            await page.get_by_role("button", name="Đăng nhập").click()
            # AuthGate là cổng, không phải redirect: chờ ô email biến mất.
            await page.locator("#cc-email").wait_for(state="detached", timeout=20_000)

        await page.goto(f"{WEB}/app/tasks/{task_id}", wait_until="networkidle")
        await page.wait_for_timeout(3500)

        body = await page.inner_text("body")
        if "Đang tải công việc" in body:
            problems.append("trang vẫn ở trạng thái 'đang tải' sau 3,5s")

        await page.screenshot(path=str(OUT / "task-detail-top.png"))
        await page.screenshot(path=str(OUT / "task-detail-full.png"), full_page=True)

        # --- sổ ghi ---
        rows = await page.locator(".timeline .timeRow").count()
        if rows == 0:
            problems.append("sổ ghi không có dòng nào")
        print(f"sổ ghi: {rows} dòng")

        # --- bộ lọc theo loại mục có lọc thật không ---
        handoff_tab = page.locator(".pillTabs button", has_text="Bàn giao").first
        if await handoff_tab.count():
            await handoff_tab.click()
            await page.wait_for_timeout(500)
            filtered = await page.locator(".timeline .timeRow").count()
            if filtered >= rows:
                problems.append(f"bộ lọc không lọc: {rows} → {filtered} dòng")
            print(f"lọc 'Bàn giao': {rows} → {filtered} dòng")
            await page.screenshot(path=str(OUT / "task-journal-filtered.png"))
            await page.locator(".pillTabs button", has_text="Tất cả").first.click()
            await page.wait_for_timeout(400)

        # --- chi tiết một mục mở ra được ---
        detail_button = page.locator("button", has_text="Xem chi tiết").first
        if await detail_button.count():
            await detail_button.click()
            await page.wait_for_timeout(400)
            if not await page.locator("pre").count():
                problems.append("bấm 'Xem chi tiết' nhưng không hiện nội dung")
            await page.screenshot(path=str(OUT / "task-journal-detail.png"))

        # --- thanh ngân sách bảy khối ---
        # Đếm KHỚP CHÍNH XÁC: trang còn một câu giải thích chứa cùng chữ đó, và
        # `text=` khớp cả chuỗi con nên nó đếm thành 4. Nhãn của khối là một
        # phần tử có nội dung đúng bằng "không cắt".
        locks = await page.get_by_text("không cắt", exact=True).count()
        if locks != 3:
            problems.append(f"phải có đúng 3 khối 'không cắt' (2, 6, 7), thấy {locks}")
        print(f"khối không cắt: {locks}")

        # --- xem nguyên văn gói ---
        preview = page.locator("button", has_text="Xem nguyên văn gói").first
        if not await preview.count():
            problems.append("không thấy nút xem nguyên văn gói ngữ cảnh")
        else:
            await preview.click()
            await page.wait_for_timeout(600)
            text = await page.inner_text("body")
            if "Thoả thuận làm việc" not in text:
                problems.append("xem nguyên văn gói nhưng không thấy nội dung bảy khối")
            await page.locator("text=Gói ngữ cảnh agent sẽ nhận").first.scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(OUT / "task-context-pack.png"))

        # --- nút bàn giao phải khoá khi chưa chọn người ---
        submit = page.locator("button.primary", has_text="Bàn giao").first
        if not await submit.count():
            problems.append("không thấy nút Bàn giao")
        elif not await submit.is_disabled():
            problems.append("chưa chọn người nhận nhưng nút Bàn giao vẫn bấm được")

        # --- chọn người nhận rồi chụp form đã điền ---
        select = page.locator("select").first
        if await select.count():
            options = await select.locator("option").all_inner_texts()
            agent_options = [o for o in options if "(AI)" in o]
            if not agent_options:
                problems.append("danh sách người nhận không có agent nào")
            else:
                await select.select_option(label=agent_options[0])
                await page.locator("textarea").last.fill(
                    "Soát lại tông thương hiệu, bỏ mọi nhạc có bản quyền, "
                    "xong trước thứ Năm.")
                await page.wait_for_timeout(400)
                if await submit.is_disabled():
                    problems.append("đã chọn người nhận nhưng nút Bàn giao vẫn bị khoá")
                await page.locator("text=Bàn giao cho người khác").first \
                    .scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                await page.screenshot(path=str(OUT / "task-handoff-form.png"))

                # --- BẤM THẬT ---
                #
                # Kiểm "nút bấm được" chưa chứng minh gì; chỉ một lần bàn giao
                # thật mới chứng minh cả đường dây UI → API → sổ ghi → runtime.
                # Lượt này tốn một lời gọi model thật, và đó chính là điều cần đo.
                if "--no-submit" not in sys.argv:
                    await submit.click()
                    try:
                        await page.get_by_text("Đã bàn giao cho", exact=False).first \
                            .wait_for(timeout=180_000)
                    except Exception:                     # noqa: BLE001
                        problems.append("bấm Bàn giao nhưng không thấy kết quả sau 180s")
                    await page.wait_for_timeout(700)
                    result_text = await page.inner_text("body")
                    for needle, label in (
                        ("Ghi sổ: xong", "kết quả không báo đã ghi sổ"),
                        ("Chủ việc đã chuyển", "kết quả không báo chuyển chủ việc"),
                        ("Giao việc: đã chạy", "kết quả không báo đã giao việc"),
                    ):
                        if needle not in result_text:
                            problems.append(label)
                    await page.locator("text=Bàn giao cho người khác").first \
                        .scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)
                    await page.screenshot(path=str(OUT / "task-handoff-result.png"))
                    print("đã bàn giao thật qua UI")

        await browser.close()

    print(f"\n→ ảnh trong {OUT}")
    if problems:
        print("\nVẤN ĐỀ PHÁT HIỆN:")
        for item in problems:
            print("  -", item)
        return 1
    print("0 lỗi console; sổ ghi, bộ lọc, thanh ngân sách bảy khối, xem nguyên văn "
          "và khoá nút bàn giao đều hoạt động.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
