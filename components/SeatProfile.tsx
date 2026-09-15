"use client";
import {useEffect, useState} from "react";
import {apiSeat} from "../lib/api";
import {Icon, IconName} from "./Icon";

/* WP-2.1 + WP-2.2 — Hồ sơ nhân sự AI, sáu tab.

   Đây là màn hình biến "cấu hình một agent" thành "tuyển và huấn luyện một
   nhân viên". Nguồn dữ liệu, tất cả đều thật:

   - GET   /api/agents/{id}/profile        gộp DB + roster gateway + 5 file + config
   - PUT   /api/agents/{id}/files/{name}   tab 1-3, ghi file với expectedHash
   - PATCH /api/agents/{id}/config         tab 4-6, ghi config qua ConfigRegistry

   Ba điều màn hình này phải nói thẳng, vì không nói thì người dùng mất dữ liệu:

   1. **Đếm ký tự.** Vượt hạn mức thì OpenClaw cắt âm thầm khi dựng prompt —
      file trên đĩa vẫn đủ, nhưng agent chỉ đọc được một phần tính cách của nó.
   2. **Xung đột hash.** Ghi bằng hash cũ trả 409; phải hiện "ai đó vừa sửa"
      kèm nút tải lại, không được ghi đè.
   3. **Nguồn của từng khối.** Khi một con số sai, câu hỏi đầu tiên luôn là
      "số này từ database hay từ gateway". */

type Row = Record<string, any>;
type TabId = "profile" | "personality" | "job" | "capability" | "permission" | "budget";

const TABS: {id: TabId; label: string; icon: IconName; hint: string}[] = [
  {id: "profile", label: "Hồ sơ", icon: "users",
   hint: "Tên, chức danh, emoji — IDENTITY.md và identity.* trong config"},
  {id: "personality", label: "Tính cách", icon: "sparkle",
   hint: "SOUL.md — giọng điệu và cách làm việc, nạp vào mọi phiên"},
  {id: "job", label: "Công việc", icon: "doc",
   hint: "AGENTS.md là quy tắc/SOP; USER.md là sở thích của người quản lý"},
  {id: "capability", label: "Năng lực", icon: "chart",
   hint: "Model, mức suy nghĩ, nén ngữ cảnh"},
  {id: "permission", label: "Quyền", icon: "shield",
   hint: "Tool, sandbox, skill — tab nguy hiểm nhất"},
  {id: "budget", label: "Hạn mức", icon: "pulse",
   hint: "Heartbeat và khối lượng việc song song — đây là tiền"},
];

/* Trường cấu hình của ba tab sau. Nhãn tiếng Việt, kèm gợi ý đủ để người không
   phải kỹ sư quyết định được. `advice` là khuyến nghị của lượt tiếp nhận, dựa
   trên mục 7 của docs/ARCHITECTURE_TREE.md. */
const CONFIG_FIELDS: Record<string, {key: string; label: string; hint?: string;
                                     options?: string[]; advice?: string}[]> = {
  capability: [
    {key: "model", label: "Model chính",
     hint: "Dạng provider/model. Khai bằng chuỗi là chế độ nghiêm — không có model dự phòng."},
    {key: "thinkingDefault", label: "Mức suy nghĩ",
     options: ["off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max"],
     advice: "Seat quản lý: high. Seat thừa hành: medium — nghĩ sâu là tiền."},
    {key: "timeoutSeconds", label: "Thời gian tối đa mỗi lượt (giây)"},
    {key: "compaction.notifyUser", label: "Báo khi nén ngữ cảnh",
     options: ["true", "false"], advice: "Nên bật: người dùng biết vì sao agent 'quên'."},
  ],
  permission: [
    {key: "sandbox.mode", label: "Chế độ sandbox", options: ["off", "non-main", "all"],
     advice: "Nên 'all'. Mặc định của OpenClaw là 'off', và workspace KHÔNG phải hàng rào cứng — đường dẫn tuyệt đối đi ra ngoài được."},
    {key: "sandbox.workspaceAccess", label: "Quyền vào workspace",
     options: ["none", "ro", "rw"]},
    {key: "sandbox.docker.network", label: "Mạng của sandbox", options: ["none", "bridge"],
     advice: "'none' trừ khi seat này thật sự cần Internet."},
    {key: "tools.profile", label: "Bộ tool"},
  ],
  budget: [
    {key: "heartbeat.every", label: "Nhịp heartbeat",
     hint: "Ví dụ 30m, 1h, hoặc 0m để tắt.",
     advice: "Tắt cho seat thừa hành. 50 seat × 48 lần/ngày là hoá đơn không ai ký."},
    {key: "heartbeat.activeHours.start", label: "Giờ bắt đầu (HH:MM)"},
    {key: "heartbeat.activeHours.end", label: "Giờ kết thúc (HH:MM)"},
    {key: "maxConcurrent", label: "Số lượt chạy song song tối đa"},
  ],
};

