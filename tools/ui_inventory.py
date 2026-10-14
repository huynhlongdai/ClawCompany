"""Kiểm kê UI v2: mọi route (app/**/page.tsx) → component nó kéo vào (đệ quy, chỉ file
trong repo) → class nào còn lấy từ app/styles/legacy.css và chuỗi tiếng Anh nào còn
trong JSX. In bảng Markdown (stdout) để dán vào _reports/ui-v2.md.

Chạy: python3 tools/ui_inventory.py [--json]
Đây là kiểm kê tĩnh (đọc source) để biết còn phải làm gì — không thay cho kiểm
bằng trình duyệt (tools/shoot_ui_v2.mjs quét chữ hiển thị thật).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY = os.path.join(ROOT, "app/styles/legacy.css")


def legacy_classes():
    if not os.path.exists(LEGACY):
        return set()
    css = re.sub(r"/\*.*?\*/", "", open(LEGACY, encoding="utf-8").read(), flags=re.S)
    return set(re.findall(r"\.([a-zA-Z][a-zA-Z0-9_-]*)", css))


IMPORT = re.compile(r"""import\s+[^;]*?from\s+["']([^"']+)["']""", re.S)


def resolve(src, spec):
    if spec.startswith("@/"):
        base = os.path.join(ROOT, spec[2:])
    elif spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(src), spec))
    else:
        return None
    for ext in ("", ".tsx", ".ts", "/index.tsx", "/index.ts"):
        if os.path.isfile(base + ext):
            return base + ext
    return None


def walk(path, seen):
    if path in seen:
        return
    seen.add(path)
    txt = open(path, encoding="utf-8").read()
    for spec in IMPORT.findall(txt):
        r = resolve(path, spec)
        if r and r.endswith(".tsx"):
            walk(r, seen)


CLASS = re.compile(r"""className=(?:"([^"]*)"|\{`([^`]*)`\}|\{"([^"]*)"\})""")
EN = re.compile(r"\b(Create|Save|Cancel|Loading|Error|Settings|Status|Delete|Edit|Submit|Search|Select|Name|Approve|Reject|Run|Open|Close|No |Add|Update|Refresh|Inspect|Register|Policy|Queue|Pending|Active|Owner|Created)\b")


def scan(path, legacy):
    txt = open(path, encoding="utf-8").read()
    used = set()
    for m in CLASS.finditer(txt):
        s = next(g for g in m.groups() if g is not None)
        s = re.sub(r"\$\{[^}]*\}", " ", s)
        used.update(s.split())
    # className={cond?"a":"b"} và cx("a", …)
    for m in re.finditer(r"""className=\{[^}]*\}""", txt):
        used.update(re.findall(r'"([a-zA-Z][a-zA-Z0-9_-]*)"', m.group(0)))
    leg = sorted(c for c in used if c in legacy and not c.startswith("ui-"))
    # chữ trong JSX: >text< không chứa { }
    texts = [t.strip() for t in re.findall(r">([^<>{}]+)<", txt) if re.search(r"[A-Za-z]{3,}", t)]
    en = sorted({t for t in texts if EN.search(t) and not re.search(r"[À-ỹđĐ]", t)})
    return leg, en


def main():
    legacy = legacy_classes()
    rows = []
    for d, _, files in os.walk(os.path.join(ROOT, "app")):
        if "page.tsx" in files:
            page = os.path.join(d, "page.tsx")
            route = "/" + os.path.relpath(d, os.path.join(ROOT, "app")).replace(os.sep, "/")
            route = route.replace("/.", "") or "/"
            seen = set()
            walk(page, seen)
            comps = sorted(p for p in seen if "/components/" in p and "/components/ui/" not in p and "/components/shell/" not in p)
            leg, en = set(), set()
            per = {}
            for p in seen:
                l, e = scan(p, legacy)
                if l:
                    per[os.path.relpath(p, ROOT)] = l
                leg.update(l); en.update(e)
            rows.append({"route": "/" if route == "/." else route, "components": [os.path.relpath(p, ROOT) for p in comps],
                         "legacy_classes": sorted(leg), "legacy_by_file": per, "english_texts": sorted(en)[:12]})
    rows.sort(key=lambda r: r["route"])
    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1)); return
    print(f"legacy.css: {os.path.getsize(LEGACY) if os.path.exists(LEGACY) else 0} byte, {len(legacy)} class\n")
    print("| Route | Class legacy còn dùng | Chuỗi tiếng Anh (tĩnh) | Trạng thái |")
    print("|---|---|---|---|")
    for r in rows:
        ok = not r["legacy_classes"] and not r["english_texts"]
        print(f"| `{r['route']}` | {len(r['legacy_classes'])} | {len(r['english_texts'])} | {'mới' if ok else 'cũ'} |")


if __name__ == "__main__":
    main()
