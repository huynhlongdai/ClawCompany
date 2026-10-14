/* Mọi lỗi hiện cho người dùng = chuyện gì xảy ra + làm gì tiếp, bằng tiếng Việt.
   Dùng chung cho ErrorState, Banner, Toast và error boundary của app. */
import {ApiError} from "./api";

export type Explained = {title: string; detail: string; fix: string; code?: string; requestId?: string; retry: boolean};

/* Một số câu tiếng Anh cố định từ backend (FastAPI) — dịch lại khi gặp. */
const EN_VI: [RegExp, string][] = [
  [/^invalid credentials$/i, "Sai email hoặc mật khẩu."],
  [/^not authenticated$/i, "Chưa đăng nhập."],
  [/^no access to organization$/i, "Tài khoản không có quyền vào tổ chức này."],
  [/could not validate credentials|token (has )?expired|signature has expired/i, "Phiên đăng nhập đã hết hạn."],
  [/^not found$/i, "Không tìm thấy dữ liệu."],
  [/^forbidden$|insufficient role|permission denied/i, "Bạn chưa có quyền làm việc này."],
  [/failed to fetch|networkerror|load failed/i, "Không kết nối được máy chủ API."],
];

export function translate(msg: string): string {
  const m = msg.trim();
  for (const [re, vi] of EN_VI) if (re.test(m)) return vi;
  return m;
}

export function explain(e: unknown, context = "Thao tác"): Explained {
  const err = e as ApiError & {message?: string};
  const status = typeof err?.status === "number" ? err.status : -1;
  const code = err?.code || "";
  const detail = translate(String(err?.message || e || "")).slice(0, 400);
  const base = {detail, code, requestId: err?.requestId, retry: true};
  if (status === 0 || code === "network" || /kết nối được máy chủ/i.test(detail))
    return {...base, title: "Không kết nối được máy chủ", fix: "Kiểm tra mạng và dịch vụ API (cổng 8000) đang chạy, rồi bấm Thử lại."};
  if (status === 401)
    return {...base, title: "Phiên đăng nhập đã hết hạn", fix: "Đăng nhập lại để tiếp tục — dữ liệu chưa lưu trên trang này sẽ mất.", retry: false};
  if (status === 403)
    return {...base, title: "Bạn chưa có quyền", fix: "Nhờ chủ công ty hoặc Quản trị nâng vai trong Đội ngũ › Người & quyền.", retry: false};
  if (status === 404)
    return {...base, title: "Không tìm thấy", fix: "Mục này có thể đã bị xoá hoặc chuyển. Quay lại danh sách và tải lại."};
  if (status === 409 || code === "stale_revision" || code === "already_decided")
    return {...base, title: "Dữ liệu vừa thay đổi", fix: "Ai đó (hoặc agent) vừa cập nhật mục này. Tải lại để xem bản mới rồi làm lại."};
  if (status === 422 || status === 400)
    return {...base, title: "Dữ liệu chưa hợp lệ", fix: "Xem lại các ô vừa nhập theo gợi ý bên dưới rồi gửi lại.", retry: false};
  if (status === 429)
    return {...base, title: "Thao tác quá nhanh", fix: "Đợi vài giây rồi thử lại."};
  if (status >= 500)
    return {...base, title: "Máy chủ gặp lỗi", fix: `Thử lại sau ít giây. Nếu lặp lại, gửi${err?.requestId ? ` mã yêu cầu ${err.requestId}` : " ảnh màn hình này"} cho người quản trị.`};
  return {...base, title: `${context} chưa thành công`, fix: "Thử lại. Nếu vẫn lỗi, tải lại trang."};
}
