// Đo độ phủ i18n theo file/trang: số lời gọi t()/tr() (đã tách) và số chuỗi tiếng Việt CÒN
// viết cứng (JSX text, thuộc tính, string literal — bỏ comment, bỏ chuỗi nằm trong t(...),
// bỏ chuỗi dùng làm khoá/so sánh). Chạy: node tools/i18n_coverage.mjs [--json]
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const VI = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;
const GROUPS = {
  "Shell / nav / ⌘K": ["components/shell", "lib/nav.ts", "components/LanguageSwitcher.tsx"],
  "components/ui": ["components/ui"],
  "lib/errors.ts + labels": ["lib/errors.ts", "lib/labels.ts", "app/error.tsx", "app/not-found.tsx", "app/app/error.tsx"],
  "Đăng nhập / lời mời": ["components/AuthGate.tsx", "app/invite"],
  "Onboarding": ["components/onboarding", "app/onboarding"],
  "Tổng quan": ["components/overview"],
  "Hộp việc": ["components/InboxHub.tsx", "components/QuickApprove.tsx", "app/app/inbox"],
  "Công việc + chi tiết việc": ["components/WorkBoard.tsx", "components/TaskDetail.tsx", "components/TaskGraphPanels.tsx", "components/TaskPolicyPanel.tsx", "app/app/tasks"],
  "Mục tiêu & Kế hoạch": ["components/GoalsConsole.tsx", "components/StrategyConsole.tsx", "components/NinaPlannerConsole.tsx"],
  "Đội ngũ + hồ sơ agent": ["components/TeamConsole.tsx", "components/AgentHR.tsx", "components/SeatProfile.tsx", "components/AgentDetail.tsx", "components/AgentProfile.tsx", "app/app/agents"],
  "Việc định kỳ / quy trình": ["components/RoutinesConsole.tsx", "components/WorkflowBuilderConsole.tsx"],
  "Chi phí": ["components/CostsBoard.tsx", "components/BudgetsConsole.tsx"],
  "Cài đặt (OpenClaw, kỹ năng, bí mật, lab)": ["components/settings", "components/OpenClawControl.tsx", "components/AgentToolsConsole.tsx", "components/SecretsConsole.tsx"],
  "Cổng khách hàng": ["components/CustomerPortal.tsx", "components/CustomerChat.tsx"],
  "Phòng thí nghiệm + trang phụ (không bắt buộc)": ["components/lab", "components/InboxConsole.tsx", "components/WorkforceConsole.tsx", "components/CompanyFactoryConsole.tsx", "components/EventAutomationConsole.tsx", "components/ArtifactHandoffConsole.tsx", "components/AgentMessageBusConsole.tsx", "components/QualitySLAConsole.tsx", "components/MemoryConsole.tsx", "components/LiveRunsConsole.tsx", "components/ReportsConsole.tsx", "components/RoutingConsole.tsx", "components/CustomersConsole.tsx", "components/MarketplaceConsole.tsx", "components/WorkspaceOpsConsole.tsx", "components/CollaborationFabricConsole.tsx", "components/KnowledgeMeshConsole.tsx"],
};
const exists = p => fs.existsSync(p);
const walk = p => !exists(p) ? [] : fs.statSync(p).isDirectory() ? fs.readdirSync(p).flatMap(f => walk(path.join(p, f))) : /\.(tsx?|jsx?)$/.test(p) ? [p] : [];

function scan(file) {
  const src = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  let calls = 0; const hard = [];
  const inT = n => { for (let p = n.parent; p; p = p.parent) if (ts.isCallExpression(p) && /^(t|tr)$/.test(p.expression.getText())) return true; return false; };
  const ignorable = n => {
    const p = n.parent;
    if (!p) return false;
    if (ts.isImportDeclaration(p) || ts.isExportDeclaration(p)) return true;
    if (ts.isBinaryExpression(p) && /^(===|!==|==|!=)$/.test(p.operatorToken.getText())) return true;
    if (ts.isPropertyAssignment(p) && p.name === n) return true;
    if (ts.isElementAccessExpression(p)) return true;
    if (ts.isCaseClause(p)) return true;
    return false;
  };
  const visit = n => {
    if (ts.isCallExpression(n) && /^(t|tr)$/.test(n.expression.getText()) && n.arguments[0] && ts.isStringLiteral(n.arguments[0])) calls++;
    if (ts.isJsxText(n) && VI.test(n.text) && n.text.trim()) hard.push(n.text.trim().slice(0, 60));
    if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && VI.test(n.text) && !inT(n) && !ignorable(n)) hard.push(n.text.slice(0, 60));
    if (ts.isTemplateExpression(n) && VI.test(n.getText()) && !inT(n)) hard.push(n.getText().slice(1, 61));
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return {calls, hard};
}

const out = [];
let tc = 0, th = 0;
for (const [g, paths] of Object.entries(GROUPS)) {
  const files = [...new Set(paths.flatMap(walk))];
  let c = 0, h = 0; const samples = [];
  for (const f of files) { const r = scan(f); c += r.calls; h += r.hard.length; if (r.hard.length) samples.push(`${f}: ${r.hard.slice(0, 3).join(" | ")}`); }
  const optional = g.includes("không bắt buộc");
  if (!optional) { tc += c; th += h; }
  out.push({group: g, files: files.length, extracted: c, hardcoded: h, pct: c + h ? Math.round(1000 * c / (c + h)) / 10 : 100, optional, samples: samples.slice(0, 6)});
}
const total = {extracted: tc, hardcoded: th, pct: Math.round(1000 * tc / (tc + th)) / 10};
if (process.argv.includes("--json")) console.log(JSON.stringify({groups: out, total}, null, 1));
else {
  for (const r of out) console.log(`${String(r.pct).padStart(5)}%  ${String(r.extracted).padStart(4)} tách / ${String(r.hardcoded).padStart(3)} còn cứng  ${r.group}`);
  console.log(`TỔNG (bắt buộc): ${total.pct}% — ${tc} chuỗi qua t(), ${th} chuỗi tiếng Việt còn viết cứng`);
}
