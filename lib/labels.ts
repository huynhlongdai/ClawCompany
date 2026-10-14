import {t, lazy} from "./i18n";
import {intlLocale} from "./i18n";
/* Nhãn tiếng Việt cho trạng thái/mức độ thô từ backend (giá trị enum tiếng Anh).
   Một chỗ cho mọi trang; giá trị lạ hiện nguyên văn (là id, không phải câu chữ). */
const VI: Record<string, string> = lazy(() => ({
  // vòng đời chung
  active: t("labels.dang_hoat_dong"), inactive: t("labels.khong_hoat_dong"), enabled: t("labels.bat"), disabled: t("labels.tat"), on: t("labels.bat"), off: t("labels.tat"),
  pending: t("labels.dang_cho"), queued: t("labels.trong_hang"), waiting: t("labels.dang_cho"), waiting_approval: t("labels.cho_duyet"), awaiting_approval: t("labels.cho_duyet"),
  running: t("labels.dang_chay"), in_progress: t("labels.dang_lam"), started: t("labels.da_bat_dau"), executing: t("labels.dang_thuc_thi"), planned: t("labels.da_lap"), planning: t("labels.dang_lap"),
  completed: t("labels.hoan_tat"), complete: t("labels.hoan_tat"), done: "Xong", succeeded: t("labels.thanh_cong"), success: t("labels.thanh_cong"), passed: t("labels.dat"), ok: t("labels.on"),
  failed: t("labels.that_bai"), failure: t("labels.that_bai"), error: t("labels.loi"), errored: t("labels.loi"), breached: t("labels.vi_pham"), blocked: t("labels.bi_chan"), rejected: t("labels.tu_choi"),
  cancelled: t("labels.da_huy"), canceled: t("labels.da_huy"), expired: t("labels.het_han"), revoked: t("labels.da_thu_hoi"), released: t("labels.da_tra"), destroyed: t("labels.da_huy_bo"),
  approved: t("labels.da_duyet"), review: t("labels.cho_duyet"), in_review: t("labels.dang_review"), changes_requested: t("labels.can_sua"), draft: t("labels.nhap"), open: t("labels.dang_mo"),
  closed: t("labels.da_dong"), resolved: t("labels.da_xu_ly"), acknowledged: t("labels.da_nhan"), mitigated: t("labels.da_giam_nhe"), investigating: t("labels.dang_dieu_tra"),
  ready: t("labels.san_sang"), provisioning: t("labels.dang_chuan_bi"), deployed: t("labels.da_trien_khai"), deploying: t("labels.dang_trien_khai"), rolled_back: t("labels.da_rollback"),
  promoted: t("labels.da_thang_cap"), paused: t("labels.tam_dung"), skipped: t("labels.bo_qua"), insufficient_data: t("labels.thieu_du_lieu"), healthy: t("labels.khoe"), degraded: t("labels.suy_giam"),
  unhealthy: t("labels.khong_khoe"), online: t("labels.truc_tuyen"), offline: t("labels.ngoai_tuyen"), sent: t("labels.da_gui"), delivered: t("labels.da_giao"), merged: t("labels.da_merge"),
  clean: t("labels.sach"), dirty: t("labels.co_thay_doi"), verified: t("labels.da_xac_minh"), unverified: t("labels.chua_xac_minh"), signed: t("labels.da_ky"), backlog: t("labels.ton_dong"),
  todo: t("labels.can_lam"), retired: t("labels.nghi_viec"), archived: t("labels.da_luu_tru"), new: t("labels.moi"), scheduled: t("labels.da_hen"), fired: t("labels.da_kich_hoat"), matched: t("labels.khop"),
  green: "Xanh", yellow: t("labels.vang"), red: t("labels.do"), at_risk: t("labels.co_rui_ro"), on_track: t("labels.dung_huong"), off_track: t("labels.lech_huong"),
  // mức độ / ưu tiên / rủi ro
  critical: t("labels.nghiem_trong"), high: "Cao", medium: t("labels.trung_binh"), mid: t("labels.trung_binh"), low: t("labels.thap"), info: t("labels.thong_tin"), none: t("labels.khong"),
  urgent: t("labels.khan"), normal: t("labels.binh_thuong"), sev1: "SEV1", sev2: "SEV2", sev3: "SEV3",
}));

export function viStatus(s?: string | null): string {
  if (s == null || s === "") return "—";
  const k = String(s).toLowerCase();
  return VI[k] || String(s).replace(/_/g, " ");
}

export function viBool(b: unknown, yes = t("labels.bat"), no = t("labels.tat")) { return b ? yes : no; }

/** Giờ ngắn kiểu Việt Nam (dd/mm HH:mm) — "—" khi trống. */
export function viTime(s?: string | null): string {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  if (isNaN(d.getTime())) return String(s);
  return d.toLocaleString(intlLocale(), {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
}
