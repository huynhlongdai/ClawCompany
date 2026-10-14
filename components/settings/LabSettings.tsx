"use client";
import Link from "next/link";
import {Icon} from "../Icon";
import {Panel} from "../ui/Panel";
import {Notice} from "../ui/EmptyState";
import {LAB_JOBS, LAB_PAGES} from "../../lib/nav";
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
    <Notice tone="wait">
      <b>Job nền chưa tắt theo cờ.</b> {LAB_JOBS.length} job Celery của các trang này vẫn chạy ({LAB_JOBS.join(", ")}); <code>v15.control_plane_tick</code> có thể đẩy
      phê duyệt lạ vào Hộp việc. Backend chưa có cờ môi trường cho việc này — việc tắt job được ghi lại để làm ở M0 (backend), không đổi hành vi backend trong lượt UI này.
    </Notice>
    {lab && areas.map(a => <Panel key={a} title={a} flush>
      <div className="ui-list">{LAB_PAGES.filter(p => p.area === a).map(p => <Link key={p.href} href={p.href} className="ui-row">
        <Icon name={p.icon} size={16}/><span className="ui-row-main"><span className="ui-row-title">{p.label}</span><span className="ui-row-meta">{p.desc}</span></span>
        <Icon name="chevron-right" size={14}/></Link>)}</div>
    </Panel>)}
  </div>;
}
