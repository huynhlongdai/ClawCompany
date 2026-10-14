// UI v2: chụp mọi trang lõi ở 1440px và 390px, sáng + tối; ghi lỗi console/HTTP và tràn ngang.
// Chạy: NODE_PATH=/tmp/pw/node_modules node tools/shoot_ui_v2.mjs [light|dark] [desktop|mobile]
// Cần API :8000 (seed.py + tools/seed_ui_v2.py) và `next start` :3000 build với NEXT_PUBLIC_AUTH_REQUIRED=true.
import {chromium} from "playwright";
import fs from "node:fs";
const WEB = process.env.WEB || "http://127.0.0.1:3000", API = process.env.API || "http://127.0.0.1:8000";
const OUT = process.env.OUT || "docs/screenshots/ui-v2";
const themes = process.argv[2] ? [process.argv[2]] : ["light", "dark"];
const sizes = process.argv[3] ? [process.argv[3]] : ["desktop", "mobile"];
const ONLY = process.env.ONLY ? process.env.ONLY.split(",") : null;
fs.mkdirSync(OUT, {recursive: true});
const tok = (await (await fetch(API + "/api/auth/login", {method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({email: "admin@clawcompany.local", password: "ChangeMe123!"})})).json()).access_token;
const inv = await (await fetch(API + "/api/team/invitations", {method: "POST", headers: {"Content-Type": "application/json", Authorization: `Bearer ${tok}`},
  body: JSON.stringify({email: `moi${Date.now() % 100000}@gommoc.vn`, role: "member", job_title: "Bán hàng"})})).json().catch(() => ({}));
const PAGES = [
  ["tong-quan", "/app/os"], ["hop-viec", "/app/inbox"], ["cong-viec-list", "/app/work"], ["cong-viec-board", "/app/work?view=board"],
  ["cong-viec-peek", "/app/work?peek=2"], ["cong-viec-du-an", "/app/work?view=projects"], ["muc-tieu", "/app/goals"], ["ke-hoach", "/app/strategy"],
  ["nina", "/app/nina"], ["doi-ngu-so-do", "/app/team"], ["doi-ngu-agent", "/app/team?tab=ai"], ["doi-ngu-nguoi", "/app/team?tab=people"],
  ["doi-ngu-dao-tao", "/app/team?tab=training"], ["agent-ho-so", "/app/agents/4"], ["viec-dinh-ky", "/app/routines"], ["quy-trinh", "/app/workflows"],
  ["chi-phi", "/app/costs"], ["chi-phi-ngan-sach", "/app/costs?tab=budgets"], ["openclaw", "/app/openclaw"], ["cai-dat", "/app/settings"],
  ["phong-thi-nghiem", "/app/settings/lab"], ["ky-nang", "/app/agent-tools"], ["bi-mat", "/app/secrets"], ["onboarding", "/onboarding"],
  ["lab-repositories", "/app/repositories"], ["lab-control-center", "/app/control-center"], ["khac-su-kien", "/app/events"], ["khac-phong-hop", "/app/collaboration"],
  ["chi-tiet-viec", "/app/tasks/2"], ["danh-ba", "/app/system"],
];
const rep = {};
const b = await chromium.launch({args: ["--no-sandbox"]});
for (const theme of themes) for (const size of sizes) {
  const [W, H] = size === "desktop" ? [1440, 900] : [390, 844];
  const tag = `-${size === "desktop" ? "1440" : "390"}-${theme}`;
  const shootOne = async (ctx, name, url, opts = {}) => {
    const pg = await ctx.newPage(); const errs = [];
    pg.on("console", m => { if (m.type() === "error") errs.push(m.text().slice(0, 200)); });
    pg.on("response", r => { if (r.status() >= 400) errs.push(`HTTP ${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, "").slice(0, 90)}`); });
    pg.on("pageerror", e => errs.push("PAGEERR " + String(e).slice(0, 200)));
    try { await pg.goto(WEB + url, {waitUntil: "networkidle", timeout: 60000}); } catch (e) { errs.push("GOTO " + String(e).slice(0, 120)); }
    await pg.waitForTimeout(opts.wait || 1300);
    if (opts.act) { try { await opts.act(pg); await pg.waitForTimeout(700); } catch (e) { errs.push("ACT " + String(e).slice(0, 120)); } }
    const ov = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth");
    await pg.screenshot({path: `${OUT}/${name}${tag}.jpg`, type: "jpeg", quality: 72, fullPage: opts.full !== false});
    const h1 = await pg.evaluate(() => (document.querySelector("h1")?.textContent || "").trim().slice(0, 80));
    rep[name + tag] = {overflow_x: ov, errors: errs, h1};
    await pg.close();
  };
  const ctx = await b.newContext({viewport: {width: W, height: H}, locale: "vi-VN", colorScheme: theme});
  await ctx.addInitScript(`localStorage.setItem('clawcompany_token','${tok}');localStorage.setItem('cc_theme','${theme}');localStorage.setItem('cc_company','3');`);
  for (const [name, url] of PAGES) { if (!ONLY || ONLY.includes(name)) await shootOne(ctx, name, url); }
  if (!ONLY || ONLY.includes("palette")) await shootOne(ctx, "palette", "/app/os", {full: false, act: async pg => {
    if (size === "desktop") await pg.keyboard.press("Control+k"); else await pg.locator("[data-testid=bnav-more]").click();
    if (size === "desktop") await pg.keyboard.type("chi phí");
  }});
  await ctx.close();
  const anon = await b.newContext({viewport: {width: W, height: H}, locale: "vi-VN", colorScheme: theme});
  await anon.addInitScript(`localStorage.setItem('cc_theme','${theme}');`);
  if (!ONLY || ONLY.includes("dang-nhap")) await shootOne(anon, "dang-nhap", "/app/inbox", {full: false});
  if ((!ONLY || ONLY.includes("loi-moi")) && inv?.invite_path) await shootOne(anon, "loi-moi", inv.invite_path, {full: false});
  await anon.close();
}
await b.close();
const file = `${OUT}/report-${themes.join("_")}-${sizes.join("_")}.json`;
fs.writeFileSync(file, JSON.stringify(rep, null, 1));
const bad = Object.entries(rep).filter(([, v]) => v.errors.length || v.overflow_x > 0);
console.log(`${Object.keys(rep).length} ảnh; có vấn đề: ${bad.length}`);
for (const [k, v] of bad) console.log(k, "ov=" + v.overflow_x, v.errors.slice(0, 3).join(" | "));
