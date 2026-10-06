import asyncio, json, httpx
from playwright.async_api import async_playwright
WEB="http://127.0.0.1:3000"; API="http://127.0.0.1:8000"
CORE=["/app/os","/app/os?tab=companies","/app/os?tab=people","/app/os?tab=agents","/app/os?tab=projects","/app/tasks/1","/app/agents/1","/app/approve","/app/budgets","/app/founder-cockpit","/app/control-center","/app/nina","/app/openclaw","/app/system","/app/live-runs","/app/workflows","/app/reviews"]
SKIP=("đăng xuất","logout","xoá","xóa","delete")
async def main():
    tok=httpx.post(API+"/api/auth/login",json={"email":"admin@clawcompany.local","password":"ChangeMe123!"}).json()["access_token"]
    rep={}
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/vercel/sandbox/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",args=["--no-sandbox"])
        ctx=await b.new_context(viewport={"width":1440,"height":900})
        await ctx.add_init_script(f"localStorage.setItem('clawcompany_token','{tok}')")
        for path in CORE:
            pg=await ctx.new_page(); errs=[]
            pg.on("console",lambda m,errs=errs: errs.append("CONSOLE "+m.text[:160]) if m.type=="error" else None)
            pg.on("response",lambda r,errs=errs: errs.append(f"HTTP {r.status} {r.request.method} {r.url.replace(API,'')[:100]}") if r.status>=400 else None)
            pg.on("pageerror",lambda e,errs=errs: errs.append("PAGEERR "+str(e)[:160]))
            pg.on("dialog",lambda d: asyncio.ensure_future(d.dismiss()))
            try: await pg.goto(WEB+path,wait_until="networkidle",timeout=60000)
            except Exception as e: errs.append("GOTO "+str(e)[:80]); rep[path]={"errors":errs}; await pg.close(); continue
            if "/login" in pg.url or pg.url.rstrip("/")!=(WEB+path).rstrip("/"): errs.append("REDIRECT "+pg.url)
            labels=await pg.evaluate("Array.from(document.querySelectorAll('main button, main [role=button]')).map(b=>b.innerText.trim().slice(0,40))")
            clicked=[]
            for i,lab in enumerate(labels[:25]):
                if any(s in lab.lower() for s in SKIP): continue
                try:
                    btns=pg.locator("main button, main [role=button]")
                    if i>=await btns.count(): break
                    n0=len(errs)
                    await btns.nth(i).click(timeout=2500)
                    await pg.wait_for_timeout(700)
                    ui=await pg.evaluate("Array.from(document.querySelectorAll('.v8Error,[role=alert],.error')).map(e=>e.innerText.slice(0,120)).filter(Boolean)")
                    clicked.append({"btn":lab,"new_errs":errs[n0:],"ui":ui[:3]})
                    if pg.url.split('?')[0].rstrip('/')!=(WEB+path).rstrip('/'):
                        await pg.goto(WEB+path,wait_until="networkidle",timeout=60000)
                    else:
                        await pg.keyboard.press("Escape")
                except Exception as e: clicked.append({"btn":lab,"fail":str(e)[:80]})
            rep[path]={"errors":errs[:20],"buttons":len(labels),"clicks":[c for c in clicked if c.get("new_errs") or c.get("ui")]}
            print(path,len(labels),len(errs),flush=True)
            await pg.close()
        await b.close()
    json.dump(rep,open("/data/out/interact2.json","w"),ensure_ascii=False,indent=1)
asyncio.run(main())
