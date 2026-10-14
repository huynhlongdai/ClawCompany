// M4b: chụp /app/inbox và /app/costs ở 1440px và 390px, ghi lỗi console/HTTP và tràn ngang; bấm Duyệt thật một thẻ.
// Chạy: node tools/shoot_m4b.mjs  (cần API :8000, web :3000, playwright trong NODE_PATH)
import {chromium} from "playwright";
const WEB = process.env.WEB || "http://127.0.0.1:3000", API = process.env.API || "http://127.0.0.1:8000";
const OUT = process.env.OUT || "docs/screenshots/m4b";
const login = await (await fetch(API + "/api/auth/login", {method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({email: "admin@clawcompany.local", password: "ChangeMe123!"})})).json();
const tok = login.access_token, rep = {};
const b = await chromium.launch({args: ["--no-sandbox"]});
for (const [W, H, tag] of [[1440, 900, ""], [390, 844, "-mobile"]]) {
  const ctx = await b.newContext({viewport: {width: W, height: H}, locale: "vi-VN"});
  await ctx.addInitScript(`localStorage.setItem('clawcompany_token','${tok}')`);
  const pg = await ctx.newPage(); const errs = [];
  pg.on("console", m => { if (m.type() === "error") errs.push(m.text().slice(0, 160)); });
  pg.on("response", r => { if (r.status() >= 400) errs.push(`HTTP ${r.status()} ${r.url().slice(-80)}`); });
  pg.on("pageerror", e => errs.push("PAGEERR " + String(e).slice(0, 160)));
  const shot = async (name, sel = "main") => {
    await pg.waitForTimeout(1500);
    const ov = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth");
    await pg.screenshot({path: `${OUT}/${name}${tag}.jpg`, type: "jpeg", quality: 70, fullPage: true});
    const txt = await pg.evaluate(s => (document.querySelector(s) || document.body).innerText.replace(/\s+/g, " ").slice(0, 500), sel);
    rep[name + tag] = {overflow_x: ov, errors: [...errs], text: txt}; errs.length = 0;
  };
  await pg.goto(WEB + "/app/inbox", {waitUntil: "networkidle", timeout: 90000}); await shot("inbox");
  await pg.goto(WEB + "/app/inbox?group=approvals", {waitUntil: "networkidle"}); await shot("inbox-approvals");
  if (tag) {
    await pg.getByRole("button", {name: "Từ chối"}).first().click(); await shot("inbox-reject");
    await pg.getByRole("button", {name: "Quay lại"}).first().click();
    const btn = pg.locator("[data-testid^=ibx-approve-]").first();
    await btn.click(); await shot("inbox-after-approve");
  }
  await pg.goto(WEB + "/app/costs", {waitUntil: "networkidle"}); await shot("costs-overview");
  await pg.goto(WEB + "/app/costs?tab=budgets", {waitUntil: "networkidle"}); await shot("costs-budgets");
  await pg.goto(WEB + "/app/approve", {waitUntil: "networkidle"}); await pg.waitForTimeout(1200);
  rep["approve-redirect" + tag] = pg.url();
  await ctx.close();
}
await b.close();
console.log(JSON.stringify(rep, null, 1));
