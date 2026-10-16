/* Sổ đăng ký điều hướng — nguồn duy nhất cho sidebar (9 mục), tab của từng
   mục, thanh dưới trên điện thoại, ⌘K, tiêu đề trang và Phòng thí nghiệm.

   Theo plan-v2 §5: 8 mục menu (+ Công ty từ 2026-10-16 = 9). Mỗi mục có các tab là route thật (link đổi
   URL, chia sẻ được). Trang không thuộc menu chia hai nhóm:
   - MORE: trang còn dùng nhưng không đáng một chỗ trên menu — vào bằng ⌘K hoặc
     từ trang cha (vd. Phòng họp, Nhật ký sự kiện).
   - LAB:  27 trang ít dùng của plan §2 (giao phần mềm v11–v15 + điều hành v9/v10).
     Route vẫn chạy; chỉ hiện ở Cài đặt › Phòng thí nghiệm và ⌘K khi bật cờ. */

import type {IconName} from "../components/Icon";
import {t as tr, lazy} from "./i18n";

export type NavTab = {href: string; label: string; desc?: string};
export type NavGroup = {key: string; label: string; tabs: NavTab[]};
export type NavSection = {
  key: string; href: string; label: string; icon: IconName; desc: string; keywords: string;
  countKey?: string; tabs: NavTab[];
  /** Mục nhiều trang (Công ty): tab chia nhóm — hàng trên là nhóm, hàng dưới là trang trong nhóm. `tabs` = các nhóm trải phẳng. */
  groups?: NavGroup[];
  /** Tiền tố đường dẫn thuộc về mục này (kể cả trang chi tiết). */
  owns: string[];
};
export type NavPage = {href: string; label: string; icon: IconName; desc: string; keywords?: string; area: string; kind: "more" | "lab"};

/* Mục "Công ty" (2026-10-16, tách khỏi Đội ngũ): mọi thứ ở cấp công ty — pháp nhân,
   cơ cấu, vận hành, hiệu quả, cho thuê. Đội ngũ chỉ còn người & agent.
   Tab cũ /app/team?tab=<x> chuyển hướng sang /app/company?tab=<x> (TeamConsole). */
export const COMPANY_TAB_IDS = ["overview", "readiness", "build", "profile", "roles", "authority", "rules", "departments", "positions",
  "processes", "contracts", "rhythm", "coverage", "compliance", "kpi", "agenthr", "leaseout", "leased"] as const;
export type CompanyTab = typeof COMPANY_TAB_IDS[number];
const ct = (tab: string, label: string): NavTab => ({href: tab === "overview" ? "/app/company" : `/app/company?tab=${tab}`, label});
function companySection(): NavSection {
  const groups: NavGroup[] = [
    {key: "overview", label: tr("nav.co_tong_quan"), tabs: [ct("overview", tr("nav.co_cong_ty_cua_anh")), ct("readiness", tr("nav.san_sang")), ct("build", tr("nav.co_tao_nhap"))]},
    {key: "governance", label: tr("nav.co_phap_nhan_quan_tri"), tabs: [ct("profile", tr("nav.co_ho_so_hien_chuong")), ct("roles", tr("nav.vai_tro_cong_ty")), ct("authority", tr("nav.co_ma_tran_tham_quyen")), ct("rules", tr("nav.luat_cung"))]},
    {key: "structure", label: tr("nav.co_co_cau"), tabs: [ct("departments", tr("nav.phong_ban")), ct("positions", tr("nav.chuc_danh"))]},
    {key: "operations", label: tr("nav.van_hanh"), tabs: [ct("processes", tr("nav.quy_trinh_cty")), ct("contracts", tr("nav.hop_dong_du_lieu")), ct("rhythm", tr("nav.giao_ban")), ct("coverage", tr("nav.co_phu_24_7_sla")), ct("compliance", tr("nav.tuan_thu"))]},
    {key: "performance", label: tr("nav.co_hieu_qua"), tabs: [ct("kpi", tr("nav.kpi")), ct("agenthr", tr("nav.nhan_su_agent"))]},
    {key: "rental", label: tr("nav.co_cho_thue"), tabs: [ct("leaseout", tr("nav.cho_thue_agent")), ct("leased", tr("nav.agent_di_thue"))]},
  ];
  return {key: "company", href: "/app/company", label: tr("nav.co_cong_ty"), icon: "building",
    desc: tr("nav.co_desc"), keywords: tr("nav.co_keywords"),
    owns: ["/app/company"], groups, tabs: groups.flatMap(g => g.tabs)};
}

