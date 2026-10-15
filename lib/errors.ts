/* Mọi lỗi hiện cho người dùng = chuyện gì xảy ra + làm gì tiếp, bằng tiếng Việt.
   Dùng chung cho ErrorState, Banner, Toast và error boundary của app. */
import type {ApiError} from "./http";
import {t, lazy} from "./i18n";

export type Explained = {title: string; detail: string; fix: string; code?: string; requestId?: string; retry: boolean};

/* Một số câu tiếng Anh cố định từ backend (FastAPI) — dịch lại khi gặp. */
const EN_VI: [RegExp, string][] = lazy(() => ([
  [/^invalid credentials$/i, t("errors.sai_email_hoac_mat_khau")],
  [/^not authenticated$/i, t("errors.chua_dang_nhap")],
  [/^no access to organization$/i, t("errors.tai_khoan_khong_co_quyen")],
  [/could not validate credentials|token (has )?expired|signature has expired/i, t("errors.phien_dang_nhap_da_het")],
  [/^not found$/i, t("errors.khong_tim_thay_du_lieu")],
  [/^forbidden$|insufficient role|permission denied/i, t("errors.ban_chua_co_quyen_lam")],
  [/failed to fetch|networkerror|load failed/i, t("errors.khong_ket_noi_duoc_may")],
]));

export function translate(msg: string): string {
  const m = msg.trim();
  for (const [re, vi] of EN_VI) if (re.test(m)) return vi;
  return m;
}

export function explain(e: unknown, context = t("errors.thao_tac")): Explained {
  const err = e as ApiError & {message?: string};
  const status = typeof err?.status === "number" ? err.status : -1;
  const code = err?.code || "";
  const detail = translate(String(err?.message || e || "")).slice(0, 400);
  const base = {detail, code, requestId: err?.requestId, retry: true};
  if (status === 0 || code === "network" || /kết nối được máy chủ/i.test(detail))
    return {...base, title: t("errors.khong_ket_noi_duoc_may_2"), fix: t("errors.kiem_tra_mang_va_dich")};
  if (status === 401)
    return {...base, title: t("errors.phien_dang_nhap_da_het_2"), fix: t("errors.dang_nhap_lai_de_tiep"), retry: false};
  if (status === 403)
    return {...base, title: t("errors.ban_chua_co_quyen"), fix: t("errors.nho_chu_cong_ty_hoac"), retry: false};
  if (status === 404)
    return {...base, title: t("errors.khong_tim_thay"), fix: t("errors.muc_nay_co_the_da")};
  if (status === 409 || code === "stale_revision" || code === "already_decided")
    return {...base, title: t("errors.du_lieu_vua_thay_doi"), fix: t("errors.ai_do_hoac_agent_vua")};
  if (status === 422 || status === 400)
    return {...base, title: t("errors.du_lieu_chua_hop_le"), fix: t("errors.xem_lai_cac_o_vua"), retry: false};
  if (status === 424)
    return {...base, title: t("errors.ben_ngoai_khong_tra_loi"), fix: t("errors.ben_ngoai_khong_tra_loi_fix"), retry: false};
  if (status === 429)
    return {...base, title: t("errors.thao_tac_qua_nhanh"), fix: t("errors.doi_vai_giay_roi_thu")};
  if (status >= 500)
    return {...base, title: t("errors.may_chu_gap_loi"), fix: t("errors.thu_lai_sau_it_giay", {p0: err?.requestId ? ` mã yêu cầu ${err.requestId}` : " ảnh màn hình này"})};
  return {...base, title: t("errors.chua_thanh_cong", {p0: context}), fix: t("errors.thu_lai_neu_van_loi")};
}
