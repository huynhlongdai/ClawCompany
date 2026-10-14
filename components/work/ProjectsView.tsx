"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {apiV17, apiV36} from "../../lib/api";
import {StatusPill, toneOf} from "../ui/StatusPill";
import {EmptyState, ErrorBanner, ErrorState} from "../ui/EmptyState";
import {SkeletonRows} from "../ui/Skeleton";
import {useToast} from "../ui/Toast";

/* Công việc › Dự án: tiến độ dẫn xuất từ việc, hạn chót sửa tại chỗ (projects.due_date, v36). */
const STATUS_VI: Record<string, string> = {active: "Đang chạy", planning: "Lên kế hoạch", paused: "Tạm dừng", completed: "Xong", archived: "Lưu trữ", draft: "Nháp"};
function daysLeft(due: string) {
  const d = Math.round((new Date(due + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()) / 86400000);
  return d < 0 ? {text: `quá hạn ${-d} ngày`, late: true} : d === 0 ? {text: "hạn hôm nay", late: true} : {text: `còn ${d} ngày`, late: false};
}

export function ProjectsView() {
  const [rows, setRows] = useState<any[] | null>(null), [error, setError] = useState<unknown>(null), [saveErr, setSaveErr] = useState<unknown>(null);
  const toast = useToast();
  const load = useCallback(() => { setError(null); apiV17.projects().then(r => setRows(r || [])).catch(setError); }, []);
  useEffect(() => { load(); }, [load]);
  async function setDue(id: number, value: string | null) {
    setSaveErr(null);
    try { await apiV36.setDueDate(id, value); setRows(rs => (rs || []).map(r => r.id === id ? {...r, due_date: value} : r)); toast(value ? "Đã đặt hạn chót" : "Đã bỏ hạn chót"); }
    catch (e) { setSaveErr(e); }
  }
  if (error) return <ErrorState error={error} onRetry={load} context="Tải dự án"/>;
  if (!rows) return <SkeletonRows n={5}/>;
  if (!rows.length) return <EmptyState mood="chao" title="Chưa có dự án" action={<Link className="ui-btn is-primary" href="/onboarding">Dựng công ty từ mẫu</Link>}>
    Việc luôn nằm trong một dự án. Dựng công ty từ mẫu sẽ có sẵn dự án đầu tiên, hoặc tạo ở trang Sửa dữ liệu tổ chức.</EmptyState>;
  return <div className="wk-projects" data-testid="wk-projects">
    {saveErr ? <ErrorBanner error={saveErr} onClose={() => setSaveErr(null)} context="Lưu hạn chót"/> : null}
    <div className="ui-panel"><div className="ui-table-wrap"><table className="ui-table">
      <thead><tr><th>Dự án</th><th>Công ty</th><th style={{width: 180}}>Tiến độ</th><th className="is-num">Việc xong</th><th>Hạn chót</th><th>Trạng thái</th></tr></thead>
      <tbody>{rows.map(p => { const left = p.due_date ? daysLeft(p.due_date) : null;
        return <tr key={p.id}>
          <td>{p.name}</td><td>{p.company_name || "—"}</td>
          <td><div style={{display: "flex", alignItems: "center", gap: 8}}><div className="ui-meter" style={{flex: 1}}><i style={{width: `${p.progress || 0}%`}}/></div>
            <span className="ui-num" style={{fontSize: 12, color: "var(--text-muted)", minWidth: 34}}>{p.progress || 0}%</span></div></td>
          <td className="is-num">{p.tasks_done}/{p.tasks_total}</td>
          <td><input type="date" value={p.due_date || ""} aria-label={`Hạn chót ${p.name}`} onChange={e => setDue(p.id, e.target.value || null)}/>
            {left && <small style={{display: "block", marginTop: 2, color: left.late ? "var(--risk)" : undefined}}>{left.text}</small>}</td>
          <td><StatusPill tone={toneOf(p.status)}>{STATUS_VI[p.status] || p.status}</StatusPill></td>
        </tr>; })}</tbody>
    </table></div></div>
  </div>;
}
