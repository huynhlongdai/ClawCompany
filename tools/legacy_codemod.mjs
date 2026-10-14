// UI v2: chuyển class đời cũ (legacy.css) sang class của primitive components/ui (ui-*) + vài
// helper lab-* trong pages.css. Đọc AST (chỉ đụng chuỗi trong thuộc tính className), không regex mù.
// Lỗi dạng <div className="v8Error">{error}</div> → <ErrorBanner error={error}/> (có câu giải thích + cách xử lý).
// Chạy: node tools/legacy_codemod.mjs <file...>
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const MAP = {
  // khung
  "panel": "ui-panel", "panelHead": "ui-panel-head", "pad": "ui-panel-body",
  "v8Card": "ui-panel ui-panel-body", "hrPanel": "ui-panel ui-panel-body", "portalCard": "ui-panel ui-panel-body",
  "v8CardHead": "lab-cardhead", "portalCardHead": "lab-cardhead",
  // bảng
  "dataTable": "ui-table", "tmTable": "ui-table", "v8Table": "ui-table", "v14Table": "ui-table", "v10Table": "ui-table",
  "v8Th": "", "v8Tr": "", "v10TH": "", "v10TR": "", "tableWrap": "ui-table-wrap",
  // nhãn
  "tag": "ui-pill", "statusPill": "ui-pill", "prio": "ui-pill", "v9Status": "ui-pill", "sev": "ui-pill", "v8Risk": "ui-pill",
  "greenTag": "is-ok", "orangeTag": "is-wait", "redTag": "is-risk", "blueTag": "is-info",
  // nút
  "darkBtn": "ui-btn is-primary", "v8Primary": "ui-btn is-primary", "primary": "ui-btn is-primary",
  "ghost": "ui-btn", "v8Ghost": "ui-btn", "v9BudgetButton": "ui-btn",
  // trạng thái rỗng/lỗi
  "v8Empty": "ui-empty-line", "v9Empty": "ui-empty-line", "portalEmpty": "ui-empty-line",
  "v8Error": "ui-banner is-error", "portalError": "ui-banner is-error",
  // form + lưới
  "v9Form": "ui-form", "v8Form": "ui-form", "v10Compose": "ui-form", "v9FormRow": "ui-form-row",
  "v9Grid2": "ui-grid is-2", "v8Two": "ui-grid is-2", "v12Two": "ui-grid is-2", "v10Grid": "ui-grid is-2", "v13Split": "ui-grid is-2",
  "companyGrid": "ui-grid is-2", "portalGrid": "ui-grid is-2", "v9MemoryGrid": "ui-grid is-2", "v8JobGrid": "ui-grid is-3", "v10ArtifactGrid": "ui-grid is-2",
  // số liệu
  "v14Metrics": "lab-stats", "kpi4": "lab-stats", "metric5": "lab-stats", "v8Stats": "lab-stats",
  "metric": "lab-metric", "metricIcon": "lab-icon", "iconTile": "lab-icon", "v8Icon": "lab-icon", "v8BigMetric": "lab-big",
  // danh sách, dòng thời gian, tab
  "v9List": "ui-list", "v9LedgerRow": "ui-row", "v9Cycle": "ui-row", "v10Handoffs": "ui-list", "v10Trigger": "ui-row", "v10Message": "ui-row",
  "timeline": "lab-timeline", "timeRow": "lab-timerow", "progress": "ui-meter", "pillTabs": "ui-seg",
  "heroActions": "ui-toolbar", "divider": "lab-divider", "delta": "lab-delta", "person": "lab-person", "avatarSm": "ui-ava",
  "mono": "ui-mono", "muted": "lab-muted", "v8Checklist": "lab-check", "v8Flow": "lab-flowline", "v10ArtifactFlow": "lab-flowline",
  // bổ nghĩa
  "active": "is-active", "ok": "is-ok", "warn": "is-wait", "danger": "is-risk", "low": "is-low", "mid": "is-mid", "high": "is-high",
};

