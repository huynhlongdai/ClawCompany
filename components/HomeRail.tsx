"use client";
import {useEffect, useState} from "react";
import {api, apiV10, apiV36} from "../lib/api";
import {Icon, IconName} from "./Icon";

/* Cột phải của Trang chủ — theo mockup: "Nhiệm vụ của bạn" với ba pill tab,
   dòng hoạt động, và panel Nina.

   Nguồn dữ liệu, tất cả đều thật:
   - "Cần duyệt"   -> GET /api/approvals   (action, risk, policy_key, evidence)
   - "Quan trọng"  -> GET /api/inbox       (priority = high)
   - "Hôm nay"     -> GET /api/inbox       (tạo trong 24h)
   - Hoạt động     -> GET /api/v10/events  (company event bus)

   - "Lịch hôm nay"  -> GET /api/v36/calendar (bảng calendar_events, v36)

   v36 đã thêm thực thể lịch, nên khối "Lịch hôm nay" của bản thiết kế nay là
   dữ liệu thật. Lịch trống nghĩa là chưa ai tạo mục nào — không phải lỗi tải,
   và cũng không đồng bộ từ Google/Outlook (chưa có tích hợp nào). */

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
  const [agenda, setAgenda] = useState<Row[]>([]);
  const [failed, setFailed] = useState<string[]>([]);

  useEffect(() => {
    // Mỗi nguồn hỏng độc lập: rail không được sập cả cột vì một endpoint lỗi.
    (async () => {
      const miss: string[] = [];
      try { setApprovals((await api.approvals() as Row[]) || []); } catch { miss.push("phê duyệt"); }
      try { setInbox((await api.inbox() as Row[]) || []); } catch { miss.push("hộp thư"); }
      try { setEvents(((await apiV10.events() as Row[]) || []).slice(0, 5)); } catch { miss.push("event bus"); }
      try { setAgenda(((await apiV36.calendar(1))?.events as Row[]) || []); } catch { miss.push("lịch"); }
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

    {/* ---------- lịch hôm nay (v36) ---------- */}
    <div className="panel">
      <div className="panelHead">
        <div><b>Lịch hôm nay</b></div>
        <small>calendar_events</small>
      </div>
      <div className="timeline">
        {agenda.map(e =>
          <div key={e.id} className="timeRow">
            <span>{String(e.starts_at || "").slice(11, 16) || "—"}</span>
            <div>
              <i/>
              <b>{e.title}</b>
              <small>
                {e.event_type}
                {e.owner_name ? ` · ${e.owner_name}` : ""}
                {e.location ? ` · ${e.location}` : ""}
              </small>
            </div>
          </div>)}
        {!agenda.length && <div className="v8Empty">
          Hôm nay chưa có mục lịch nào.
        </div>}
      </div>
    </div>

    {/* ---------- diễn biến từ event bus ---------- */}
    <div className="panel">
      <div className="panelHead">
        <div><b>Diễn biến hệ thống</b></div>
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

    </div>

    {/* ---------- Nina ---------- */}
    <NinaPanel/>

    {!!failed.length && <div className="v8Error">
      Không tải được: {failed.join(", ")}. Các phần còn lại vẫn là dữ liệu thật.
    </div>}
  </>;
}

/* Panel chat Nina. Gửi câu hỏi qua /api/v36/nina/ask -> chat.send -> gateway
   -> nhà cung cấp model. Không phải bộ trả lời theo luật: câu tự do cũng trả
   lời được, và cũng tốn tiền model thật, nên nút bị khoá khi đang chờ. */
function NinaPanel() {
  const [question, setQuestion] = useState("");
  const [log, setLog] = useState<{role: "me" | "nina"; text: string; meta?: string}[]>([]);
  const [busy, setBusy] = useState(false);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setQuestion("");
    setLog(prev => [...prev, {role: "me", text: message}]);
    setBusy(true);
    try {
      const out = await apiV36.askNina(message, 90);
      if (out?.answered) {
        setLog(prev => [...prev, {
          role: "nina", text: out.reply,
          meta: `${out.agent} · ${out.runtime_agent_id} · ${out.elapsed_seconds}s`,
        }]);
      } else {
        // Không trả lời được thì nói đúng lý do, không hiện câu chung chung.
        setLog(prev => [...prev, {
          role: "nina",
          text: out?.reason || out?.note || "Chưa nhận được trả lời.",
          meta: out?.timed_out ? "hết thời gian chờ — lượt chạy vẫn tiếp tục trong phiên" : "",
        }]);
      }
    } catch (e: any) {
      setLog(prev => [...prev, {role: "nina", text: String(e?.message || e).slice(0, 300)}]);
    } finally { setBusy(false); }
  }

  return <div className="ninaPanel">
    <div className="ninaTop">
      <span className="avatarSm">N</span>
      <div style={{flex: 1, minWidth: 0}}>
        <b>Nina</b>
        <small style={{display: "block"}}>AI Chief of Staff</small>
      </div>
      <span className={`statusPill${busy ? " busy" : ""}`}>{busy ? "đang nghĩ" : "sẵn sàng"}</span>
    </div>

    {!log.length && <div className="ninaBubble">
      Chào bạn ✦ Tôi đọc được số liệu công ty và trả lời qua gateway OpenClaw.
      Hỏi tự do cũng được — câu trả lời do model sinh ra, không phải câu mẫu.
    </div>}

    {log.map((line, i) =>
      <div key={i} className="ninaBubble"
           style={line.role === "me"
             ? {background: "var(--accent-soft)", borderColor: "#dcd9fb"}
             : undefined}>
        {line.text}
        {line.meta && <small style={{display: "block", marginTop: 6}}>{line.meta}</small>}
      </div>)}

    <div className="ninaChips">
      {["Công ty đang có mấy dự án đang chạy?",
        "Việc nào đang chờ phê duyệt?",
        "Tóm tắt tình hình hôm nay trong ba câu."].map(q =>
        <button key={q} onClick={() => send(q)} disabled={busy}>{q}</button>)}
    </div>

    <div className="ninaCompose">
      <input value={question} placeholder="Hỏi Nina bất cứ điều gì…"
             onChange={e => setQuestion(e.target.value)}
             onKeyDown={e => e.key === "Enter" && send(question)}
             disabled={busy}/>
      <button onClick={() => send(question)} disabled={busy || !question.trim()}
              title="Gửi câu hỏi tới model qua gateway">
        <Icon name="arrow-right" size={16}/>
      </button>
    </div>
  </div>;
}
