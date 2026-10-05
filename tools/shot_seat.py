#!/usr/bin/env python3
"""WP-2.1/2.2 — chụp màn hình hồ sơ nhân sự AI, sáu tab, trên bản chạy thật.

Không phải để trang trí báo cáo. Ba thứ chỉ phát hiện được bằng cách mở trang
thật: lỗi console (React), khối bị tràn/chồng, và trạng thái trống hiện sai
(ví dụ "đang tải" mãi vì API trả 401). Script này thu cả ba.

Chạy (cần devstack + gateway + API + web đang lên):

    .venv/bin/python tools/shot_seat.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_reports" / "ui"
WEB = "http://127.0.0.1:3000"
EMAIL, PASSWORD = "admin@clawcompany.local", "ChangeMe123!"

# Member id của Nina trong dữ liệu seed (member #2 ⇔ agent seat #1).
MEMBER_ID = 2
TABS = ["Hồ sơ", "Tính cách", "Công việc", "Năng lực", "Quyền", "Hạn mức"]


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        # đăng nhập
        await page.goto(f"{WEB}/", wait_until="networkidle")
        # Ô email KHÔNG có type="email" (chỉ có id + autoComplete), nên selector
        # theo type sẽ chờ vô ích 30 giây rồi chết. Dùng id thật.
        if await page.locator("#cc-email").count():
            await page.fill("#cc-email", EMAIL)
            await page.fill("#cc-password", PASSWORD)
            # Nút đăng nhập không có type="submit" và không mang class .primary;
            # chọn theo vai + tên là cách duy nhất không phụ thuộc chi tiết CSS.
            await page.get_by_role("button", name="Đăng nhập").click()
            # AuthGate là *cổng*, không phải redirect: đăng nhập xong URL vẫn là
            # "/" và nội dung được thay tại chỗ. Nên chờ ô email biến mất, đừng
            # chờ điều hướng — chờ điều hướng sẽ hết giờ dù đăng nhập đã thành công.
            await page.locator("#cc-email").wait_for(state="detached", timeout=20_000)

        await page.goto(f"{WEB}/app/agents/{MEMBER_ID}", wait_until="networkidle")
        await page.wait_for_timeout(3500)

        # Trang phải thoát khỏi trạng thái "đang tải" — nếu không thì API lỗi.
        body = await page.inner_text("body")
        if "Đang tải hồ sơ" in body or "Đang tra seat" in body:
            errors.append("trang vẫn ở trạng thái 'đang tải' sau 3,5s")

        await page.screenshot(path=str(OUT / "seat-profile-top.png"), full_page=False)

        for index, label in enumerate(TABS):
            tab = page.locator(".pillTabs button", has_text=label).first
            if not await tab.count():
                errors.append(f"không thấy tab '{label}'")
                continue
            await tab.click()
            await page.wait_for_timeout(900)
            await page.screenshot(path=str(OUT / f"seat-tab-{index}-{label.replace(' ', '-').lower()}.png"))

        # Thử vượt hạn mức ký tự ngay trên UI: cảnh báo phải hiện và nút Lưu
        # phải bị khoá, chứ không để người dùng bấm rồi nhận lỗi từ server.
        await page.locator(".pillTabs button", has_text="Tính cách").first.click()
        await page.wait_for_timeout(600)
        area = page.locator("textarea").first
        if await area.count():
            await area.fill("x" * 20_050)
            await page.wait_for_timeout(500)
            warned = await page.locator("text=Vượt hạn mức").count() > 0
            save = page.locator("button.primary", has_text="Lưu").first
            disabled = await save.is_disabled() if await save.count() else False
            if not warned:
                errors.append("vượt hạn mức nhưng UI không cảnh báo")
            if not disabled:
                errors.append("vượt hạn mức nhưng nút Lưu vẫn bấm được")
            await page.screenshot(path=str(OUT / "seat-over-budget.png"))

        await browser.close()

    print(f"→ ảnh trong {OUT}")
    if errors:
        print("\nVẤN ĐỀ PHÁT HIỆN:")
        for e in errors:
            print("  -", e)
        return 1
    print("0 lỗi console, 6 tab render được, chốt hạn mức ký tự có hiệu lực trên UI.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
