// UI v2 (lượt 2): chụp MỌI route + kiểm hành vi trên trình duyệt thật.
//   - lỗi console / pageerror / HTTP ≥ 400, tràn ngang (scrollWidth > innerWidth)
//   - LANG=vi: chữ tiếng Anh còn sót trong chữ HIỂN THỊ (bỏ code/pre/kbd/[translate=no]/.ui-mono — đó là id, tên riêng)
//   - LANG=en: chữ tràn khỏi nút/tab/chip (scrollWidth > clientWidth)
//   - 390px: thẻ cuối của Hộp việc không bị thanh điều hướng dưới che
// Chạy: NODE_PATH=/tmp/pw/node_modules node tools/shoot_ui_v2.mjs <light|dark> <desktop|mobile> [vi|en]
//   ONLY=tong-quan,hop-viec  CORE=1 (chỉ trang lõi)  OUT=docs/screenshots/ui-v2b
// Cần API :8000 (seed.py + tools/seed_ui_v2.py) và `next start` :3000.
import {chromium} from "playwright";
import fs from "node:fs";
const WEB = process.env.WEB || "http://127.0.0.1:3000", API = process.env.API || "http://127.0.0.1:8000";
const OUT = process.env.OUT || "docs/screenshots/ui-v2b";
const theme = process.argv[2] || "light", size = process.argv[3] || "desktop", lang = process.argv[4] || "vi";
const ONLY = process.env.ONLY ? process.env.ONLY.split(",") : null;
fs.mkdirSync(OUT, {recursive: true});
const post = async (path, body, tok) => (await fetch(API + path, {method: "POST", headers: {"Content-Type": "application/json", ...(tok ? {Authorization: `Bearer ${tok}`} : {})}, body: JSON.stringify(body)})).json().catch(() => ({}));
const tok = (await post("/api/auth/login", {email: "admin@clawcompany.local", password: "ChangeMe123!"})).access_token;
const ptok = (await post("/api/portal/auth/login", {email: "client@acme.local", password: "ChangeMe123!"})).access_token;
const inv = await post("/api/team/invitations", {email: `moi${Date.now() % 100000}@gommoc.vn`, role: "member", job_title: "Bán hàng"}, tok);

const CORE = [
  ["tong-quan", "/app/os"], ["hop-viec", "/app/inbox"], ["cong-viec-list", "/app/work"], ["cong-viec-board", "/app/work?view=board"],
  ["cong-viec-peek", "/app/work?peek=2"], ["cong-viec-du-an", "/app/work?view=projects"], ["chi-tiet-viec", "/app/tasks/2"],
  ["muc-tieu", "/app/goals"], ["ke-hoach", "/app/strategy"], ["nina", "/app/nina"],
  ["doi-ngu-so-do", "/app/team"], ["doi-ngu-agent", "/app/team?tab=ai"], ["doi-ngu-nguoi", "/app/team?tab=people"], ["doi-ngu-phong-ban", "/app/team?tab=departments"],
  ["doi-ngu-dao-tao", "/app/team?tab=training"], ["doi-ngu-dung", "/app/team?tab=build"],
  ["agent-ho-so", "/app/agents/4"], ["agent-nhan-su", "/app/agents/4?tab=hr"], ["agent-openclaw", "/app/agents/4?tab=openclaw"],
  ["viec-dinh-ky", "/app/routines"], ["quy-trinh", "/app/workflows"], ["chi-phi", "/app/costs"], ["chi-phi-ngan-sach", "/app/costs?tab=budgets"],
  ["cai-dat", "/app/settings"], ["openclaw", "/app/openclaw"], ["ky-nang", "/app/agent-tools"], ["bi-mat", "/app/secrets"], ["phong-thi-nghiem", "/app/settings/lab"],
  ["onboarding", "/onboarding"],
];
const MORE = ["collaboration", "communications", "artifacts", "quality", "live-runs", "events", "reports", "routing", "agents", "company-factory", "workspace-ops",
  "memory", "knowledge-mesh", "customers", "marketplace", "system", "approve", "budgets", "flow"].map(r => ["khac-" + r, "/app/" + r]);
