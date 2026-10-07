import asyncio, json, urllib.request
from playwright.async_api import async_playwright
WEB="http://127.0.0.1:3000"; API="http://127.0.0.1:8000"
CH="/vercel/sandbox/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome"
OUT="/data/cc/_shots/m4a"; PEEK=14
def login():
    r=urllib.request.Request(API+"/api/auth/login",data=json.dumps({"email":"admin@clawcompany.local","password":"ChangeMe123!"}).encode(),headers={"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(r))["access_token"]
async def main():
    tok=login(); rep={}
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path=CH,args=["--no-sandbox"])
        for W,H,tag in ((1440,900,""),(390,844,"-mobile")):
            ctx=await b.new_context(viewport={"width":W,"height":H},locale="vi-VN")
            await ctx.add_init_script(f"localStorage.setItem('clawcompany_token','{tok}')")
            pg=await ctx.new_page(); errs=[]
            pg.on("console",lambda m: errs.append(m.text[:160]) if m.type=="error" else None)
            pg.on("response",lambda r: errs.append(f"HTTP {r.status} {r.url[-90:]}") if r.status>=400 else None)
            pg.on("pageerror",lambda e: errs.append("PAGEERR "+str(e)[:160]))
            async def shot(name, full=False):
                await pg.wait_for_timeout(1200)
                ov=await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                await pg.screenshot(path=f"{OUT}/{name}{tag}.png",full_page=full)
                txt=await pg.evaluate("(document.querySelector('.wkModal')||document.querySelector('.wkPeek')||document.querySelector('.wkPage')||document.body).innerText.replace(/\\s+/g,' ').slice(0,420)")
                rep[name+tag]={"overflow_x":ov,"errors":list(errs),"text":txt}; errs.clear()
            await pg.goto(WEB+"/app/work",wait_until="networkidle",timeout=90000); await shot("work-list")
            await pg.goto(WEB+"/app/work?view=board",wait_until="networkidle"); await shot("work-board")
            await pg.goto(WEB+f"/app/work?peek={PEEK}",wait_until="networkidle"); await shot("peek-timeline")
            await pg.locator("[data-testid=wk-tab-review]").click(); await shot("peek-review")
            await pg.keyboard.press("Escape"); await pg.wait_for_timeout(1500)
            await pg.goto(WEB+"/app/work",wait_until="networkidle"); await pg.wait_for_timeout(800)
            await pg.get_by_role("button",name="Tạo việc").first.click(); await shot("create")
            await ctx.close()
        await b.close()
    print(json.dumps(rep,ensure_ascii=False,indent=1))
asyncio.run(main())