function pct(part: number, whole: number) {
  return Math.min(100, Math.round((part / Math.max(1, whole)) * 100));
}

/* URL của màn hình agent là /app/agents/{memberId} (đã có từ trước), còn API hồ
   sơ khoá theo `agents.id`. Component này nhận memberId rồi tự tra ra agentId
   qua GET /api/agents — đổi URL sẽ làm hỏng link người dùng đã lưu, và đổi khoá
   API sẽ làm hỏng quan hệ 1-1 giữa member và seat. */
export function SeatProfileByMember({memberId}: {memberId: number}) {
  const [agentId, setAgentId] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const rows = (await import("../lib/api")).api;
        const list = (await rows.agents()) as Row[];
        const found = (list || []).find(a => a.member_id === memberId);
        if (!found) {
          setError(`Member #${memberId} không có seat agent nào. `
            + `Đây có thể là một nhân sự người, hoặc seat chưa được tạo.`);
          return;
        }
        setAgentId(found.id);
      } catch (e: any) {
        setError(e?.message || "Không tra được seat của member này");
      }
    })();
  }, [memberId]);

  if (error) return <div className="v8Error">{error}</div>;
  if (agentId == null) return <div className="v8Empty">Đang tra seat…</div>;
  return <SeatProfile agentId={agentId}/>;
}

export function SeatProfile({agentId}: {agentId: number}) {
  const [data, setData] = useState<Row | null>(null);
  const [tab, setTab] = useState<TabId>("profile");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      setData(await apiSeat.profile(agentId));
      setError("");
    } catch (e: any) {
      setError(e?.message || "Không tải được hồ sơ seat");
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [agentId]);

  if (loading && !data) return <div className="v8Empty">Đang tải hồ sơ…</div>;
  if (error && !data) return <div className="v8Error">{error}</div>;
  if (!data) return null;

  const seat = data.seat || {};
  const files: Row[] = data.files || [];
  const budget = data.budget || {};

  return <>
    {/* ---------- đầu trang: ai, ở đâu, và seat có thật trên gateway không --- */}
    <div className="panel">
      <div className="panelHead">
        <div>
          <b>{seat.name || "(không tên)"}</b>
          <small style={{display: "block"}}>
            {[seat.role, seat.department, seat.company].filter(Boolean).join(" · ")}
            {seat.manager ? ` · báo cáo cho ${seat.manager}` : ""}
          </small>
        </div>
        <span className={`statusPill${data.roster_match === false ? " busy" : ""}`}>
          {data.roster_match === true ? "khớp gateway"
            : data.roster_match === false ? "không có trên gateway"
            : "chưa rõ"}
        </span>
      </div>

      <section className="v14Metrics"
               style={{gridTemplateColumns: "repeat(auto-fit,minmax(178px,1fr))"}}>
        <Kpi label="Seat runtime" value={data.runtime_agent_id || "—"} icon="mesh" source="db"/>
        <Kpi label="Vòng đời" value={seat.lifecycle || "—"} icon="check" source="db"/>
        <Kpi label="Model đang chạy"
             value={data.config?.effective?.model || seat.model_recorded_in_db || "—"}
             icon="sparkle"
             source={data.config?.effective?.model ? "gateway" : "db"}/>
        <Kpi label="Chi phí 30 ngày"
             value={seat.cost_30d != null ? `$${Number(seat.cost_30d).toFixed(2)}` : "—"}
             icon="chart" source="db" note={seat.cost_source}/>
      </section>

      {/* Hạn mức ký tự của toàn bộ hồ sơ. Vượt là bị cắt âm thầm. */}
      <div style={{marginTop: 14}}>
        <div style={{display: "flex", justifyContent: "space-between", fontSize: 13}}>
          <span>Tổng hồ sơ: {budget.total_chars?.toLocaleString("vi-VN")} / {budget.total_max_chars?.toLocaleString("vi-VN")} ký tự</span>
          <span style={{color: budget.over_budget ? "var(--risk)" : "var(--muted)"}}>
            {pct(budget.total_chars || 0, budget.total_max_chars || 1)}%
          </span>
        </div>
        <div className="progress" style={{marginTop: 6}}><span style={{
          width: `${pct(budget.total_chars || 0, budget.total_max_chars || 1)}%`,
          background: budget.over_budget ? "var(--risk)" : undefined,
        }}/></div>
      </div>

      {!!(data.warnings || []).length && <div className="v8Error" style={{marginTop: 12}}>
        <b>Cần biết:</b>
        <ul style={{margin: "6px 0 0 18px"}}>
          {data.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
        </ul>
      </div>}
    </div>

    {/* ---------- sáu tab ---------- */}
    <div className="panel">
      <div className="pillTabs">
        {TABS.map(t =>
          <button key={t.id} className={tab === t.id ? "active" : ""}
                  onClick={() => setTab(t.id)} title={t.hint}>
            <Icon name={t.icon} size={14}/> {t.label}
          </button>)}
      </div>
      <small style={{display: "block", margin: "2px 0 14px"}}>
        {TABS.find(t => t.id === tab)?.hint}
      </small>

      {["profile", "personality", "job"].includes(tab)
        ? <FileTabs agentId={agentId} tab={tab as TabId} files={files} onSaved={load}/>
        : <ConfigTab agentId={agentId} tab={tab} config={data.config || {}} onSaved={load}/>}
    </div>
  </>;
}

