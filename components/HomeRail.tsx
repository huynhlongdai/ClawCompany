"use client";
import {useEffect, useState} from "react";
import {api, apiV10} from "../lib/api";
import {Icon, IconName} from "./Icon";

/* Cột phải của Trang chủ — theo mockup: "Nhiệm vụ của bạn" với ba pill tab,
   dòng hoạt động, và panel Nina.

   Nguồn dữ liệu, tất cả đều thật:
   - "Cần duyệt"   -> GET /api/approvals   (action, risk, policy_key, evidence)
   - "Quan trọng"  -> GET /api/inbox       (priority = high)
   - "Hôm nay"     -> GET /api/inbox       (tạo trong 24h)
   - Hoạt động     -> GET /api/v10/events  (company event bus)

   Mockup còn có "Lịch hôm nay" với các buổi họp. Hệ thống KHÔNG có thực thể
   lịch nào, nên thay vì bịa vài dòng cho đẹp, chỗ đó là dòng hoạt động thật
   từ event bus. Ô chat Nina cũng vậy: gateway dev không có credential model
   nên ô nhập bị khoá kèm lý do, thay vì giả vờ chat được. */

type Row = Record<string, any>;
type Tab = "approvals" | "important" | "today";

const RISK_CLASS: Record<string, string> = {high: "high", critical: "high", medium: "mid", low: "low"};
const RISK_LABEL: Record<string, string> = {
  critical: "Rất cao", high: "Cao", medium: "Trung bình", low: "Thấp",
};

/* Ô icon pastel chọn theo loại việc — cùng cách mockup phân biệt bằng màu. */
const KIND_STYLE: Record<string, {tint: string; icon: IconName}> = {
  approval: {tint: "pink", icon: "shield"},
  project: {tint: "blue", icon: "board"},
  task: {tint: "violet", icon: "check"},
  knowledge: {tint: "green", icon: "book"},
  report: {tint: "amber", icon: "chart"},
  default: {tint: "blue", icon: "doc"},
};

