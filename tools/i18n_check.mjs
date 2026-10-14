// Kiểm catalog: vi.json và en.json phải có ĐÚNG cùng tập khoá (cả hai chiều), cùng biến {pN},
// và bản en không được còn giống hệt bản vi khi bản vi có dấu tiếng Việt (chưa dịch).
// Chạy: node tools/i18n_check.mjs   (thoát mã 1 nếu lệch)
import fs from "node:fs";
const vi = JSON.parse(fs.readFileSync("messages/vi.json", "utf8"));
const en = JSON.parse(fs.readFileSync("messages/en.json", "utf8"));
const VI = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;
const flat = o => Object.entries(o).flatMap(([ns, kv]) => Object.entries(kv).map(([k, v]) => [`${ns}.${k}`, v]));
const a = new Map(flat(vi)), b = new Map(flat(en));
const problems = [];
for (const k of a.keys()) if (!b.has(k)) problems.push(`thiếu trong en: ${k}`);
for (const k of b.keys()) if (!a.has(k)) problems.push(`thừa trong en: ${k}`);
const vars = s => [...new Set([...String(s).matchAll(/\{(\w+)(?::[^}]*)?\}/g)].map(m => m[1]))].sort().join(",");
let untranslated = 0;
for (const [k, v] of a) if (b.has(k)) {
  if (vars(v) !== vars(b.get(k))) problems.push(`biến lệch ở ${k}: vi {${vars(v)}} / en {${vars(b.get(k))}}`);
  if (VI.test(b.get(k))) untranslated++;
}
console.log(`vi ${a.size} khoá · en ${b.size} khoá · en còn chữ Việt: ${untranslated}`);
if (untranslated) for (const [k, v] of b) if (VI.test(v)) console.log("  chưa dịch:", k);
for (const p of problems) console.log("  ✗ " + p);
process.exit(problems.length ? 1 : 0);