function Kpi({label, value, source, note, icon}:
             {label: string; value: string; source: "db" | "gateway";
              note?: string; icon: IconName}) {
  return <div className="metric">
    <div className="metricIcon"><Icon name={icon} size={16}/></div>
    <label>{label}</label>
    <strong style={{fontSize: 15, wordBreak: "break-word"}}>{value}</strong>
    {/* Nguồn của từng con số, để không ai phải đọc code mới biết. */}
    <small title={note || ""} style={{color: "var(--muted)", fontSize: 11}}>
      nguồn: {source === "db" ? "database" : "gateway"}{note ? " *" : ""}
    </small>
  </div>;
}

/* ---------------------------------------------------- tab 1-3: ghi file */

function FileTabs({agentId, tab, files, onSaved}:
                  {agentId: number; tab: TabId; files: Row[]; onSaved: () => void}) {
  const names = tab === "profile" ? ["IDENTITY.md"]
    : tab === "personality" ? ["SOUL.md"]
    : ["AGENTS.md", "USER.md"];
  const mine = files.filter(f => names.includes(f.name));
  if (!mine.length) return <div className="v8Empty">Không đọc được file nào cho tab này.</div>;
  return <>{mine.map(f => <FileEditor key={f.name} agentId={agentId} file={f} onSaved={onSaved}/>)}</>;
}

