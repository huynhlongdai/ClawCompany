#!/usr/bin/env python3
"""Kiểm kê tĩnh codebase ClawCompany: endpoint, model/table, bridge tool, test.

Chỉ đọc file, không import app -> chạy được cả khi chưa cài dependency.
Xuất Markdown ra stdout.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "backend/app/api"
MODELS = ROOT / "backend/app/models"
SERVICES = ROOT / "backend/app/services"
TESTS = ROOT / "backend/tests"
BRIDGE = ROOT / "openclaw-company-bridge/tool-contracts.json"

ROUTE_RE = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']')
PREFIX_RE = re.compile(r'APIRouter\((.*?)\)', re.S)
TABLE_RE = re.compile(r'__tablename__\s*=\s*["\']([^"\']+)["\']')
CLASS_RE = re.compile(r'^class\s+(\w+)\(', re.M)
TESTFN_RE = re.compile(r'^\s*def (test_\w+)', re.M)
INCLUDE_RE = re.compile(r'app\.include_router\(\s*(\w+)_router\s*,\s*prefix="([^"]*)"')


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def api_inventory():
    rows = []
    for f in sorted(API.glob("*.py")):
        src = read(f)
        m = PREFIX_RE.search(src)
        prefix = ""
        if m:
            pm = re.search(r'prefix="([^"]*)"', m.group(1))
            if pm:
                prefix = pm.group(1)
        routes = ROUTE_RE.findall(src)
        verbs = Counter(v.upper() for v, _ in routes)
        rows.append({
            "file": f.name,
            "prefix": prefix,
            "endpoints": len(routes),
            "verbs": dict(verbs),
            "lines": src.count("\n") + 1,
            "paths": [f"{v.upper()} /api{prefix}{p}" for v, p in routes],
        })
    return rows


def model_inventory():
    out = []
    for f in sorted(MODELS.glob("*.py")):
        src = read(f)
        tables = TABLE_RE.findall(src)
        out.append({"file": f.name, "tables": tables, "classes": len(CLASS_RE.findall(src))})
    return out


def service_inventory():
    out = []
    for f in sorted(SERVICES.glob("*.py")):
        src = read(f)
        out.append({
            "file": f.name,
            "lines": src.count("\n") + 1,
            "defs": len(re.findall(r'^def \w+', src, re.M)),
            "classes": len(CLASS_RE.findall(src)),
        })
    return out


def test_inventory():
    out = []
    for f in sorted(TESTS.glob("test_*.py")):
        src = read(f)
        out.append({"file": f.name, "tests": len(TESTFN_RE.findall(src)), "lines": src.count("\n") + 1})
    return out


def bridge_inventory():
    data = json.loads(read(BRIDGE))
    tools = data.get("tools", [])
    names = [t.get("name", "?") for t in tools]
    groups = Counter(n.split(".")[1] if n.count(".") >= 1 else n for n in names)
    return data, names, groups


def cross_check(names, api_rows):
    """Bridge tool khai báo endpoint nào? Endpoint đó có tồn tại không?"""
    all_paths = set()
    for r in api_rows:
        for p in r["paths"]:
            all_paths.add(p)
    data = json.loads(read(BRIDGE))
    missing, checked = [], 0
    for t in data.get("tools", []):
        ep = t.get("path") or t.get("endpoint") or t.get("route")
        method = (t.get("method") or "").upper()
        if not ep:
            continue
        checked += 1
        ep_norm = re.sub(r"\{[^}]+\}", "{}", ep)
        found = any(re.sub(r"\{[^}]+\}", "{}", p) == f"{method} {ep_norm}" for p in all_paths)
        if not found:
            missing.append(f"{t.get('name')} -> {method} {ep}")
    return checked, missing


def main():
    api_rows = api_inventory()
    models = model_inventory()
    services = service_inventory()
    tests = test_inventory()
    bdata, names, groups = bridge_inventory()
    checked, missing = cross_check(names, api_rows)

    total_ep = sum(r["endpoints"] for r in api_rows)
    total_tests = sum(t["tests"] for t in tests)
    tables = sorted({t for m in models for t in m["tables"]})

    P = print
    P("# Kiểm kê ClawCompany (sinh tự động bởi tools/inventory.py)\n")
    P(f"- Router file: **{len(api_rows)}** · endpoint: **{total_ep}**")
    P(f"- Model file: **{len(models)}** · bảng (`__tablename__`): **{len(tables)}**")
    P(f"- Service module: **{len(services)}** · tổng dòng: **{sum(s['lines'] for s in services)}**")
    P(f"- Test file: **{len(tests)}** · hàm test: **{total_tests}**")
    P(f"- Bridge tool contract: **{len(names)}**\n")

    P("## Endpoint theo router\n")
    P("| File | Prefix | Endpoint | Dòng |")
    P("| --- | --- | --- | --- |")
    for r in api_rows:
        P(f"| `{r['file']}` | `{r['prefix'] or '-'}` | {r['endpoints']} | {r['lines']} |")

    P("\n## Bảng dữ liệu theo model file\n")
    P("| File | Số bảng | Tên bảng |")
    P("| --- | --- | --- |")
    for m in models:
        P(f"| `{m['file']}` | {len(m['tables'])} | {', '.join(f'`{t}`' for t in m['tables']) or '-'} |")

    P("\n## Test theo file\n")
    P("| File | Hàm test | Dòng |")
    P("| --- | --- | --- |")
    for t in tests:
        P(f"| `{t['file']}` | {t['tests']} | {t['lines']} |")

    P("\n## Bridge tool: nhóm theo namespace\n")
    P("| Nhóm | Số tool |")
    P("| --- | --- |")
    for g, c in groups.most_common():
        P(f"| `{g}` | {c} |")

    P("\n## Đối chiếu bridge tool với endpoint thật\n")
    P(f"- Tool có khai báo endpoint: **{checked}/{len(names)}**")
    P(f"- Tool trỏ tới endpoint **không tìm thấy trong code**: **{len(missing)}**\n")
    if missing:
        for m in missing[:60]:
            P(f"- `{m}`")
        if len(missing) > 60:
            P(f"- … còn {len(missing)-60} dòng nữa")

    P("\n## 15 service module lớn nhất\n")
    P("| File | Dòng | def | class |")
    P("| --- | --- | --- | --- |")
    for s in sorted(services, key=lambda x: -x["lines"])[:15]:
        P(f"| `{s['file']}` | {s['lines']} | {s['defs']} | {s['classes']} |")


if __name__ == "__main__":
    main()
