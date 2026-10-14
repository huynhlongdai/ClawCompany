/* Nhãn tiếng Việt cho trạng thái/mức độ thô từ backend (giá trị enum tiếng Anh).
   Một chỗ cho mọi trang; giá trị lạ hiện nguyên văn (là id, không phải câu chữ). */
const VI: Record<string, string> = {
  // vòng đời chung
  active: "Đang hoạt động", inactive: "Không hoạt động", enabled: "Bật", disabled: "Tắt", on: "Bật", off: "Tắt",
  pending: "Đang chờ", queued: "Trong hàng", waiting: "Đang chờ", waiting_approval: "Chờ duyệt", awaiting_approval: "Chờ duyệt",
  running: "Đang chạy", in_progress: "Đang làm", started: "Đã bắt đầu", executing: "Đang thực thi", planned: "Đã lập", planning: "Đang lập",
  completed: "Hoàn tất", complete: "Hoàn tất", done: "Xong", succeeded: "Thành công", success: "Thành công", passed: "Đạt", ok: "Ổn",
  failed: "Thất bại", failure: "Thất bại", error: "Lỗi", errored: "Lỗi", breached: "Vi phạm", blocked: "Bị chặn", rejected: "Từ chối",
  cancelled: "Đã huỷ", canceled: "Đã huỷ", expired: "Hết hạn", revoked: "Đã thu hồi", released: "Đã trả", destroyed: "Đã huỷ bỏ",
  approved: "Đã duyệt", review: "Chờ duyệt", in_review: "Đang review", changes_requested: "Cần sửa", draft: "Nháp", open: "Đang mở",
  closed: "Đã đóng", resolved: "Đã xử lý", acknowledged: "Đã nhận", mitigated: "Đã giảm nhẹ", investigating: "Đang điều tra",
  ready: "Sẵn sàng", provisioning: "Đang chuẩn bị", deployed: "Đã triển khai", deploying: "Đang triển khai", rolled_back: "Đã rollback",
  promoted: "Đã thăng cấp", paused: "Tạm dừng", skipped: "Bỏ qua", insufficient_data: "Thiếu dữ liệu", healthy: "Khoẻ", degraded: "Suy giảm",
  unhealthy: "Không khoẻ", online: "Trực tuyến", offline: "Ngoại tuyến", sent: "Đã gửi", delivered: "Đã giao", merged: "Đã merge",
  clean: "Sạch", dirty: "Có thay đổi", verified: "Đã xác minh", unverified: "Chưa xác minh", signed: "Đã ký", backlog: "Tồn đọng",
  todo: "Cần làm", retired: "Nghỉ việc", archived: "Đã lưu trữ", new: "Mới", scheduled: "Đã hẹn", fired: "Đã kích hoạt", matched: "Khớp",
  green: "Xanh", yellow: "Vàng", red: "Đỏ", at_risk: "Có rủi ro", on_track: "Đúng hướng", off_track: "Lệch hướng",
  // mức độ / ưu tiên / rủi ro
  critical: "Nghiêm trọng", high: "Cao", medium: "Trung bình", mid: "Trung bình", low: "Thấp", info: "Thông tin", none: "Không",
  urgent: "Khẩn", normal: "Bình thường", sev1: "SEV1", sev2: "SEV2", sev3: "SEV3",
};

export function viStatus(s?: string | null): string {
  if (s == null || s === "") return "—";
  const k = String(s).toLowerCase();
  return VI[k] || String(s).replace(/_/g, " ");
}

export function viBool(b: unknown, yes = "Bật", no = "Tắt") { return b ? yes : no; }

/** Giờ ngắn kiểu Việt Nam (dd/mm HH:mm) — "—" khi trống. */
export function viTime(s?: string | null): string {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
  if (isNaN(d.getTime())) return String(s);
  return d.toLocaleString("vi-VN", {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
}