/** Nhóm chứa tab đang chọn (mục có `groups`). */
export function activeGroup(section: NavSection | undefined, tab: NavTab | undefined): NavGroup | undefined {
  if (!section?.groups) return undefined;
  return section.groups.find(g => g.tabs.some(t => t.href === tab?.href)) || section.groups[0];
}

export const SECTIONS: NavSection[] = lazy(() => ([
  {key: "inbox", href: "/app/inbox", label: tr("nav.hop_viec"), icon: "inbox", countKey: "inbox",
   desc: tr("nav.nhung_gi_dang_cho_anh"),
   keywords: tr("nav.inbox_phe_duyet_approval_duyet"), owns: ["/app/inbox", "/app/approve"],
   tabs: []},
  {key: "os", href: "/app/os", label: tr("nav.tong_quan"), icon: "home",
   desc: tr("nav.hom_nay_cong_ty_lam"),
   keywords: tr("nav.home_trang_chu_dashboard_hom"), owns: ["/app/os"], tabs: []},
  {key: "work", href: "/app/work", label: tr("nav.cong_viec"), icon: "check",
   desc: tr("nav.danh_sach_bang_va_du"),
   keywords: tr("nav.task_nhiem_vu_kanban_board"),
   owns: ["/app/work", "/app/tasks", "/app/flow"],
   tabs: [{href: "/app/work", label: tr("nav.danh_sach")}, {href: "/app/work?view=board", label: tr("nav.bang")}, {href: "/app/work?view=projects", label: tr("nav.du_an")}]},
  {key: "goals", href: "/app/goals", label: tr("nav.muc_tieu_ke_hoach"), icon: "target",
   desc: tr("nav.dat_muc_tieu_nina_chia"),
   keywords: tr("nav.goal_okr_muc_tieu_strategy"),
   owns: ["/app/goals", "/app/strategy", "/app/nina"],
   tabs: [{href: "/app/goals", label: tr("nav.muc_tieu")}, {href: "/app/strategy", label: tr("nav.ke_hoach_cho_duyet")}, {href: "/app/nina", label: tr("nav.nina_lap_nhanh")}]},
  {key: "team", href: "/app/team", label: tr("nav.doi_ngu"), icon: "users",
   desc: tr("nav.doi_ngu_desc"),
   keywords: tr("nav.team_org_chart_so_do"),
   owns: ["/app/team", "/app/agents/"],
   tabs: [{href: "/app/team", label: tr("nav.so_do")}, {href: "/app/team?tab=ai", label: "Agent"}, {href: "/app/team?tab=people", label: tr("nav.nguoi_quyen")},
          {href: "/app/team?tab=training", label: tr("nav.dao_tao")}]},
  companySection(),
  {key: "routines", href: "/app/routines", label: tr("nav.viec_dinh_ky"), icon: "zap",
   desc: tr("nav.viec_lap_theo_lich_hoac"),
   keywords: tr("nav.routine_cron_lich_webhook_dinh"),
   owns: ["/app/routines", "/app/workflows"],
   tabs: [{href: "/app/routines", label: tr("nav.viec_dinh_ky")}, {href: "/app/workflows", label: tr("nav.quy_trinh")}]},
  {key: "costs", href: "/app/costs", label: tr("nav.chi_phi"), icon: "coins",
   desc: tr("nav.chi_phi_model_theo_agent"),
   keywords: tr("nav.budget_cost_chi_phi_ngan"), owns: ["/app/costs", "/app/budgets"],
   tabs: [{href: "/app/costs", label: tr("nav.tong_quan")}, {href: "/app/costs?tab=budgets", label: tr("nav.ngan_sach")}]},
  {key: "settings", href: "/app/settings", label: tr("nav.cai_dat"), icon: "gear",
   desc: tr("nav.ket_noi_openclaw_ky_nang"),
   keywords: tr("nav.settings_cai_dat_openclaw_gateway"),
   owns: ["/app/settings", "/app/openclaw", "/app/agent-tools", "/app/secrets"],
   tabs: [{href: "/app/settings", label: tr("nav.chung")}, {href: "/app/openclaw", label: "OpenClaw"}, {href: "/app/agent-tools", label: tr("nav.ky_nang_cong_cu")},
          {href: "/app/secrets", label: tr("nav.bi_mat")}, {href: "/app/team?tab=people&from=settings", label: tr("nav.thanh_vien")},
          {href: "/app/settings/lab", label: tr("nav.phong_thi_nghiem")}]},
]));

