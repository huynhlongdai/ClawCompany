/* Số đếm cho sidebar và chuông.

   Vỏ ứng dụng nằm trong từng trang (không nằm trong layout), nên mỗi lần
   chuyển trang nó mount lại. Giữ kết quả 30 giây ở cấp module để chuyển trang
   không bắn lại ba request và số không nhấp nháy về rỗng. */
import {api, apiV17} from "./api";

export type Counts = Record<string, number>;

let orgName = "";
export function getOrgName() { return orgName; }

let cache: {at: number; data: Counts} | null = null;
let inflight: Promise<Counts> | null = null;
const listeners = new Set<(c: Counts) => void>();

async function load(): Promise<Counts> {
  const [overview, approvals, tasks] = await Promise.allSettled([
    apiV17.overview(), api.approvals(), apiV17.tasks(),
  ]);
  const out: Counts = {};
  if (overview.status === "fulfilled") Object.assign(out, (overview.value as any)?.kpis || {});
  const pending = approvals.status === "fulfilled" && Array.isArray(approvals.value)
    ? approvals.value.filter((a: any) => a.status === "pending").length : 0;
  /* Số trên chuông = số việc cần anh RA TAY: phê duyệt chờ + nhiệm vụ bị
     chặn + kết quả chờ duyệt. Thông báo chưa đọc là thông tin, không tính —
     để con số này khớp đúng với dòng tóm tắt trong Hộp việc. */
  const stuck = tasks.status === "fulfilled" && Array.isArray(tasks.value)
    ? tasks.value.filter((t: any) => t.status === "blocked" || t.status === "review").length : 0;
  if (approvals.status === "fulfilled" || tasks.status === "fulfilled") out.inbox = pending + stuck;
  if (overview.status === "fulfilled") orgName = (overview.value as any)?.organization?.name || orgName;
  return out;
}

export function getCounts(force = false): Promise<Counts> {
  if (!force && cache && Date.now() - cache.at < 30_000) return Promise.resolve(cache.data);
  if (!inflight) {
    inflight = load().then(data => {
      cache = {at: Date.now(), data};
      listeners.forEach(fn => fn(data));
      return data;
    }).finally(() => { inflight = null; });
  }
  return inflight;
}

export function peekCounts(): Counts | null { return cache?.data || null; }

/** Gọi sau khi duyệt/đọc một mục để sidebar và chuông cập nhật ngay. */
export function refreshCounts() { return getCounts(true); }

export function subscribeCounts(fn: (c: Counts) => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
