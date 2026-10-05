/* Sổ đăng ký điều hướng — nguồn duy nhất cho sidebar, command palette,
   danh bạ công cụ và tiêu đề trang.

   Vì sao cần: trước v6 có mười vỏ ứng dụng (V8…V17AppShell), mỗi vỏ một danh
   sách menu riêng, nửa Anh nửa Việt. Cùng một trang /app/budgets có thể hiện
   "Budgets" ở vỏ này và không có mặt ở vỏ kia. Một danh sách, một tên cho mỗi
   khái niệm (DESIGN.md của Paperclip gọi là "one name per concept"). */

import type {IconName} from "../components/Icon";

export type NavGroupKey = "top" | "work" | "team" | "control" | "business" | "system";

export type NavEntry = {
  href: string;
  label: string;
  group: NavGroupKey;
  icon: IconName;
  desc: string;
  /** Nhóm con trong "Hệ thống" — chỉ dùng cho danh bạ công cụ. */
  area?: string;
  keywords?: string;
  countKey?: string;
};

export const NAV_GROUPS: {key: NavGroupKey; label: string}[] = [
  {key: "top", label: ""},
  {key: "work", label: "Công việc"},
  {key: "team", label: "Đội ngũ"},
  {key: "control", label: "Kiểm soát"},
  {key: "business", label: "Kinh doanh"},
  {key: "system", label: "Hệ thống"},
];

