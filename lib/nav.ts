/* Sổ đăng ký điều hướng — nguồn duy nhất cho sidebar (8 mục), tab của từng
   mục, thanh dưới trên điện thoại, ⌘K, tiêu đề trang và Phòng thí nghiệm.

   Theo plan-v2 §5: đúng 8 mục menu. Mỗi mục có các tab là route thật (link đổi
   URL, chia sẻ được). Trang không thuộc 8 mục chia hai nhóm:
   - MORE: trang còn dùng nhưng không đáng một chỗ trên menu — vào bằng ⌘K hoặc
     từ trang cha (vd. Phòng họp, Nhật ký sự kiện).
   - LAB:  27 trang ít dùng của plan §2 (giao phần mềm v11–v15 + điều hành v9/v10).
     Route vẫn chạy; chỉ hiện ở Cài đặt › Phòng thí nghiệm và ⌘K khi bật cờ. */

import type {IconName} from "../components/Icon";

export type NavTab = {href: string; label: string; desc?: string};
export type NavSection = {
  key: string; href: string; label: string; icon: IconName; desc: string; keywords: string;
  countKey?: string; tabs: NavTab[];
  /** Tiền tố đường dẫn thuộc về mục này (kể cả trang chi tiết). */
  owns: string[];
};
export type NavPage = {href: string; label: string; icon: IconName; desc: string; keywords?: string; area: string; kind: "more" | "lab"};

export const SECTIONS: NavSection[] = [
  {key: "inbox", href: "/app/inbox", label: "Hộp việc", icon: "inbox", countKey: "inbox",
   desc: "Những gì đang chờ anh: phê duyệt, kết quả cần xem, ngân sách chạm nấc",
   keywords: "inbox phê duyệt approval duyệt thông báo", owns: ["/app/inbox", "/app/approve"],
   tabs: []},
  {key: "os", href: "/app/os", label: "Tổng quan", icon: "home",
   desc: "Hôm nay công ty làm gì: agent đang làm, việc chờ duyệt, chi tiêu so với ngân sách",
   keywords: "home trang chủ dashboard hôm nay", owns: ["/app/os"], tabs: []},
  {key: "work", href: "/app/work", label: "Công việc", icon: "check",
   desc: "Danh sách, bảng và dự án — lượt chạy kèm chi phí, review chéo",
   keywords: "task nhiệm vụ kanban board bảng list danh sách dự án project lượt chạy",
   owns: ["/app/work", "/app/tasks", "/app/flow"],
   tabs: [{href: "/app/work", label: "Danh sách"}, {href: "/app/work?view=board", label: "Bảng"}, {href: "/app/work?view=projects", label: "Dự án"}]},
  {key: "goals", href: "/app/goals", label: "Mục tiêu & Kế hoạch", icon: "target",
   desc: "Đặt mục tiêu, Nina chia thành kế hoạch cho từng phòng, anh duyệt",
   keywords: "goal okr mục tiêu strategy kế hoạch nina plan phân rã",
   owns: ["/app/goals", "/app/strategy", "/app/nina"],
   tabs: [{href: "/app/goals", label: "Mục tiêu"}, {href: "/app/strategy", label: "Kế hoạch chờ duyệt"}, {href: "/app/nina", label: "Nina lập nhanh"}]},
  {key: "team", href: "/app/team", label: "Đội ngũ", icon: "users",
   desc: "Sơ đồ tổ chức, agent, người và quyền, đào tạo",
   keywords: "team org chart sơ đồ agent nhân sự ai người mời quyền phòng ban đào tạo",
   owns: ["/app/team", "/app/agents/"],
   tabs: [{href: "/app/team", label: "Sơ đồ"}, {href: "/app/team?tab=ai", label: "Agent"}, {href: "/app/team?tab=people", label: "Người & quyền"},
          {href: "/app/team?tab=departments", label: "Phòng ban"}, {href: "/app/team?tab=training", label: "Đào tạo"}, {href: "/app/team?tab=build", label: "Dựng công ty"}]},
  {key: "routines", href: "/app/routines", label: "Việc định kỳ", icon: "zap",
   desc: "Việc lặp theo lịch hoặc webhook, và quy trình nhiều bước",
   keywords: "routine cron lịch webhook định kỳ workflow quy trình tự động hoá",
   owns: ["/app/routines", "/app/workflows"],
   tabs: [{href: "/app/routines", label: "Việc định kỳ"}, {href: "/app/workflows", label: "Quy trình"}]},
  {key: "costs", href: "/app/costs", label: "Chi phí", icon: "coins",
   desc: "Chi phí model theo agent, phòng, công ty — ngân sách 3 nấc",
   keywords: "budget cost chi phí ngân sách hạn mức tiền model", owns: ["/app/costs", "/app/budgets"],
   tabs: [{href: "/app/costs", label: "Tổng quan"}, {href: "/app/costs?tab=budgets", label: "Ngân sách"}]},
  {key: "settings", href: "/app/settings", label: "Cài đặt", icon: "gear",
   desc: "Kết nối OpenClaw, kỹ năng & công cụ, bí mật, thành viên, Phòng thí nghiệm",
   keywords: "settings cài đặt openclaw gateway kỹ năng skill tool mcp bí mật secret thành viên phòng thí nghiệm lab",
   owns: ["/app/settings", "/app/openclaw", "/app/agent-tools", "/app/secrets"],
   tabs: [{href: "/app/settings", label: "Chung"}, {href: "/app/openclaw", label: "OpenClaw"}, {href: "/app/agent-tools", label: "Kỹ năng & công cụ"},
          {href: "/app/secrets", label: "Bí mật"}, {href: "/app/team?tab=people&from=settings", label: "Thành viên"},
          {href: "/app/settings/lab", label: "Phòng thí nghiệm"}]},
];

