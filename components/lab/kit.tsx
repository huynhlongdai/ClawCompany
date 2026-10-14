"use client";
import {Fragment, ReactNode, useCallback, useEffect, useRef, useState} from "react";
import {Panel} from "../ui/Panel";
import {StatusPill, toneOf} from "../ui/StatusPill";
import {EmptyState, ErrorBanner, ErrorState} from "../ui/EmptyState";
import {SkeletonRows} from "../ui/Skeleton";
import {useToast} from "../ui/Toast";
import {viStatus} from "../../lib/labels";

/* Bộ dựng trang Phòng thí nghiệm + trang phụ: đầu trang do PageFrame lo; ở đây chỉ có
   đoạn giới thiệu ngắn, dải số, bảng, danh sách, rỗng/lỗi — đều trên primitive components/ui.
   Mục tiêu: các console v8–v15 nhìn cùng một hệ với trang lõi, không cần CSS riêng từng trang. */
export type Any = Record<string, any>;
export {Panel};

/** Tải dữ liệu một lần (+ tải lại). Lỗi giữ nguyên object để explain() dịch sang tiếng Việt. */
export function useLoad<T>(fn: () => Promise<T>, init: T, deps: unknown[] = []) {
  const [data, setData] = useState<T>(init);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const fnRef = useRef(fn); fnRef.current = fn;
  const reload = useCallback(async () => {
    setLoading(true);
    try { setData(await fnRef.current()); setError(null); setLoaded(true); } catch (e) { setError(e); } finally { setLoading(false); }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, deps);
  return {data, setData, error, loading, loaded, reload};
}

/** Chạy một thao tác: khoá nút, báo lỗi tiếng Việt, toast khi xong. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(async (key: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(key); setError(null);
    try { const r = await fn(); if (done) toast(done); return r; } catch (e) { setError(e); return undefined; } finally { setBusy(null); }
  }, [toast]);
  return {busy, error, setError, run};
}

/** Khung trạng thái cho cả trang: chưa tải được lần nào → lỗi cả trang (có Thử lại) hoặc khung xương;
    đã có dữ liệu mà lần tải lại lỗi → dải báo lỗi trên đầu, giữ nội dung cũ. */
export function LabBody({q, children, context = "Tải dữ liệu"}: {
  q: {loading: boolean; loaded: boolean; error: unknown; reload: () => void}; children: ReactNode; context?: string;
}) {
  if (!q.loaded && q.error) return <ErrorState error={q.error} onRetry={q.reload} context={context}/>;
  if (!q.loaded) return <Panel><SkeletonRows n={4}/></Panel>;
  return <div className="lab">{q.error ? <ErrorBanner error={q.error} onRetry={q.reload} context={context}/> : null}{children}</div>;
}

/** Một đoạn nói thẳng module này làm gì và giới hạn của nó. */
export function Intro({children, flow}: {children: ReactNode; flow?: string[]}) {
  return <div className="lab-intro">
    <p>{children}</p>
    {flow && <ol className="lab-flow" aria-label="Các bước">{flow.map((s, i) => <li key={i}>{s}</li>)}</ol>}
  </div>;
}

export function Stats({items}: {items: [ReactNode, ReactNode, ReactNode?][]}) {
  return <div className="lab-stats">{items.map(([label, value, hint], i) =>
    <div key={i} className="lab-stat"><span>{label}</span><b>{value ?? "—"}</b>{hint ? <small>{hint}</small> : null}</div>)}</div>;
}

export function Pill({s, label}: {s?: string | null; label?: ReactNode}) {
  return <StatusPill tone={toneOf(s)}>{label ?? viStatus(s)}</StatusPill>;
}

export type Col<T> = {label: ReactNode; render: (row: T, i: number) => ReactNode; num?: boolean; hideSm?: boolean; nowrap?: boolean};

/** Bảng cuộn ngang trong khung (không bao giờ tràn trang). `empty` = câu nói rõ vì sao trống. */
export function Table<T extends Any>({cols, rows, empty, rowKey = (r: T, i: number) => r.id ?? i, testId}: {
  cols: Col<T>[]; rows: T[]; empty: string; rowKey?: (r: T, i: number) => string | number; testId?: string;
}) {
  if (!rows.length) return <p className="ui-empty-line" data-testid={testId}>{empty}</p>;
  return <div className="ui-table-wrap" data-testid={testId}><table className="ui-table lab-table">
    <thead><tr>{cols.map((c, i) => <th key={i} className={(c.num ? "is-num" : "") + (c.hideSm ? " lab-hide-sm" : "")}>{c.label}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={rowKey(r, i)}>{cols.map((c, j) =>
      <td key={j} className={(c.num ? "is-num" : "") + (c.hideSm ? " lab-hide-sm" : "") + (c.nowrap ? " lab-nowrap" : "")}>{c.render(r, i)}</td>)}</tr>)}</tbody>
  </table></div>;
}

/** Danh sách dòng: tiêu đề + mô tả phụ + phần cuối (thường là nhãn trạng thái). */
export function Rows<T extends Any>({rows, title, meta, end, empty, rowKey = (r: T, i: number) => r.id ?? i, onPick, picked}: {
  rows: T[]; title: (r: T) => ReactNode; meta?: (r: T) => ReactNode; end?: (r: T) => ReactNode; empty: string;
  rowKey?: (r: T, i: number) => string | number; onPick?: (r: T) => void; picked?: (r: T) => boolean;
}) {
  if (!rows.length) return <p className="ui-empty-line">{empty}</p>;
  return <div className="ui-list lab-rows">{rows.map((r, i) => {
    const inner = <><span className="ui-row-main"><span className="ui-row-title">{title(r)}</span>{meta && <span className="ui-row-meta">{meta(r)}</span>}</span>
      {end && <span className="ui-row-end">{end(r)}</span>}</>;
    return onPick
      ? <button type="button" key={rowKey(r, i)} className="ui-row" aria-pressed={picked?.(r) || undefined} onClick={() => onPick(r)}>{inner}</button>
      : <div key={rowKey(r, i)} className="ui-row">{inner}</div>;
  })}</div>;
}

export function KV({items}: {items: [ReactNode, ReactNode][]}) {
  return <dl className="ui-kv">{items.map(([k, v], i) => <Fragment key={i}><dt>{k}</dt><dd>{v ?? "—"}</dd></Fragment>)}</dl>;
}

export function Empty({title, children}: {title: string; children?: ReactNode}) {
  return <EmptyState compact title={title}>{children}</EmptyState>;
}

export function Grid({children, cols = 2}: {children: ReactNode; cols?: 2 | 3}) {
  return <div className={`ui-grid is-${cols}`}>{children}</div>;
}

/** JSON an toàn (backend trả nhiều cột *_json dạng chuỗi). */
export function parseJson<T>(s: unknown, fallback: T): T {
  if (s == null || s === "") return fallback;
  if (typeof s !== "string") return s as T;
  try { return JSON.parse(s) as T; } catch { return fallback; }
}
export const short = (s: unknown, n = 12) => String(s ?? "—").slice(0, n);
