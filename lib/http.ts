/* Lõi HTTP dùng chung (tách khỏi lib/api.ts để trang nhỏ như /invite/[token] không phải
   kéo theo cả ~300 hàm gọi API): ApiError, describeError (lỗi JSON → câu dễ đọc), request(). */
import {getLocale} from "./i18n";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";

// T mặc định là any: 288 lời gọi request(...) trong file này không truyền type
// argument, nên nếu không có default chúng trả Promise<unknown> và mọi
// setState(await api...) đều là type error. Không có contract type sinh từ
// backend, nên any là mô tả trung thực hiện trạng, không phải cách né kiểu.
/** M1: lỗi API mang mã + câu tiếng Việt thay vì nguyên chuỗi JSON. */
export class ApiError extends Error {
  status:number; code:string; requestId:string; detail?:any;
  constructor(message:string, status:number, code="", requestId=""){
    super(message); this.name="ApiError"; this.status=status; this.code=code; this.requestId=requestId;
  }
}

export function describeError(status:number, text:string):ApiError{
  let body:any = null;
  try{ body = JSON.parse(text); }catch{ /* không phải JSON */ }
  const d = body?.detail;
  // Lỗi có cấu trúc {error, message, ...}: hiện câu `message` (tiếng Việt), giữ mã ở `code`.
  // Trước M4a nhánh này JSON.stringify cả object, nên người dùng thấy chuỗi JSON thô.
  let msg = typeof d === "string" ? d
    : Array.isArray(d) ? d.map((x:any)=>`${(x.loc||[]).slice(1).join(".")}: ${x.msg}`).join("; ")
    : d && typeof d.message === "string" ? d.message
    : d ? JSON.stringify(d) : (text || "");
  if(!msg){
    msg = status===401 ? "Phiên đăng nhập đã hết hạn, hãy đăng nhập lại."
      : status===403 ? "Bạn không có quyền làm việc này."
      : status===404 ? "Không tìm thấy dữ liệu."
      : status>=500 ? "Máy chủ gặp lỗi. Thử lại sau ít giây."
      : `Yêu cầu không hợp lệ (HTTP ${status}).`;
  }
  const rid = body?.request_id || "";
  const err = new ApiError(rid ? `${msg} (mã yêu cầu ${rid})` : msg, status,
    body?.code || (d && typeof d === "object" && !Array.isArray(d) ? d.error || "" : ""), rid);
  if(d && typeof d === "object" && !Array.isArray(d)) err.detail = d;
  return err;
}

export async function request<T = any>(path:string, init?:RequestInit):Promise<T>{
  const token = typeof window!=="undefined" ? localStorage.getItem("clawcompany_token") : null;
  let res:Response;
  try{
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {...(typeof FormData!=="undefined" && init?.body instanceof FormData ? {} : {"Content-Type":"application/json"}), "Accept-Language": getLocale(), ...(token?{Authorization:`Bearer ${token}`}:{ }), ...(init?.headers||{})},
      cache: "no-store",
    });
  }catch{
    throw new ApiError("Không kết nối được máy chủ API. Kiểm tra mạng hoặc dịch vụ api đang chạy.", 0, "network");
  }
  if(!res.ok){
    throw describeError(res.status, await res.text());
  }
  return res.json();
}

