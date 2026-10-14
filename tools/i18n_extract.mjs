// Tách chuỗi tiếng Việt trong một file TSX/TS vào messages/vi.json và thay bằng t("ns.key").
// Dùng TypeScript compiler API (đọc AST, không regex mù):
//   - JsxText có chữ Việt            → {t("ns.k")}
//   - "chuỗi" / `chuỗi` có chữ Việt   → t("ns.k")   (thuộc tính JSX: attr={t("ns.k")})
//   - `… ${x} …` có chữ Việt          → t("ns.k", {p0: x})  với message "… {p0} …"
//   - chuỗi ở cấp module (ngoài mọi hàm) → bọc khai báo bằng lazy(() => (…)) để đọc theo locale lúc dùng
// Bỏ qua: import/export, tên thuộc tính, kiểu literal, className/href/key/id/data-*.
// Chạy: node tools/i18n_extract.mjs <namespace> <file> [--dry]
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const [ns, file, flag] = process.argv.slice(2);
if (!ns || !file) { console.error("dùng: node tools/i18n_extract.mjs <namespace> <file> [--dry]"); process.exit(2); }
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const VI = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;
const SKIP_ATTR = new Set(["className", "href", "key", "id", "src", "type", "name", "role", "rel", "target", "htmlFor", "inputMode", "autoComplete"]);

const src = fs.readFileSync(file, "utf8");
const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
const viPath = path.join(ROOT, "messages/vi.json");
const cat = JSON.parse(fs.readFileSync(viPath, "utf8"));
const bucket = cat[ns] || (cat[ns] = {});
const byText = new Map(Object.entries(bucket).map(([k, v]) => [v, k]));

function slug(text) {
  const s = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[đĐ]/g, "d").toLowerCase()
    .replace(/\{p\d+\}/g, " ").replace(/[^a-z0-9]+/g, " ").trim().split(/\s+/).slice(0, 5).join("_");
  return (s || "k").slice(0, 40).replace(/^(\d)/, "k$1");
}
function keyFor(text) {
  if (byText.has(text)) return byText.get(text);
  let base = slug(text), k = base, i = 2;
  while (bucket[k] !== undefined && bucket[k] !== text) k = `${base}_${i++}`;
  bucket[k] = text; byText.set(text, k); return k;
}

// tên `t` có bị khai báo trong file không (tham số, biến) → dùng bí danh
let shadow = false;
(function scan(n) {
  if ((ts.isParameter(n) || ts.isVariableDeclaration(n) || ts.isBindingElement(n)) && ts.isIdentifier(n.name) && n.name.text === "t") shadow = true;
  ts.forEachChild(n, scan);
})(sf);
const T = shadow ? "tr" : "t";

const edits = []; // {start, end, text}
const lazyWrap = new Map(); // VariableDeclaration → true
const warnings = [];
let count = 0, needLazy = false;

const isFn = n => ts.isArrowFunction(n) || ts.isFunctionExpression(n) || ts.isFunctionDeclaration(n) || ts.isMethodDeclaration(n) ||
  ts.isGetAccessor(n) || ts.isSetAccessor(n) || ts.isConstructorDeclaration(n);
function inFunction(n) { for (let p = n.parent; p; p = p.parent) if (isFn(p)) return true; return false; }
function topVarDecl(n) {
  for (let p = n.parent; p; p = p.parent) if (ts.isVariableDeclaration(p) && ts.isVariableStatement(p.parent?.parent) && p.parent.parent.parent === sf) return p;
  return null;
}
function inTypePos(n) { for (let p = n.parent; p; p = p.parent) { if (ts.isTypeNode(p) && !ts.isExpressionWithTypeArguments?.(p)) return true; if (ts.isStatement(p)) return false; } return false; }
function alreadyT(n) { const c = n.parent; return ts.isCallExpression(c) && ts.isIdentifier(c.expression) && (c.expression.text === "t" || c.expression.text === "tr"); }

function moduleLevel(n) {
  if (inFunction(n)) return true;
  const d = topVarDecl(n);
  if (!d || !d.initializer) { warnings.push(`cấp module, không bọc được: ${JSON.stringify(n.getText().slice(0, 60))}`); return false; }
  if (ts.isStringLiteral(d.initializer) || ts.isTemplateExpression(d.initializer) || ts.isNoSubstitutionTemplateLiteral(d.initializer)) {
    warnings.push(`hằng chuỗi cấp module (đổi tay): ${d.name.getText()}`); return false;
  }
  lazyWrap.set(d, true); needLazy = true; return true;
}