/* Trang còn dùng, ngoài menu. */
export const MORE_PAGES: NavPage[] = lazy(() => ([
  {href: "/app/collaboration", label: tr("nav.phong_hop"), icon: "room", area: tr("nav.phoi_hop"), kind: "more", desc: tr("nav.phong_phoi_hop_co_chu"), keywords: tr("nav.room_meeting_hop")},
  {href: "/app/communications", label: tr("nav.tin_nhan_agent"), icon: "room", area: tr("nav.phoi_hop"), kind: "more", desc: tr("nav.tin_nhan_giua_agent_va"), keywords: "message bus chat"},
  {href: "/app/artifacts", label: tr("nav.san_pham_ban_giao"), icon: "doc", area: tr("nav.phoi_hop"), kind: "more", desc: tr("nav.tep_ket_qua_ban_giao"), keywords: "artifact handoff"},
  {href: "/app/quality", label: tr("nav.chat_luong_han"), icon: "check", area: tr("nav.phoi_hop"), kind: "more", desc: tr("nav.cong_danh_gia_han_va"), keywords: "qa sla"},
  {href: "/app/live-runs", label: tr("nav.phien_dang_chay"), icon: "pulse", area: tr("nav.van_hanh"), kind: "more", desc: tr("nav.phien_openclaw_lease_chuyen_trang"), keywords: "run session live"},
  {href: "/app/events", label: tr("nav.nhat_ky_su_kien"), icon: "list", area: tr("nav.van_hanh"), kind: "more", desc: tr("nav.su_kien_he_thong_va"), keywords: tr("nav.event_audit_log_nhat_ky")},
  {href: "/app/reports", label: tr("nav.bao_cao"), icon: "chart", area: tr("nav.van_hanh"), kind: "more", desc: tr("nav.chi_so_co_ky_truoc"), keywords: "report analytics kpi"},
  {href: "/app/routing", label: tr("nav.dinh_tuyen_phong_ban"), icon: "users", area: tr("nav.to_chuc"), kind: "more", desc: tr("nav.giao_viec_cho_phong_truong"), keywords: "routing department"},
  {href: "/app/agents", label: tr("nav.tuyen_agent_cu"), icon: "sparkle", area: tr("nav.to_chuc"), kind: "more", desc: tr("nav.trang_tuyen_agent_doi_cu"), keywords: "workforce hire"},
  {href: "/app/company-factory", label: tr("nav.dung_cong_ty_tu_mau"), icon: "building", area: tr("nav.to_chuc"), kind: "more", desc: tr("nav.company_factory_doi_cu_dung"), keywords: "factory template"},
  {href: "/app/workspace-ops", label: tr("nav.sua_du_lieu_to_chuc"), icon: "pencil", area: tr("nav.to_chuc"), kind: "more", desc: tr("nav.lap_cong_ty_phong_ban"), keywords: "workspace ops"},
  {href: "/app/memory", label: tr("nav.bo_nho_to_chuc"), icon: "book", area: tr("nav.tri_thuc"), kind: "more", desc: tr("nav.ghi_nho_va_tim_lai"), keywords: "memory"},
  {href: "/app/knowledge-mesh", label: tr("nav.luoi_tri_thuc"), icon: "mesh", area: tr("nav.tri_thuc"), kind: "more", desc: tr("nav.khong_gian_tri_thuc_co"), keywords: "knowledge mesh"},
  {href: "/app/customers", label: tr("nav.khach_hang"), icon: "users", area: "Kinh doanh", kind: "more", desc: tr("nav.khach_hang_ghe_da_ban"), keywords: "customer"},
  {href: "/app/marketplace", label: tr("nav.kho_mau"), icon: "doc", area: "Kinh doanh", kind: "more", desc: tr("nav.mau_cong_ty_mau_nhan"), keywords: "marketplace template"},
  {href: "/app/system", label: tr("nav.danh_ba_cong_cu"), icon: "grid", area: tr("nav.khac"), kind: "more", desc: tr("nav.moi_trang_ngoai_menu_chia"), keywords: tr("nav.system_tools_danh_ba")},
]));