function ago(iso?: string) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 60) return `${mins} phút trước`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} giờ trước`;
  return `${Math.round(hours / 24)} ngày trước`;
}

function timeOf(iso?: string) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—"
    : d.toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"});
}

export function HomeRail() {
  const [tab, setTab] = useState<Tab>("approvals");
  const [approvals, setApprovals] = useState<Row[]>([]);
  const [inbox, setInbox] = useState<Row[]>([]);
  const [events, setEvents] = useState<Row[]>([]);
  const [failed, setFailed] = useState<string[]>([]);

  useEffect(() => {
    // Mỗi nguồn hỏng độc lập: rail không được sập cả cột vì một endpoint lỗi.
    (async () => {
      const miss: string[] = [];
      try { setApprovals((await api.approvals() as Row[]) || []); } catch { miss.push("phê duyệt"); }
      try { setInbox((await api.inbox() as Row[]) || []); } catch { miss.push("hộp thư"); }
      try { setEvents(((await apiV10.events() as Row[]) || []).slice(0, 6)); } catch { miss.push("event bus"); }
      setFailed(miss);
    })();
  }, []);

  const pending = approvals.filter(a => a.status === "pending");
  const important = inbox.filter(i => i.priority === "high");
  const today = inbox.filter(i => {
    const t = new Date(i.created_at || 0).getTime();
    return !Number.isNaN(t) && Date.now() - t < 24 * 3600 * 1000;
  });

  const TABS: [Tab, string, number][] = [
    ["approvals", "Cần duyệt", pending.length],
    ["important", "Quan trọng", important.length],
    ["today", "Hôm nay", today.length],
  ];

  function rowsFor(current: Tab) {
    if (current === "approvals") {
      return pending.map(a => ({
        key: `a${a.id}`,
        kind: "approval",
        title: a.action || "Yêu cầu phê duyệt",
        meta: [a.policy_key, ago(a.created_at)].filter(Boolean).join(" · "),
        risk: a.risk,
      }));
    }
    const source = current === "important" ? important : today;
    return source.map(i => ({
      key: `i${i.id}`,
      kind: i.item_type || "default",
      title: i.title || "(không tiêu đề)",
      meta: [i.source, ago(i.created_at)].filter(Boolean).join(" · "),
      risk: i.priority,
    }));
  }

  const rows = rowsFor(tab);

  return <>
    {/* ---------- nhiệm vụ của bạn ---------- */}
    <div className="panel">
      <div className="panelHead">
        <div><b>Nhiệm vụ của bạn</b></div>
        <a href="/app/workspace-ops">Xem tất cả →</a>
      </div>

      <div className="pillTabs">
        {TABS.map(([id, label, count]) =>
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            {label} ({count})
          </button>)}
      </div>

      <div>
        {rows.map(r => {
          const style = KIND_STYLE[r.kind] || KIND_STYLE.default;
          const cls = RISK_CLASS[String(r.risk || "").toLowerCase()] || "low";
          return <div key={r.key} className="railRow">
            <span className={`iconTile ${style.tint}`}><Icon name={style.icon} size={17}/></span>
            <div style={{minWidth: 0}}>
              <b>{r.title}</b>
              {r.meta && <small>{r.meta}</small>}
            </div>
            <span className={`prio ${cls}`}>
              {RISK_LABEL[String(r.risk || "").toLowerCase()] || "—"}
            </span>
          </div>;
        })}
        {!rows.length && <div className="v8Empty">
          {tab === "approvals" ? "Không có gì chờ duyệt." : "Không có mục nào."}
        </div>}
      </div>
    </div>

    {/* ---------- hoạt động (thay cho "lịch hôm nay" của mockup) ---------- */}
    <div className="panel">
      <div className="panelHead">
        <div><b>Diễn biến hôm nay</b></div>
        <small>từ event bus</small>
      </div>
      <div className="timeline">
        {events.map(e =>
          <div key={e.id} className="timeRow">
            <span>{timeOf(e.occurred_at)}</span>
            <div>
              <i/>
              <b>{e.event_type}</b>
              <small>{e.source || "hệ thống"}
                {e.aggregate_type ? ` · ${e.aggregate_type}#${e.aggregate_id}` : ""}</small>
            </div>
          </div>)}
        {!events.length && <div className="v8Empty">Chưa có diễn biến nào.</div>}
      </div>
      {/* Nói thẳng vì sao đây không phải lịch họp như mockup. */}
      <small style={{display: "block", marginTop: 10}}>
        Hệ thống chưa có thực thể lịch; chỗ này là event bus thật thay vì dữ liệu dựng sẵn.
      </small>
    </div>

    {/* ---------- Nina ---------- */}
    <div className="ninaPanel">
      <div className="ninaTop">
        <span className="avatarSm">N</span>
        <div style={{flex: 1, minWidth: 0}}>
          <b>Nina</b>
          <small style={{display: "block"}}>AI Chief of Staff</small>
        </div>
        <span className="statusPill off">chưa nối model</span>
      </div>

      <div className="ninaBubble">
        Chào bạn 👋 Tôi đọc được toàn bộ số liệu công ty, nhưng chưa trả lời được:
        gateway OpenClaw đang chạy mà <b>không có credential model</b>.
      </div>

      <div className="ninaChips">
        <a href="/app/os?tab=agents">Đội agent</a>
        <a href="/app/openclaw">Lõi OpenClaw</a>
        <a href="/app/live-runs">Phiên đang chạy</a>
        <a href="/app/sre-control">Nina SRE</a>
      </div>

      <div className="ninaCompose">
        <input placeholder="Cần credential model để chat…" disabled/>
        <button disabled title="Đặt credential model cho gateway OpenClaw để bật chat">
          <Icon name="arrow-right" size={16}/>
        </button>
      </div>
    </div>

    {!!failed.length && <div className="v8Error">
      Không tải được: {failed.join(", ")}. Các phần còn lại vẫn là dữ liệu thật.
    </div>}
  </>;
}