function visit(n) {
  if (ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) return;
  if (ts.isJsxText(n)) {
    const raw = n.getText();
    if (VI.test(raw) && !raw.includes("{") && !raw.includes("}")) {
      const lead = raw.match(/^\s*/)[0], trail = raw.match(/\s*$/)[0];
      const text = raw.trim().replace(/\s+/g, " ");
      if (text) { edits.push({start: n.getStart(), end: n.getEnd(), text: `${lead}{${T}("${ns}.${keyFor(text)}")}${trail}`}); count++; }
    }
    return;
  }
  if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) && VI.test(n.text)) {
    const p = n.parent;
    if (ts.isPropertyAssignment(p) && p.name === n) return;
    if (ts.isLiteralTypeNode(p) || inTypePos(n) || alreadyT(n)) return;
    if (ts.isJsxAttribute(p)) {
      const an = p.name.getText();
      if (SKIP_ATTR.has(an) || an.startsWith("data-")) return;
      if (!moduleLevel(n)) return;
      edits.push({start: n.getStart(), end: n.getEnd(), text: `{${T}("${ns}.${keyFor(n.text)}")}`}); count++; return;
    }
    if (!moduleLevel(n)) return;
    edits.push({start: n.getStart(), end: n.getEnd(), text: `${T}("${ns}.${keyFor(n.text)}")`}); count++;
    return;
  }
  if (ts.isTemplateExpression(n)) {
    const lits = [n.head.text, ...n.templateSpans.map(s => s.literal.text)];
    if (lits.some(x => VI.test(x)) && !alreadyT(n)) {
      if (!moduleLevel(n)) return;
      let msg = n.head.text; const vars = [];
      n.templateSpans.forEach((s, i) => { msg += `{p${i}}` + s.literal.text; vars.push(`p${i}: ${s.expression.getText()}`); });
      edits.push({start: n.getStart(), end: n.getEnd(), text: `${T}("${ns}.${keyFor(msg)}", {${vars.join(", ")}})`}); count++;
      return; // không đi vào biểu thức con (đã chép nguyên văn)
    }
  }
  ts.forEachChild(n, visit);
}
visit(sf);

for (const d of lazyWrap.keys()) {
  edits.push({start: d.initializer.getStart(), end: d.initializer.getStart(), text: "lazy(() => ("});
  edits.push({start: d.initializer.getEnd(), end: d.initializer.getEnd(), text: "))"});
}
// áp từ cuối lên đầu; chèn (start==end) đứng sau thay thế cùng vị trí
edits.sort((a, b) => b.start - a.start || (a.start === a.end ? -1 : 1));
let out = src;
for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);

if (count) {
  let rel = path.relative(path.dirname(file), path.join(ROOT, "lib/i18n")).replace(/\\/g, "/");
  if (!rel.startsWith(".")) rel = "./" + rel;
  const names = [shadow ? "t as tr" : "t", ...(needLazy ? ["lazy"] : [])];
  const imp = `import {${names.join(", ")}} from "${rel}";\n`;
  const imports = [...out.matchAll(/^import[\s\S]*?from\s+["'][^"']+["'];?\s*$/gm)];
  if (/^\s*["']use client["'];?/.test(out) || imports.length) {
    const last = imports.length ? imports[imports.length - 1] : out.match(/^\s*["']use client["'];?\n?/);
    const at = last.index + last[0].length;
    out = out.slice(0, at) + (out[at - 1] === "\n" ? "" : "\n") + imp + out.slice(at);
  } else out = imp + out;
}
if (flag !== "--dry") {
  fs.writeFileSync(file, out);
  fs.writeFileSync(viPath, JSON.stringify(cat, null, 1) + "\n");
}
console.log(`${file}: ${count} chuỗi → ${ns}${shadow ? " (bí danh tr)" : ""}${needLazy ? `, ${lazyWrap.size} hằng bọc lazy` : ""}`);
for (const w of warnings) console.log("  ! " + w);