function FileEditor({agentId, file, onSaved}:
                    {agentId: number; file: Row; onSaved: () => void}) {
  const [text, setText] = useState<string>(file.content || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [conflict, setConflict] = useState("");

  useEffect(() => { setText(file.content || ""); }, [file.content]);

  const max: number = file.max_chars || 20000;
  const over = text.length > max;
  const dirty = text !== (file.content || "");

  async function save() {
    setBusy(true); setMsg(""); setConflict("");
    try {
      const out = await apiSeat.writeFile(agentId, file.name, text, file.hash || null);
      setMsg(`Đã lưu. ${out.note || ""}`);
      onSaved();
    } catch (e: any) {
      const detail = e?.detail || e?.body?.detail;
      if (detail?.reason === "file_conflict") {
        setConflict(detail.message || "File vừa bị người khác sửa.");
      } else {
        setMsg(detail?.message || e?.message || "Lưu thất bại");
      }
    } finally { setBusy(false); }
  }

  return <div style={{marginBottom: 20}}>
    <div style={{display: "flex", justifyContent: "space-between", alignItems: "baseline"}}>
      <b>{file.name}</b>
      <small style={{color: over ? "var(--risk)" : "var(--muted)"}}>
        {text.length.toLocaleString("vi-VN")} / {max.toLocaleString("vi-VN")} ký tự
        {file.name === "USER.md" ? " (hạn mức riêng, nhỏ hơn các file khác)" : ""}
      </small>
    </div>

    {file.missing && <div className="v8Empty" style={{margin: "8px 0"}}>
      File chưa tồn tại{file.expected_absent ? " — điều này bình thường" : ""}. Lưu sẽ tạo mới.
    </div>}

    {file.looks_like_shipped_sample && <div className="v8Error" style={{margin: "8px 0"}}>
      File này vẫn là <b>bản mẫu xuất xưởng của OpenClaw</b> (nội dung về "C-3PO"),
      nghĩa là tính cách của seat chưa từng được cấu hình. Viết lại theo đúng
      nhân sự bạn muốn.
    </div>}

    <textarea value={text} onChange={e => setText(e.target.value)} rows={16}
              spellCheck={false}
              style={{width: "100%", fontFamily: "ui-monospace, monospace", fontSize: 13,
                      padding: 12, borderRadius: 10,
                      border: `1px solid ${over ? "var(--risk)" : "var(--line)"}`}}/>

    {over && <div className="v8Error" style={{marginTop: 8}}>
      Vượt hạn mức {max.toLocaleString("vi-VN")} ký tự. OpenClaw sẽ <b>cắt bớt khi
      dựng prompt mà không báo</b>, nên agent chỉ đọc được phần đầu. Server sẽ từ
      chối lưu — hãy viết ngắn lại thay vì để hệ thống chọn hộ phần bị mất.
    </div>}

    {conflict && <div className="v8Error" style={{marginTop: 8}}>
      {conflict}{" "}
      <button onClick={onSaved} style={{marginLeft: 8}}>Tải lại bản mới</button>
    </div>}

    <div style={{display: "flex", gap: 10, alignItems: "center", marginTop: 10}}>
      <button className="primary" onClick={save} disabled={busy || over || !dirty}>
        {busy ? "Đang lưu…" : "Lưu"}
      </button>
      {dirty && !busy && <small>Chưa lưu</small>}
      {msg && <small>{msg}</small>}
      <small style={{marginLeft: "auto", opacity: .7}}>
        hash {String(file.hash || "").slice(0, 12) || "—"}…
      </small>
    </div>
  </div>;
}

/* ------------------------------------------------- tab 4-6: ghi config */

function ConfigTab({agentId, tab, config, onSaved}:
                   {agentId: number; tab: string; config: Row; onSaved: () => void}) {
  const fields = CONFIG_FIELDS[tab] || [];
  const effective: Row = config.effective || {};
  const own: Row = config.entry || {};

  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  function currentValue(key: string): string {
    const parts = key.split(".");
    let cursor: any = effective;
    for (const p of parts) cursor = cursor?.[p];
    return cursor === undefined || cursor === null ? "" : String(cursor);
  }

  function isInherited(key: string): boolean {
    const head = key.split(".")[0];
    return !(head in own);
  }

  const changed = Object.entries(draft).filter(([k, v]) => v !== currentValue(k));

  async function save() {
    setBusy(true); setMsg("");
    try {
      const values: Record<string, unknown> = {};
      for (const [k, v] of changed) {
        // Số và boolean phải gửi đúng kiểu: config schema của OpenClaw kiểm kiểu.
        values[k] = v === "true" ? true : v === "false" ? false
          : /^-?\d+$/.test(v) ? Number(v) : v;
      }
      const out = await apiSeat.writeConfig(agentId, tab, values,
                                            {baseHash: config.hash});
      setMsg(out.no_op ? "Không có gì thay đổi."
        : `Đã lưu ${(out.changed_paths || []).length} thiết lập.`
          + (out.requires_restart ? " Cần khởi động lại gateway." : " Áp dụng ngay."));
      setDraft({});
      onSaved();
    } catch (e: any) {
      const detail = e?.detail || e?.body?.detail;
      setMsg(detail?.message || e?.message || "Lưu thất bại");
    } finally { setBusy(false); }
  }

  if (!fields.length) return <div className="v8Empty">Tab này chưa có trường nào.</div>;

  return <div>
    {fields.map(f => {
      const value = draft[f.key] ?? currentValue(f.key);
      return <div key={f.key} style={{marginBottom: 16}}>
        <div style={{display: "flex", justifyContent: "space-between"}}>
          <b style={{fontSize: 14}}>{f.label}</b>
          <small style={{opacity: .7}}>
            {isInherited(f.key) ? "thừa hưởng từ agents.defaults" : "của riêng seat này"}
          </small>
        </div>
        {f.hint && <small style={{display: "block", marginBottom: 4}}>{f.hint}</small>}

        {f.options
          ? <select value={value} onChange={e => setDraft({...draft, [f.key]: e.target.value})}
                    style={{padding: 8, borderRadius: 8, border: "1px solid var(--line)"}}>
              <option value="">(chưa đặt)</option>
              {f.options.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          : <input value={value} onChange={e => setDraft({...draft, [f.key]: e.target.value})}
                   style={{width: "100%", padding: 8, borderRadius: 8,
                           border: "1px solid var(--line)"}}/>}

        {f.advice && <small style={{display: "block", marginTop: 4, opacity: .85}}>
          <b>Gợi ý:</b> {f.advice}
        </small>}

        {/* Đổi giá trị thừa hưởng nghĩa là tạo giá trị riêng cho seat — nói ra,
            vì người dùng dễ tưởng mình đang sửa cho cả công ty (hoặc ngược lại). */}
        {draft[f.key] !== undefined && isInherited(f.key) &&
          <small style={{display: "block", marginTop: 4}}>
            Lưu sẽ tạo giá trị riêng cho seat này, không đổi agents.defaults.
          </small>}
      </div>;
    })}

    <div style={{display: "flex", gap: 10, alignItems: "center"}}>
      <button className="primary" onClick={save} disabled={busy || !changed.length}>
        {busy ? "Đang lưu…" : `Lưu ${changed.length || ""} thay đổi`}
      </button>
      {msg && <small>{msg}</small>}
    </div>
  </div>;
}