const LAB = ["repositories", "delivery", "reviews", "cicd", "releases", "release-manager", "deployments", "progressive-delivery", "sandboxes", "workspaces",
  "workspace-gateway", "dev-cloud", "engineering", "portfolio", "runners", "sre-control", "incidents", "observability", "telemetry-federation", "trust",
  "supply-chain", "production-trust", "secrets-federation", "control-center", "founder-cockpit", "autonomy", "simulation"].map(r => ["lab-" + r, "/app/" + r]);
const PAGES = process.env.CORE ? CORE : [...CORE, ...MORE, ...LAB];

// Chữ UI tiếng Anh thường gặp (viết hoa, đứng riêng) — không bắt giá trị dữ liệu thô/id.
const EN = /\b(Create|Save|Cancel|Loading|Error|Settings|Status|Delete|Edit|Submit|Search|Refresh|Inspect|Register|Install|Approve|Reject|Overview|Dashboard|Pending|Failed|Running|Hire|Provision|Send|Back|Next|Close|Run now|Remember|Dispatch|Emit|Deploy|Assign|Request changes|Select|No [a-z]+ (?:yet|configured))\b/;
const scanEnglish = () => {
  const skip = el => el.closest("code,pre,kbd,script,style,[translate=no],.ui-mono,textarea,input,option,svg,[aria-hidden=true]");
  const out = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    const el = n.parentElement; if (!el || skip(el)) continue;
    const s = n.textContent.trim(); if (!s) continue;
    const r = el.getBoundingClientRect(); if (!r.width && !r.height) continue;
    if (window.__EN.test(s)) out.add(s.slice(0, 80));
  }
  for (const el of document.querySelectorAll("[placeholder],[aria-label],[title]")) {
    for (const a of ["placeholder", "aria-label", "title"]) { const v = el.getAttribute(a); if (v && window.__EN.test(v) && !skip(el.parentElement || el)) out.add(`${a}=${v.slice(0, 60)}`); }
  }
  return [...out];
};
const scanButtonOverflow = () => {
  const out = [];
  for (const el of document.querySelectorAll("button,a.ui-btn,.ui-tab,.ui-chip,.ui-pill,.ui-nav,.ui-seg > *")) {
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    if (el.scrollWidth > el.clientWidth + 1)
      out.push((el.innerText || el.getAttribute("aria-label") || "").trim().slice(0, 40) + ` (${el.scrollWidth}>${el.clientWidth})`);
  }
  return out.filter(x => !x.startsWith(" ")).slice(0, 8);
};