/* Trang còn dùng, ngoài menu. */
export const MORE_PAGES: NavPage[] = [
  {href: "/app/collaboration", label: "Phòng họp", icon: "room", area: "Phối hợp", kind: "more", desc: "Phòng phối hợp có chủ toạ, bàn giao giữa agent", keywords: "room meeting họp"},
  {href: "/app/communications", label: "Tin nhắn agent", icon: "room", area: "Phối hợp", kind: "more", desc: "Tin nhắn giữa agent và người", keywords: "message bus chat"},
  {href: "/app/artifacts", label: "Sản phẩm & bàn giao", icon: "doc", area: "Phối hợp", kind: "more", desc: "Tệp, kết quả, bàn giao giữa agent", keywords: "artifact handoff"},
  {href: "/app/quality", label: "Chất lượng & hạn", icon: "check", area: "Phối hợp", kind: "more", desc: "Cổng đánh giá, hạn và leo thang", keywords: "qa sla"},
  {href: "/app/live-runs", label: "Phiên đang chạy", icon: "pulse", area: "Vận hành", kind: "more", desc: "Phiên OpenClaw, lease, chuyển trạng thái", keywords: "run session live"},
  {href: "/app/events", label: "Nhật ký sự kiện", icon: "list", area: "Vận hành", kind: "more", desc: "Sự kiện hệ thống và trigger", keywords: "event audit log nhật ký"},
  {href: "/app/reports", label: "Báo cáo", icon: "chart", area: "Vận hành", kind: "more", desc: "Chỉ số có kỳ trước và mục tiêu", keywords: "report analytics kpi"},
  {href: "/app/routing", label: "Định tuyến phòng ban", icon: "users", area: "Tổ chức", kind: "more", desc: "Giao việc cho phòng, trưởng phòng chọn người", keywords: "routing department"},
  {href: "/app/agents", label: "Tuyển agent (cũ)", icon: "sparkle", area: "Tổ chức", kind: "more", desc: "Trang tuyển agent đời cũ — dùng Đội ngũ › Agent", keywords: "workforce hire"},
  {href: "/app/company-factory", label: "Dựng công ty từ mẫu (cũ)", icon: "building", area: "Tổ chức", kind: "more", desc: "Company Factory đời cũ — dùng Đội ngũ › Dựng công ty", keywords: "factory template"},
  {href: "/app/workspace-ops", label: "Sửa dữ liệu tổ chức", icon: "pencil", area: "Tổ chức", kind: "more", desc: "Lập công ty, phòng ban, ghế, dự án bằng form", keywords: "workspace ops"},
  {href: "/app/memory", label: "Bộ nhớ tổ chức", icon: "book", area: "Tri thức", kind: "more", desc: "Ghi nhớ và tìm lại quyết định", keywords: "memory"},
  {href: "/app/knowledge-mesh", label: "Lưới tri thức", icon: "mesh", area: "Tri thức", kind: "more", desc: "Không gian tri thức có cấp quyền", keywords: "knowledge mesh"},
  {href: "/app/customers", label: "Khách hàng", icon: "users", area: "Kinh doanh", kind: "more", desc: "Khách hàng, ghế đã bán, chi phí AI theo khách", keywords: "customer"},
  {href: "/app/marketplace", label: "Kho mẫu", icon: "doc", area: "Kinh doanh", kind: "more", desc: "Mẫu công ty, mẫu nhân sự và quy trình", keywords: "marketplace template"},
  {href: "/app/system", label: "Danh bạ công cụ", icon: "grid", area: "Khác", kind: "more", desc: "Mọi trang ngoài menu, chia theo khu vực", keywords: "system tools danh bạ"},
];