/* 27 trang ít dùng — plan-v2 §2. */
export const LAB_PAGES: NavPage[] = lazy(() => ([
  ...[
    ["/app/repositories", "Repository", tr("nav.kho_ma_quyen_truy_cap"), "doc"],
    ["/app/delivery", tr("nav.pipeline_giao_hang"), tr("nav.goi_worktree_test_review_merge"), "arrow-right"],
    ["/app/reviews", tr("nav.review_ma"), tr("nav.cong_review_nguoi_ai_truoc"), "check"],
    ["/app/cicd", "CI/CD", tr("nav.do_thi_chay_tu_commit"), "layers"],
    ["/app/releases", tr("nav.chuyen_phat_hanh"), tr("nav.commit_duyet_moi_truong"), "arrow-right"],
    ["/app/release-manager", tr("nav.quan_ly_phat_hanh"), tr("nav.thang_cap_co_kiem_soat"), "crown"],
    ["/app/deployments", tr("nav.trien_khai"), "Preview, staging, production", "server"],
    ["/app/progressive-delivery", tr("nav.trien_khai_dan"), tr("nav.canary_va_rollback_theo_slo"), "pulse"],
    ["/app/sandboxes", "Sandbox", tr("nav.moi_truong_chay_build_test"), "shield"],
    ["/app/workspaces", tr("nav.workspace_phat_trien"), tr("nav.ban_giao_workspace_giua_cac"), "layers"],
    ["/app/workspace-gateway", tr("nav.cong_workspace"), tr("nav.trao_doi_tep_giua_cac"), "server"],
    ["/app/dev-cloud", "Dev Cloud", tr("nav.workspace_sandbox_phat_hanh_trong"), "server"],
    ["/app/engineering", tr("nav.to_chuc_ky_thuat"), tr("nav.giao_phan_mem_do_nina"), "users"],
    ["/app/portfolio", tr("nav.danh_muc_ky_thuat"), tr("nav.suc_khoe_ky_thuat_va"), "chart"],
  ].map(([href, label, desc, icon]) => ({href, label, desc, icon: icon as IconName, area: tr("nav.giao_phan_mem"), kind: "lab" as const})),
  ...[
    ["/app/runners", tr("nav.runner_phan_tan"), tr("nav.cho_thue_tai_nguyen_chay"), "server"],
    ["/app/sre-control", "Nina SRE", tr("nav.khoi_phuc_su_co_tu"), "crown"],
    ["/app/incidents", tr("nav.su_co"), tr("nav.xu_ly_su_co_co"), "alert"],
    ["/app/observability", tr("nav.slo_do_luong"), tr("nav.tin_hieu_suc_khoe_dieu"), "pulse"],
    ["/app/telemetry-federation", tr("nav.lien_ket_do_luong"), "OTLP, Prometheus, exporter", "mesh"],
    ["/app/trust", tr("nav.tin_cay"), tr("nav.bang_chung_ky_so_bo"), "shield"],
    ["/app/supply-chain", tr("nav.chuoi_cung_ung_phan_mem"), tr("nav.sbom_provenance_cong_bao_mat"), "layers"],
    ["/app/production-trust", tr("nav.tin_cay_production"), tr("nav.danh_tinh_mtls_cua_runner"), "shield"],
    ["/app/secrets-federation", tr("nav.lien_ket_bi_mat"), tr("nav.thue_bi_mat_co_han"), "key"],
  ].map(([href, label, desc, icon]) => ({href, label, desc, icon: icon as IconName, area: tr("nav.van_hanh_tin_cay"), kind: "lab" as const})),
  ...[
    ["/app/control-center", tr("nav.trung_tam_dieu_hanh"), tr("nav.bang_dieu_hanh_doi_v9"), "target"],
    ["/app/founder-cockpit", tr("nav.buong_lai_founder"), tr("nav.bang_dieu_hanh_doi_v10"), "crown"],
    ["/app/autonomy", tr("nav.muc_tu_chu"), tr("nav.chinh_sach_tu_chu_van"), "shield"],
    ["/app/simulation", tr("nav.mo_phong"), tr("nav.thu_neu_thi_truoc_khi"), "layers"],
  ].map(([href, label, desc, icon]) => ({href, label, desc, icon: icon as IconName, area: tr("nav.dieu_hanh_doi_cu"), kind: "lab" as const})),
]));

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