export const NAV: NavEntry[] = [
  {href: "/app/inbox", label: "Hộp việc", group: "top", icon: "inbox", countKey: "inbox",
   desc: "Mọi thứ đang chờ anh quyết: phê duyệt, việc bị chặn, việc chờ duyệt", keywords: "inbox phê duyệt approval duyệt"},
  {href: "/app/os", label: "Tổng quan", group: "top", icon: "home",
   desc: "Ai đang làm gì, cái gì cần anh, số liệu chính", keywords: "home trang chủ dashboard"},

  {href: "/app/flow", label: "Bảng việc", group: "work", icon: "board",
   desc: "Kanban theo vòng đời nhiệm vụ — kéo thả hoặc dùng nút ba chấm để chuyển trạng thái", keywords: "kanban task nhiệm vụ board flow"},
  {href: "/app/os?tab=projects", label: "Dự án", group: "work", icon: "layers", countKey: "projects_active",
   desc: "Dự án, tiến độ và hạn chót", keywords: "project"},
  {href: "/app/goals", label: "Mục tiêu", group: "work", icon: "target",
   desc: "Mục tiêu điều hành, kế hoạch và vòng vận hành", keywords: "goal okr"},
  {href: "/app/nina", label: "Nina lập kế hoạch", group: "work", icon: "crown",
   desc: "Đưa mục tiêu, Nina chia việc và giao cho đội", keywords: "planner chief of staff"},
  {href: "/app/collaboration", label: "Phòng họp", group: "work", icon: "room",
   desc: "Phòng phối hợp có chủ toạ, bàn giao giữa agent", keywords: "room meeting collaboration"},
  {href: "/app/workflows", label: "Tự động hoá", group: "work", icon: "zap",
   desc: "Quy trình và việc định kỳ", keywords: "workflow automation"},

  {href: "/app/os?tab=agents", label: "Nhân sự AI", group: "team", icon: "sparkle", countKey: "agents",
   desc: "Seat agent, model, trạng thái runtime", keywords: "agent seat ai"},
  {href: "/app/os?tab=people", label: "Con người", group: "team", icon: "users", countKey: "humans",
   desc: "Thành viên là người và vai trò", keywords: "member people nhân sự"},
  {href: "/app/os?tab=companies", label: "Công ty & sơ đồ", group: "team", icon: "building", countKey: "companies",
   desc: "Công ty con, phòng ban, sơ đồ tổ chức", keywords: "company org chart"},
  {href: "/app/os?tab=knowledge", label: "Kiến thức", group: "team", icon: "book",
   desc: "Tài liệu, SOP và quyết định đã chốt", keywords: "knowledge sop docs"},

  {href: "/app/budgets", label: "Ngân sách", group: "control", icon: "coins",
   desc: "Hạn mức chi và sổ cái giữ chỗ", keywords: "budget cost chi phí"},
  {href: "/app/live-runs", label: "Phiên đang chạy", group: "control", icon: "pulse",
   desc: "Phiên OpenClaw, lease, chuyển trạng thái", keywords: "run session live"},
  {href: "/app/events", label: "Nhật ký sự kiện", group: "control", icon: "list",
   desc: "Event bus và trigger", keywords: "event audit log"},
  {href: "/app/reports", label: "Báo cáo", group: "control", icon: "chart",
   desc: "Chỉ số có kỳ trước và mục tiêu", keywords: "report analytics kpi"},

  {href: "/app/customers", label: "Khách hàng", group: "business", icon: "users",
   desc: "Khách hàng, ghế đã bán, chi phí AI theo khách", keywords: "customer"},
  {href: "/app/marketplace", label: "Marketplace", group: "business", icon: "doc",
   desc: "Mẫu công ty, mẫu nhân sự và quy trình", keywords: "template"},

  {href: "/app/system", label: "Danh bạ công cụ", group: "system", icon: "grid",
   desc: "Mọi console chuyên sâu, chia theo khu vực", keywords: "system tools console danh bạ"},

  /* ---- Hệ thống: có thật, chạy được, nhưng là công cụ chuyên sâu ---- */
  {href: "/app/workspace-ops", label: "Vận hành tổ chức", group: "system", area: "Tổ chức", icon: "pencil", desc: "Lập công ty, phòng ban, ghế, dự án"},
  {href: "/app/company-factory", label: "Dựng công ty từ mẫu", group: "system", area: "Tổ chức", icon: "building", desc: "Company Factory"},
  {href: "/app/agents", label: "Lực lượng AI", group: "system", area: "Tổ chức", icon: "sparkle", desc: "AI Workforce — tuyển và cấp phát seat"},
  {href: "/app/memory", label: "Bộ nhớ tổ chức", group: "system", area: "Tổ chức", icon: "book", desc: "Org Memory"},
  {href: "/app/knowledge-mesh", label: "Lưới tri thức", group: "system", area: "Tổ chức", icon: "mesh", desc: "Knowledge Mesh — grant có hạn"},
  {href: "/app/control-center", label: "Trung tâm điều hành", group: "system", area: "Điều hành", icon: "target", desc: "Executive Control"},
  {href: "/app/founder-cockpit", label: "Buồng lái founder", group: "system", area: "Điều hành", icon: "crown", desc: "Founder Cockpit"},
  {href: "/app/autonomy", label: "Mức tự chủ", group: "system", area: "Điều hành", icon: "shield", desc: "Autonomy & Ops policy"},
  {href: "/app/simulation", label: "Mô phỏng", group: "system", area: "Điều hành", icon: "layers", desc: "Digital Twin — what-if"},
  {href: "/app/communications", label: "Tin nhắn agent", group: "system", area: "Phối hợp", icon: "room", desc: "Agent Message Bus"},
  {href: "/app/artifacts", label: "Sản phẩm & bàn giao", group: "system", area: "Phối hợp", icon: "doc", desc: "Artifacts & Handoff"},
  {href: "/app/quality", label: "QA & SLA", group: "system", area: "Phối hợp", icon: "check", desc: "Evaluator gates, hạn và leo thang"},
  {href: "/app/openclaw", label: "Lõi OpenClaw", group: "system", area: "Runtime", icon: "gear", desc: "Gateway, phiên theo agent, đối soát"},
  {href: "/app/runners", label: "Runner phân tán", group: "system", area: "Runtime", icon: "server", desc: "Distributed Runners"},
  {href: "/app/sandboxes", label: "Sandbox", group: "system", area: "Runtime", icon: "shield", desc: "Secure Sandboxes"},
  {href: "/app/workspaces", label: "Workspace phát triển", group: "system", area: "Runtime", icon: "layers", desc: "Development Workspaces"},
  {href: "/app/workspace-gateway", label: "Workspace Gateway", group: "system", area: "Runtime", icon: "server", desc: "Trao đổi file giữa provider"},
  {href: "/app/dev-cloud", label: "Dev Cloud", group: "system", area: "Runtime", icon: "server", desc: "Secure AI Development Cloud"},
  {href: "/app/engineering", label: "Tổ chức kỹ thuật", group: "system", area: "Giao phần mềm", icon: "users", desc: "AI Engineering Organization"},
  {href: "/app/portfolio", label: "Danh mục kỹ thuật", group: "system", area: "Giao phần mềm", icon: "chart", desc: "Nina Engineering Portfolio"},
  {href: "/app/repositories", label: "Repository", group: "system", area: "Giao phần mềm", icon: "doc", desc: "Registry và trạng thái Git"},
  {href: "/app/delivery", label: "Pipeline giao hàng", group: "system", area: "Giao phần mềm", icon: "arrow-right", desc: "Bundle → worktree → test → review → merge"},
  {href: "/app/reviews", label: "Review code", group: "system", area: "Giao phần mềm", icon: "check", desc: "Code Reviews"},
  {href: "/app/cicd", label: "CI/CD", group: "system", area: "Giao phần mềm", icon: "layers", desc: "DAG từ commit tới release"},
  {href: "/app/releases", label: "Release Train", group: "system", area: "Giao phần mềm", icon: "arrow-right", desc: "Commit → duyệt → môi trường"},
  {href: "/app/release-manager", label: "Quản lý release", group: "system", area: "Giao phần mềm", icon: "crown", desc: "Release Manager"},
  {href: "/app/deployments", label: "Triển khai", group: "system", area: "Giao phần mềm", icon: "server", desc: "Preview, staging, production"},
  {href: "/app/progressive-delivery", label: "Triển khai dần", group: "system", area: "Giao phần mềm", icon: "pulse", desc: "Canary và rollback theo SLO"},
  {href: "/app/sre-control", label: "Nina SRE", group: "system", area: "Vận hành & tin cậy", icon: "crown", desc: "Khôi phục sự cố có kiểm soát"},
  {href: "/app/incidents", label: "Sự cố", group: "system", area: "Vận hành & tin cậy", icon: "alert", desc: "Incident Response"},
  {href: "/app/observability", label: "SLO & telemetry", group: "system", area: "Vận hành & tin cậy", icon: "pulse", desc: "Tín hiệu sức khoẻ"},
  {href: "/app/telemetry-federation", label: "Liên kết telemetry", group: "system", area: "Vận hành & tin cậy", icon: "mesh", desc: "OTLP, Prometheus"},
  {href: "/app/trust", label: "Tin cậy", group: "system", area: "Vận hành & tin cậy", icon: "shield", desc: "Trust & Supply Chain"},
  {href: "/app/supply-chain", label: "Chuỗi cung ứng phần mềm", group: "system", area: "Vận hành & tin cậy", icon: "layers", desc: "SBOM, provenance"},
  {href: "/app/production-trust", label: "Production Trust", group: "system", area: "Vận hành & tin cậy", icon: "shield", desc: "mTLS runner, xoay khoá"},
  {href: "/app/secrets", label: "Bí mật & quyền", group: "system", area: "Vận hành & tin cậy", icon: "key", desc: "Secrets & Grants"},
  {href: "/app/secrets-federation", label: "Liên kết bí mật", group: "system", area: "Vận hành & tin cậy", icon: "key", desc: "Lease bí mật có hạn"},
];

export const SYSTEM_TOOLS = NAV.filter(n => n.group === "system" && !!n.area);

/** Công cụ hệ thống hay dùng, ghim sẵn khi mở nhóm "Hệ thống". */
export const SYSTEM_PINNED = ["/app/openclaw", "/app/sre-control", "/app/incidents", "/app/delivery"];

/** Mục khớp nhất với đường dẫn hiện tại (dùng cho tiêu đề và trạng thái active). */
export function matchNav(pathname: string, tab: string): NavEntry | undefined {
  const exact = NAV.find(n => {
    const [base, q = ""] = n.href.split("?");
    const t = q.startsWith("tab=") ? q.slice(4) : "";
    return base === pathname && t === tab;
  });
  if (exact) return exact;
  if (pathname === "/app/os") return NAV.find(n => n.href === "/app/os");
  if (pathname.startsWith("/app/tasks/")) return NAV.find(n => n.href === "/app/flow");
  if (pathname.startsWith("/app/agents/")) return NAV.find(n => n.href === "/app/os?tab=agents");
  return NAV.find(n => n.href.split("?")[0] === pathname);
}

export function groupLabel(key: NavGroupKey) {
  return NAV_GROUPS.find(g => g.key === key)?.label || "";
}
