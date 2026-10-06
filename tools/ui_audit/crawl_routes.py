import asyncio, sys, json, httpx, os
from playwright.async_api import async_playwright
WEB="http://127.0.0.1:3000"; API="http://127.0.0.1:8000"
OUT="/data/out/audit"; os.makedirs(OUT,exist_ok=True)
PAGES=json.load(open("tools/ui_audit/routes.json"))
async def main():
    tok=httpx.post(API+"/api/auth/login",json={"email":"admin@clawcompany.local","password":"ChangeMe123!"}).json()["access_token"]
    report={}
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/vercel/sandbox/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",args=["--no-sandbox"])
        ctx=await b.new_context(viewport={"width":1440,"height":900},locale="vi-VN")
        await ctx.add_init_script(f"localStorage.setItem('clawcompany_token','{tok}')")
        for path in PAGES:
            pg=await ctx.new_page(); errs=[]
            pg.on("console",lambda m,errs=errs: errs.append("CONSOLE "+m.text[:200]) if m.type=="error" else None)
            pg.on("response",lambda r,errs=errs: errs.append(f"HTTP {r.status} {r.request.method} {r.url.replace(API,'')[:120]}") if r.status>=400 else None)
            pg.on("pageerror",lambda e,errs=errs: errs.append("PAGEERR "+str(e)[:200]))
            try:
                await pg.goto(WEB+path,wait_until="networkidle",timeout=120000)
            except Exception as e: errs.append("GOTO "+str(e)[:100])
            await pg.wait_for_timeout(1200)
            name=path.strip("/").replace("/","_").replace("?","_").replace("=","-") or "root"
            try:
                await pg.screenshot(path=f"{OUT}/{name}.png",full_page=False)
                txt=await pg.evaluate("document.body.innerText.slice(0,400)")
                visible_err=await pg.evaluate("Array.from(document.querySelectorAll('.v8Error,[role=alert]')).map(e=>e.innerText.slice(0,160))")
            except Exception as e:
                txt=""; visible_err=[str(e)[:100]]
            report[path]={"errors":errs[:12],"ui_errors":visible_err[:5],"text":txt[:200]}
            print(path,len(errs),len(visible_err),flush=True)
            await pg.close()
        await b.close()
    json.dump(report,open("/data/out/audit.json","w"),ensure_ascii=False,indent=1)
asyncio.run(main())