const rep = {};
const b = await chromium.launch({args: ["--no-sandbox"], ...(process.env.CHROME_PATH ? {executablePath: process.env.CHROME_PATH} : {})});
const [W, H] = size === "desktop" ? [1440, 900] : [390, 844];
const tag = `-${size === "desktop" ? "1440" : "390"}-${theme}${lang === "en" ? "-en" : ""}`;
const mk = async (auth) => {
  const ctx = await b.newContext({viewport: {width: W, height: H}, locale: lang === "en" ? "en-US" : "vi-VN", colorScheme: theme});
  await ctx.addCookies([{name: "cc_locale", value: lang, url: WEB}]);
  await ctx.addInitScript(`localStorage.setItem('cc_theme','${theme}');localStorage.setItem('cc_company','3');window.__EN=${EN};` +
    (auth ? `localStorage.setItem('clawcompany_token','${tok}');localStorage.setItem('clawcompany_portal_token','${ptok}');` : ""));
  return ctx;
};
const shootOne = async (ctx, name, url, opts = {}) => {
  const pg = await ctx.newPage(); const errs = [];
  pg.on("console", m => { if (m.type() === "error") errs.push(m.text().slice(0, 200)); });
  pg.on("response", r => { if (r.status() >= 400) errs.push(`HTTP ${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, "").slice(0, 90)}`); });
  pg.on("pageerror", e => errs.push("PAGEERR " + String(e).slice(0, 200)));
  try { await pg.goto(WEB + url, {waitUntil: "networkidle", timeout: 60000}); } catch (e) { errs.push("GOTO " + String(e).slice(0, 120)); }
  await pg.waitForTimeout(opts.wait || 1200);
  if (opts.act) { try { await opts.act(pg); await pg.waitForTimeout(700); } catch (e) { errs.push("ACT " + String(e).slice(0, 120)); } }
  const ov = await pg.evaluate("document.documentElement.scrollWidth - window.innerWidth");
  const english = lang === "vi" ? await pg.evaluate(scanEnglish) : [];
  const btnOverflow = await pg.evaluate(scanButtonOverflow);
  const htmlLang = await pg.evaluate(() => document.documentElement.lang);
  let navCover = null;
  if (size === "mobile" && name === "hop-viec") navCover = await pg.evaluate(async () => {
    window.scrollTo(0, document.documentElement.scrollHeight); await new Promise(r => setTimeout(r, 400));
    const nav = document.querySelector(".ui-bottomnav"); const cards = document.querySelectorAll(".ibx-card,.ibx-group > *,.ui-content > * > *:last-child");
    const last = cards[cards.length - 1]; if (!nav || !last) return "không đo được";
    return Math.round(last.getBoundingClientRect().bottom - nav.getBoundingClientRect().top); // > 0 = bị che
  });
  await pg.screenshot({path: `${OUT}/${name}${tag}.jpg`, type: "jpeg", quality: 70, fullPage: opts.full !== false});
  const h1 = await pg.evaluate(() => (document.querySelector("h1")?.textContent || "").trim().slice(0, 80));
  rep[name + tag] = {overflow_x: ov, errors: errs, english, btn_overflow: btnOverflow, html_lang: htmlLang, h1, ...(navCover !== null ? {inbox_last_card_under_nav_px: navCover} : {})};
  await pg.close();
};
const ctx = await mk(true);
for (const [name, url] of PAGES) if (!ONLY || ONLY.includes(name)) await shootOne(ctx, name, url);
if (!process.env.CORE) {
  for (const [name, url] of [["cong-khach", "/portal"], ["cong-khach-chat", "/portal/chat"]]) if (!ONLY || ONLY.includes(name)) await shootOne(ctx, name, url);
  if (!ONLY || ONLY.includes("palette")) await shootOne(ctx, "palette", "/app/os", {full: false, act: async pg => {
    if (size === "desktop") { await pg.keyboard.press("Control+k"); await pg.keyboard.type(lang === "en" ? "cost" : "chi phí"); } else await pg.locator("[data-testid=bnav-more]").click();
  }});
}
await ctx.close();
const anon = await mk(false);
if (!ONLY || ONLY.includes("dang-nhap")) await shootOne(anon, "dang-nhap", "/app/inbox", {full: false});
if ((!ONLY || ONLY.includes("loi-moi")) && inv?.invite_path) await shootOne(anon, "loi-moi", inv.invite_path, {full: false});
await anon.close();
await b.close();
const file = `${OUT}/report${tag}.json`;
// ONLY=...: gộp vào báo cáo cũ (chụp lại vài trang không xoá kết quả các trang khác).
if (ONLY && fs.existsSync(file)) { const old = JSON.parse(fs.readFileSync(file, "utf8")); for (const k of Object.keys(rep)) old[k] = rep[k]; Object.assign(rep, old, rep); }
fs.writeFileSync(file, JSON.stringify(rep, null, 1));
const bad = Object.entries(rep).filter(([, v]) => v.errors.length || v.overflow_x > 0 || v.english.length || v.btn_overflow.length || v.html_lang !== lang || v.inbox_last_card_under_nav_px > 0);
console.log(`${Object.keys(rep).length} ảnh${tag}; có vấn đề: ${bad.length}`);
for (const [k, v] of bad) console.log(k, "ov=" + v.overflow_x, "lang=" + v.html_lang, v.errors.slice(0, 2).join(" | "), v.english.length ? "EN:" + v.english.slice(0, 4).join(" / ") : "",
  v.btn_overflow.length ? "BTN:" + v.btn_overflow.slice(0, 3).join(" / ") : "", v.inbox_last_card_under_nav_px > 0 ? "NAV che " + v.inbox_last_card_under_nav_px + "px" : "");