/* 27 trang ít dùng — plan-v2 §2. */
export const LAB_PAGES: NavPage[] = [
  ...[
    ["/app/repositories", "Repository", "Kho mã, quyền truy cập và trạng thái Git", "doc"],
    ["/app/delivery", "Pipeline giao hàng", "Gói → worktree → test → review → merge", "arrow-right"],
    ["/app/reviews", "Review mã", "Cổng review người + AI trước khi merge", "check"],
    ["/app/cicd", "CI/CD", "Đồ thị chạy từ commit tới bản phát hành", "layers"],
    ["/app/releases", "Chuyến phát hành", "Commit → duyệt → môi trường", "arrow-right"],
    ["/app/release-manager", "Quản lý phát hành", "Thăng cấp có kiểm soát, rollback theo sức khoẻ", "crown"],
    ["/app/deployments", "Triển khai", "Preview, staging, production", "server"],
    ["/app/progressive-delivery", "Triển khai dần", "Canary và rollback theo SLO", "pulse"],
    ["/app/sandboxes", "Sandbox", "Môi trường chạy build/test có chính sách", "shield"],
    ["/app/workspaces", "Workspace phát triển", "Bàn giao workspace giữa các agent viết mã", "layers"],
    ["/app/workspace-gateway", "Cổng workspace", "Trao đổi tệp giữa các nhà cung cấp", "server"],
    ["/app/dev-cloud", "Dev Cloud", "Workspace, sandbox, phát hành trong một nơi", "server"],
    ["/app/engineering", "Tổ chức kỹ thuật", "Giao phần mềm do Nina điều phối", "users"],
    ["/app/portfolio", "Danh mục kỹ thuật", "Sức khoẻ kỹ thuật và đề xuất của Nina", "chart"],
  ].map(([href, label, desc, icon]) => ({href, label, desc, icon: icon as IconName, area: "Giao phần mềm", kind: "lab" as const})),
  ...[
    ["/app/runners", "Runner phân tán", "Cho thuê tài nguyên chạy theo năng lực", "server"],
    ["/app/sre-control", "Nina SRE", "Khôi phục sự cố tự động có kiểm soát", "crown"],
    ["/app/incidents", "Sự cố", "Xử lý sự cố có kiểm toán", "alert"],
    ["/app/observability", "SLO & đo lường", "Tín hiệu sức khoẻ điều khiển thăng cấp/rollback", "pulse"],
    ["/app/telemetry-federation", "Liên kết đo lường", "OTLP, Prometheus, exporter", "mesh"],
    ["/app/trust", "Tin cậy", "Bằng chứng ký số, bộ quét", "shield"],
    ["/app/supply-chain", "Chuỗi cung ứng phần mềm", "SBOM, provenance, cổng bảo mật", "layers"],
    ["/app/production-trust", "Tin cậy production", "Danh tính mTLS của runner, xoay khoá", "shield"],
    ["/app/secrets-federation", "Liên kết bí mật", "Thuê bí mật có hạn", "key"],
  ].map(([href, label, desc, icon]) => ({href, label, desc, icon: icon as IconName, area: "Vận hành & tin cậy", kind: "lab" as const})),
  ...[
    ["/app/control-center", "Trung tâm điều hành", "Bảng điều hành đời v9", "target"],
    ["/app/founder-cockpit", "Buồng lái founder", "Bảng điều hành đời v10", "crown"],
    ["/app/autonomy", "Mức tự chủ", "Chính sách tự chủ & vận hành", "shield"],
    ["/app/simulation", "Mô phỏng", "Thử “nếu… thì” trước khi đổi công ty thật", "layers"],
  ].map(([href, label, desc, icon]) => ({href, label, desc, icon: icon as IconName, area: "Điều hành đời cũ", kind: "lab" as const})),
];

/** Job nền thuộc các trang Phòng thí nghiệm (plan §2) — chưa có cờ env ở backend; xem _reports/ui-v2.md. */
export const LAB_JOBS = ["devcloud.cleanup_expired", "v14.reap_runner_leases", "v14.evaluate_slos", "v14.review_portfolios", "v15.control_plane_tick", "v15.export_telemetry"];

const pathOf = (href: string) => href.split("?")[0];
const paramsOf = (href: string) => new URLSearchParams(href.split("?")[1] || "");

export function sectionFor(pathname: string): NavSection | undefined {
  return SECTIONS.find(s => s.owns.some(p => p.endsWith("/") ? pathname.startsWith(p) : pathname === p || pathname.startsWith(p + "/")));
}

/** Tab đang chọn: khớp đường dẫn + mọi tham số của tab có trong URL; ưu tiên tab nhiều tham số nhất. */
export function activeTab(section: NavSection | undefined, pathname: string, search: URLSearchParams): NavTab | undefined {
  if (!section) return undefined;
  let best: NavTab | undefined, score = -1;
  for (const t of section.tabs) {
    if (pathOf(t.href) !== pathname) continue;
    const p = paramsOf(t.href); let ok = true, n = 0;
    p.forEach((v, k) => { if (k === "from") return; n++; if (search.get(k) !== v) ok = false; });
    if (ok && n > score) { best = t; score = n; }
  }
  return best;
}

export function pageFor(pathname: string): NavPage | undefined {
  return [...MORE_PAGES, ...LAB_PAGES].find(p => p.href === pathname);
}
export const isLabPath = (pathname: string) => LAB_PAGES.some(p => p.href === pathname);