function mapTokens(text) {
  // giữ khoảng trắng đầu/cuối (ranh giới ${…} trong template)
  const lead = text.match(/^\s*/)[0], trail = text.match(/\s*$/)[0];
  const toks = text.trim().split(/\s+/).filter(Boolean);
  const out = [];
  for (const t of toks) {
    const m = Object.prototype.hasOwnProperty.call(MAP, t) ? MAP[t] : t;
    for (const x of m.split(/\s+/).filter(Boolean)) if (!out.includes(x)) out.push(x);
  }
  return lead + out.join(" ") + (out.length ? trail : (lead ? "" : trail));
}

for (const file of process.argv.slice(2)) {
  let src = fs.readFileSync(file, "utf8");
  // 1) lỗi thô → ErrorBanner
  let needBanner = false;
  src = src.replace(/<(div|p)\s+className="(?:v8Error|portalError)"((?:\s+data-testid="[^"]*")?)(?:\s+style=\{\{[^}]*\}\})?\s*>\{([\w.?]+)\}<\/\1>/g, (_, _t, tid, expr) => {
    needBanner = true;
    return `<ErrorBanner error={${expr}}${tid ? tid.replace("data-testid", " testId") : ""}/>`;
  });
  // 2) biến màu tên cũ trong style inline
  src = src.replace(/var\(--line\)/g, "var(--border)").replace(/var\(--muted\)/g, "var(--text-muted)")
    .replace(/var\(--cream\)/g, "var(--surface-2)").replace(/var\(--warn\)/g, "var(--wait)");
  // 3) className
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const edits = [];
  const visitInit = n => {
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) {
      const q = src[n.getStart()];
      edits.push({s: n.getStart() + 1, e: n.getEnd() - 1, t: mapTokens(n.text).replace(new RegExp(q, "g"), "\\" + q)});
      return;
    }
    if (ts.isTemplateExpression(n)) {
      const parts = [n.head, ...n.templateSpans.map(s => s.literal)];
      for (const p of parts) {
        const st = p.getStart(), en = p.getEnd();
        const raw = src.slice(st, en);
        const open = raw.startsWith("`") || raw.startsWith("}") ? 1 : 0;
        const close = raw.endsWith("${") ? 2 : raw.endsWith("`") ? 1 : 0;
        edits.push({s: st + open, e: en - close, t: mapTokens(raw.slice(open, raw.length - close))});
      }
      n.templateSpans.forEach(s => visitInit(s.expression));
      return;
    }
    // chỉ đi vào biểu thức điều kiện / nối chuỗi / mảng, không vào lời gọi hàm tuỳ ý
    if (ts.isConditionalExpression(n) || ts.isBinaryExpression(n) || ts.isParenthesizedExpression(n) || ts.isJsxExpression(n) || ts.isArrayLiteralExpression(n)) ts.forEachChild(n, visitInit);
    if (ts.isCallExpression(n) && /^(cx|cn|clsx)$/.test(n.expression.getText())) n.arguments.forEach(visitInit);
  };
  const walk = n => {
    if (ts.isJsxAttribute(n) && n.name.getText() === "className" && n.initializer) visitInit(n.initializer);
    ts.forEachChild(n, walk);
  };
  walk(sf);
  edits.sort((a, b) => b.s - a.s);
  for (const e of edits) src = src.slice(0, e.s) + e.t + src.slice(e.e);
  if (needBanner && !/\bErrorBanner\b.*from/.test(src)) {
    let rel = path.relative(path.dirname(file), path.resolve("components/ui/EmptyState")).replace(/\\/g, "/");
    if (!rel.startsWith(".")) rel = "./" + rel;
    const imports = [...src.matchAll(/^import[^\n]*from\s+["'][^"']+["'];?[^\n]*$/gm)];
    const at = imports.length ? imports[imports.length - 1].index + imports[imports.length - 1][0].length : 0;
    src = src.slice(0, at) + `\nimport {ErrorBanner} from "${rel}";` + src.slice(at);
  }
  fs.writeFileSync(file, src);
  console.log(`${file}: ${edits.length} className${needBanner ? " + ErrorBanner" : ""}`);
}
