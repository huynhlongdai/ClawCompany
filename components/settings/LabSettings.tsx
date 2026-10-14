"use client";
import Link from "next/link";
import {Icon} from "../Icon";
import {Panel} from "../ui/Panel";
import {useEffect, useState} from "react";
import {ErrorBanner, Notice} from "../ui/EmptyState";
import {StatusPill} from "../ui/StatusPill";
import {SkeletonRows} from "../ui/Skeleton";
import {api} from "../../lib/api";
import {LAB_PAGES} from "../../lib/nav";
import {useLab} from "../../lib/prefs";

/* Cờ Phòng thí nghiệm (plan-v2 §2): ẩn 27 trang ít dùng khỏi menu và ⌘K. Route vẫn chạy.
   Cờ nằm ở trình duyệt (localStorage) — mặc định tắt, bản cài đặt có thể bật sẵn bằng NEXT_PUBLIC_LAB=on. */
export function LabSettings() {
  const [lab, setLab] = useLab();
  const areas = Array.from(new Set(LAB_PAGES.map(p => p.area)));
  return <div className="ui-grid" style={{gap: 20}}>
    <Panel title="Phòng thí nghiệm" desc="Trang của các module chưa nằm trong lộ trình M0–M7: giao phần mềm, SRE, điều hành đời cũ">
      <label className="set-switch" data-testid="lab-toggle">
        <input type="checkbox" role="switch" checked={lab} onChange={e => setLab(e.target.checked)}/>
        <span><b>{lab ? "Đang bật" : "Đang tắt"}</b><small>{lab ? `${LAB_PAGES.length} trang hiện trong ⌘K và danh bạ bên dưới.` : `${LAB_PAGES.length} trang đang ẩn khỏi tìm kiếm. Link cũ vẫn mở được.`}</small></span>
      </label>
    </Panel>
    <LabJobsPanel/>
    {lab && areas.map(a => <Panel key={a} title={a} flush>
      <div className="ui-list">{LAB_PAGES.filter(p => p.area === a).map(p => <Link key={p.href} href={p.href} className="ui-row">
        <Icon name={p.icon} size={16}/><span className="ui-row-main"><span className="ui-row-title">{p.label}</span><span className="ui-row-meta">{p.desc}</span></span>
        <Icon name="chevron-right" size={14}/></Link>)}</div>
    </Panel>)}
  </div>;
}

/* Cờ backend LAB_JOBS_ENABLED: đọc từ /api/health/lab — trình duyệt không bật/tắt được, phải đổi env của api + worker. */
function LabJobsPanel() {
  const [st, setSt] = useState<{lab_jobs_enabled: boolean; env: string; jobs: string[]} | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const load = () => { setErr(null); api.labStatus().then(setSt).catch(setErr); };
  useEffect(load, []);
  const on = !!st?.lab_jobs_enabled;
  return <Panel title="Job nền của Phòng thí nghiệm" testId="lab-jobs"
    desc="Cờ máy chủ, khác với cờ ẩn trang ở trên: quyết định 6 job Celery của các module này có được lập lịch và chạy hay không"
    actions={st ? <StatusPill tone={on ? "wait" : "ok"}>{on ? "Đang chạy" : "Đã tắt"}</StatusPill> : undefined}>
    {err ? <ErrorBanner error={err} onRetry={load} context="Đọc trạng thái job nền"/> : !st ? <SkeletonRows n={2} h={28}/> : <>
      {on
        ? <Notice tone="wait"><b>{st.env}=true.</b> 6 job đang được lập lịch. <code>v15.control_plane_tick</code> có thể tạo phê duyệt SRE trong Hộp việc — chỉ bật khi anh thật sự dùng các trang giao phần mềm/SRE.</Notice>
        : <Notice tone="ok"><b>{st.env}=false (mặc định).</b> 6 job không được lập lịch; nếu bị gọi tay, task trả về ngay mà không đọc hay ghi dữ liệu. Muốn bật: đặt <code>{st.env}=true</code> cho api và worker rồi khởi động lại.</Notice>}
      <div className="ui-table-wrap" style={{marginTop: 12}}><table className="ui-table">
        <thead><tr><th>Job</th><th>Trạng thái</th></tr></thead>
        <tbody>{st.jobs.map(j => <tr key={j}><td><code>{j}</code></td><td><StatusPill tone={on ? "wait" : "neutral"}>{on ? "Lập lịch" : "Tắt"}</StatusPill></td></tr>)}</tbody>
      </table></div>
    </>}
  </Panel>;
}
