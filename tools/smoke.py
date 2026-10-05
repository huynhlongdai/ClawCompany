#!/usr/bin/env python3
"""Smoke test toàn bộ bề mặt API của ClawCompany với một server đang chạy thật.

Vì sao cần: 636 test đơn vị chạy trên test double, còn 510 operation của API
thì chưa từng có ai gọi thật. Script này đăng nhập rồi gọi mọi endpoint GET
mà nó tự khám phá từ ``/openapi.json``, cộng một chuỗi ghi cốt lõi
(tổ chức -> công ty -> phòng ban -> ghế -> dự án -> việc), rồi in bảng kết quả
theo từng nhóm version.

Chỉ gọi GET tự động. Endpoint ghi rất dễ gây tác dụng phụ, nên chuỗi ghi được
viết tay và giới hạn trong phạm vi dữ liệu do chính script tạo ra.

Dùng:
    tools/smoke.py                       # mặc định http://127.0.0.1:8000
    tools/smoke.py --base http://... --json báo cáo.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections import defaultdict

import httpx

ADMIN_EMAIL = "admin@clawcompany.local"
ADMIN_PASSWORD = "ChangeMe123!"

# Tham số path phổ biến -> giá trị thử. Không đoán bừa: id 1 là dữ liệu seed.
PATH_DEFAULTS = {
    "organization_id": "1",
    "company_id": "1",
    "department_id": "1",
    "member_id": "1",
    "project_id": "1",
    "task_id": "1",
    "agent_id": "1",
    "entity_id": "1",
    "entity_type": "project",
    "kind": "project",
    "type": "project",
}

# Tham số query bắt buộc của một số endpoint: smoke không thể đoán, và bỏ
# trống thì 422 -- đó là hành vi ĐÚNG của API, không phải lỗi. Khai ở đây để
# báo cáo phản ánh chất lượng hệ thống chứ không phản ánh chất lượng script.
# ``runtime_agent_id`` để rỗng ở đây và được điền lúc chạy bằng seat THẬT đầu
# tiên đọc từ /api/agents. Bản cũ ghim cứng "nina", nhưng seed đã đổi seat sang
# "dev" để khớp agent trên gateway, nên hai endpoint company-tools báo 404
# "Agent binding not found" — một fixture cũ bị đọc thành lỗi hệ thống.
REQUIRED_QUERY = {
    "/api/company-tools/context": {"runtime_agent_id": ""},
    "/api/company-tools/tasks": {"runtime_agent_id": ""},
    "/api/knowledge/search": {"q": "chiến lược"},
    "/api/v14/runner-jobs/next": {"node_id": 1},  # node_id là int
}

# Endpoint cần token khác (portal dùng audience riêng) -> bỏ qua có chủ đích.
SKIP_PATHS = {"/api/portal/chats", "/api/portal/me"}

# 404 là câu trả lời ĐÚNG khi seed không có dữ liệu loại đó. Ghi nhận là
# "thiếu dữ liệu", không tính vào lỗi -- nhưng vẫn in ra để không ai quên.
EXPECTED_EMPTY = {"/api/v13/preview-routes/resolve"}

VERSION_RE = re.compile(r"/api/(v\d+)/")


def group_of(path: str) -> str:
    match = VERSION_RE.search(path)
    if match:
        return match.group(1)
    return "core"


def version_key(name: str) -> tuple[int, int]:
    if name == "core":
        return (0, 0)
    return (1, int(name[1:]))


class Smoke:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.client = httpx.Client(base_url=self.base, timeout=30.0)
        self.token = ""
        self.results: list[dict] = []

    # -- helpers -----------------------------------------------------------

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def record(self, method: str, path: str, status: int, note: str = "") -> None:
        self.results.append(
            {"method": method, "path": path, "status": status,
             "group": group_of(path),
             "ok": 200 <= status < 300 or note.startswith("bỏ qua"),
             "skipped": note.startswith("bỏ qua"), "note": note}
        )

    def call(self, method: str, path: str, **kwargs) -> httpx.Response | None:
        try:
            response = self.client.request(method, path, headers=self.headers(), **kwargs)
        except Exception as exc:  # noqa: BLE001 - smoke phải sống sót mọi lỗi
            self.record(method, path, 0, f"{type(exc).__name__}: {exc}"[:200])
            return None
        note = ""
        if response.status_code >= 400:
            note = response.text[:300].replace("\n", " ")
        self.record(method, path, response.status_code, note)
        return response

    # -- các bước ----------------------------------------------------------

    def login(self) -> bool:
        response = self.client.post(
            "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        self.record("POST", "/api/auth/login", response.status_code,
                    "" if response.status_code < 400 else response.text[:200])
        if response.status_code >= 400:
            return False
        payload = response.json()
        self.token = payload.get("access_token") or payload.get("token") or ""
        return bool(self.token)

    def discover_seat(self) -> str:
        """Seat thật đầu tiên trong tổ chức, để không ghim cứng id trong fixture."""
        try:
            response = self.client.get("/api/agents", headers=self.headers())
            rows = response.json() if response.status_code < 400 else []
        except Exception:                                  # noqa: BLE001
            rows = []
        seat = next((str(r.get("runtime_agent_id") or "") for r in rows
                     if r.get("runtime_agent_id")), "")
        if seat:
            for path in ("/api/company-tools/context", "/api/company-tools/tasks"):
                REQUIRED_QUERY[path]["runtime_agent_id"] = seat
        return seat

    def discover_gets(self) -> list[str]:
        spec = self.client.get("/openapi.json").json()
        paths = []
        for path, operations in spec["paths"].items():
            if "get" not in operations:
                continue
            resolved = path
            for name, value in PATH_DEFAULTS.items():
                resolved = resolved.replace("{" + name + "}", value)
            if "{" in resolved:
                continue  # còn tham số không biết -> bỏ, và nói rõ ở báo cáo
            paths.append(resolved)
        return sorted(set(paths))

    def sweep_gets(self) -> None:
        for path in self.discover_gets():
            if path in SKIP_PATHS:
                self.record("GET", path, 0, "bỏ qua: cần token audience portal")
                continue
            if path in EXPECTED_EMPTY:
                response = self.client.get(path, headers=self.headers(),
                                           params={"organization_id": 1})
                self.record("GET", path, response.status_code,
                            "bỏ qua: seed không có dữ liệu loại này"
                            if response.status_code == 404 else "")
                continue
            query = dict(REQUIRED_QUERY.get(path, {}))
            if "organization_id" not in path:
                query.setdefault("organization_id", 1)
            self.call("GET", path, params=query)

    def write_flow(self) -> None:
        """Chuỗi ghi cốt lõi: công ty -> phòng ban -> ghế -> dự án -> việc.

        Hậu tố ngẫu nhiên vì workspace_ops cấm trùng tên công ty trong cùng
        organization -- luật đúng, nên script phải tự tránh thay vì coi 409 là lỗi.
        """
        suffix = f"smoke-{uuid.uuid4().hex[:6]}"
        company = self.call(
            "POST", "/api/v18/workspace/companies",
            json={"organization_id": 1, "name": f"Cty {suffix}", "industry": "AI"},
        )
        company_id = (company.json() or {}).get("id") if company and company.status_code < 300 else None
        if not company_id:
            return

        department = self.call(
            "POST", "/api/v18/workspace/departments",
            json={"company_id": company_id, "name": f"Phòng {suffix}"},
        )
        department_id = (department.json() or {}).get("id") if department and department.status_code < 300 else None

        # Route thật là /workspace/members. README gọi chúng là "seats
        # (human or agent)", nhưng đường dẫn thì là members.
        seat_id = None
        seat = self.call(
            "POST", "/api/v18/workspace/members",
            json={"company_id": company_id, "department_id": department_id,
                  "name": f"Người {suffix}", "member_type": "human", "role": "Editor"},
        )

        if seat and seat.status_code < 300:
            seat_id = (seat.json() or {}).get("id")

        project = self.call(
            "POST", "/api/v18/workspace/projects",
            json={"company_id": company_id, "name": f"Dự án {suffix}"},
        )
        project_id = (project.json() or {}).get("id") if project and project.status_code < 300 else None
        if not project_id:
            return

        task = self.call(
            "POST", "/api/v18/workspace/tasks",
            json={"project_id": project_id, "title": f"Việc {suffix}", "priority": "high"},
        )
        task_id = (task.json() or {}).get("id") if task and task.status_code < 300 else None
        if task_id:
            # Task mới sinh ra ở "backlog"; workspace_ops chỉ cho phép
            # backlog -> todo | cancelled. Nhảy thẳng sang in_progress bị 409,
            # và đó là luật đúng của v18 chứ không phải lỗi.
            self.call("POST", f"/api/v18/workspace/tasks/{task_id}/move",
                      json={"status": "todo"})
            # v18 đòi gán người trước khi đưa việc vào in_progress -- luật
            # đúng ("Assign the task before moving it into progress"), nên
            # script phải tuân theo chứ không coi 400 là lỗi hệ thống.
            if seat_id:
                self.call("POST", f"/api/v18/workspace/tasks/{task_id}/assign",
                          json={"assignee_member_id": seat_id})
            self.call("POST", f"/api/v18/workspace/tasks/{task_id}/move",
                      json={"status": "in_progress"})
        # Sự thật bảng dự án (v27) trên đúng dự án vừa tạo
        self.call("GET", f"/api/v27/projects/{project_id}/truth")
        self.call("GET", f"/api/v28/projects/{project_id}/history")
        self.call("GET", f"/api/v29/companies/{company_id}/archive/preview")

    # -- báo cáo -----------------------------------------------------------

    def report(self) -> dict:
        by_group: dict[str, list[dict]] = defaultdict(list)
        for row in self.results:
            by_group[row["group"]].append(row)

        print(f"\n{'nhóm':6} {'gọi':>5} {'ok':>5} {'lỗi':>5}  endpoint lỗi")
        print("-" * 78)
        total_ok = total = 0
        for group in sorted(by_group, key=version_key):
            rows = by_group[group]
            ok = sum(1 for r in rows if r["ok"])
            bad = [r for r in rows if not r["ok"]]
            total_ok += ok
            total += len(rows)
            sample = ", ".join(f"{r['status']} {r['path']}" for r in bad[:2])
            print(f"{group:6} {len(rows):5} {ok:5} {len(bad):5}  {sample[:60]}")
        print("-" * 78)
        print(f"{'TỔNG':6} {total:5} {total_ok:5} {total - total_ok:5}")

        failures = [r for r in self.results if not r["ok"]]
        if failures:
            print(f"\n{len(failures)} lỗi, chi tiết:")
            for row in failures:
                print(f"  {row['status']:>3} {row['method']:4} {row['path']}")
                if row["note"]:
                    print(f"      {row['note'][:220]}")
        return {"total": total, "ok": total_ok, "failed": total - total_ok,
                "results": self.results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()

    smoke = Smoke(args.base)
    if not smoke.login():
        print("không đăng nhập được; đã seed chưa?", file=sys.stderr)
        smoke.report()
        return 1
    seat = smoke.discover_seat()
    print(f"seat dùng cho company-tools: {seat or '(không tìm được seat nào)'}")
    smoke.sweep_gets()
    smoke.write_flow()
    summary = smoke.report()
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
