/* Số đếm cho sidebar + chuông, tên tổ chức và danh sách công ty cho bộ đổi công ty.

   Shell nằm trong layout nên chỉ mount một lần; vẫn giữ cache 30 giây ở cấp
   module để các trang gọi refreshCounts() sau khi duyệt/đọc mà không bắn lặp.
   Hai nguồn gọi SONG SONG (trước UI v2: tổng quan + duyệt + việc chạy song song
   rồi mới gọi tóm tắt hộp việc — một thác nước 2 nhịp). */
import {useSyncExternalStore} from "react";
import {apiInboxHub, apiV17} from "./api";

export type Counts = Record<string, number>;
export type OrgInfo = {name: string; companies: {id: number; name: string; industry?: string}[]};

let org: OrgInfo = {name: "", companies: []};
export function getOrg() { return org; }
/** Giữ tương thích với code cũ. */
export function getOrgName() { return org.name; }

const hasToken = () => { try { return !!localStorage.getItem("clawcompany_token"); } catch { return false; } };

let cache: {at: number; data: Counts} | null = null;
let inflight: Promise<Counts> | null = null;
const listeners = new Set<(c: Counts) => void>();

async function load(): Promise<Counts> {
  const [overview, summary] = await Promise.allSettled([apiV17.overview(), apiInboxHub.summary()]);
  const out: Counts = {};
  if (overview.status === "fulfilled") {
    const o: any = overview.value || {};
    Object.assign(out, o.kpis || {});
    org = {name: o.organization?.name || org.name, companies: (o.companies || []).map((c: any) => ({id: c.id, name: c.name, industry: c.industry}))};
  }
  /* Số trên chuông = số "cần anh ra tay" của Hộp việc (duyệt + xem) — cùng nguồn với trang. */
  if (summary.status === "fulfilled") out.inbox = Number((summary.value as any)?.need_action ?? 0);
  return out;
}

export function getCounts(force = false): Promise<Counts> {
  // Chưa đăng nhập (màn đăng nhập vẫn nằm trong shell): không gọi API để khỏi bắn 401 vô ích.
  // Đăng nhập xong AuthGate phát "cc:auth" và useCounts() gọi lại với force.
  if (!hasToken()) return Promise.resolve({});
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
export function refreshCounts() { return getCounts(true); }
export function subscribeCounts(fn: (c: Counts) => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** Tên tổ chức + công ty cho lúc RENDER. Đọc getOrg() thẳng trong render gây lệch hydration
   (React #425/#422): HTML server có org rỗng, nhưng nếu getCounts() của Shell xong trước khi
   trang hydrate thì client đã có tên. useSyncExternalStore trả org rỗng lúc hydrate rồi mới
   cập nhật. */
const EMPTY_ORG: OrgInfo = {name: "", companies: []};
export function useOrg(): OrgInfo {
  return useSyncExternalStore(fn => subscribeCounts(() => fn()), () => org, () => EMPTY_ORG);
}
