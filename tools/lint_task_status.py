#!/usr/bin/env python3
"""D1.4 — chỉ ``app/services/task_lifecycle.py`` được ghi trạng thái task.

Đỏ (exit 1) khi tìm thấy ở chỗ khác trong ``backend/app``:
- phép gán ``<x>.status = ...`` / ``<x>.checkout_run_id = ...`` mà tên biến
  có chữ "task" (task, child_task, parent_task, t_task ...);
- ``setattr(<task>, "status", ...)``;
- ``update(Task).values(status=...)`` hoặc ``.values(checkout_run_id=...)``.

Tạo task mới với ``Task(status=...)`` vẫn được: đó là trạng thái ban đầu,
không phải một lần chuyển.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app"
OWNER = ROOT / "services" / "task_lifecycle.py"
GUARDED = {"status", "checkout_run_id"}


def _is_task_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return "task" in node.id.lower()
    if isinstance(node, ast.Attribute):
        return "task" in node.attr.lower()
    return False


def scan(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for tgt in targets:
            for t in (tgt.elts if isinstance(tgt, ast.Tuple) else [tgt]):
                if isinstance(t, ast.Attribute) and t.attr in GUARDED and _is_task_name(t.value):
                    hits.append(f"{path}:{node.lineno}: gán {ast.unparse(t)}")
        if isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id == "setattr" and len(node.args) >= 2
                    and _is_task_name(node.args[0]) and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in GUARDED):
                hits.append(f"{path}:{node.lineno}: setattr(..., {node.args[1].value!r})")
            if isinstance(fn, ast.Attribute) and fn.attr == "values":
                src = ast.unparse(fn.value)
                if "update(Task)" in src.replace(" ", "") and any(
                        k.arg in GUARDED for k in node.keywords):
                    hits.append(f"{path}:{node.lineno}: update(Task).values(status/checkout)")
    return hits


def main(root: Path = ROOT) -> int:
    hits: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.resolve() == OWNER.resolve():
            continue
        hits.extend(scan(path))
    for h in hits:
        print(h)
    if hits:
        print(f"\n{len(hits)} chỗ ghi trạng thái task ngoài task_lifecycle.py — "
              "hãy gọi task_lifecycle.transition/checkout/release.", file=sys.stderr)
        return 1
    print("lint_task_status: 0 chỗ ghi trạng thái task ngoài task_lifecycle.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
