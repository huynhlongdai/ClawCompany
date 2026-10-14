"use client";
import {useEffect, useState} from "react";
import {apiSeat} from "../lib/api";
import {Icon, IconName} from "./Icon";
import {t as tr, lazy, intlLocale} from "../lib/i18n";

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

const TABS: {id: TabId; label: string; icon: IconName; hint: string}[] = lazy(() => ([
  {id: "profile", label: tr("seat.ho_so"), icon: "users",
   hint: tr("seat.ten_chuc_danh_emoji_identity")},
  {id: "personality", label: tr("seat.tinh_cach"), icon: "sparkle",
   hint: tr("seat.soul_md_giong_dieu_va")},
  {id: "job", label: tr("seat.cong_viec"), icon: "doc",
   hint: tr("seat.agents_md_la_quy_tac")},
  {id: "capability", label: tr("seat.nang_luc"), icon: "chart",
   hint: tr("seat.model_muc_suy_nghi_nen")},
  {id: "permission", label: tr("seat.quyen"), icon: "shield",
   hint: tr("seat.tool_sandbox_skill_tab_nguy")},
  {id: "budget", label: tr("seat.han_muc"), icon: "pulse",
   hint: tr("seat.heartbeat_va_khoi_luong_viec")},
]));

/* Trường cấu hình của ba tab sau. Nhãn tiếng Việt, kèm gợi ý đủ để người không
   phải kỹ sư quyết định được. `advice` là khuyến nghị của lượt tiếp nhận, dựa
   trên mục 7 của docs/ARCHITECTURE_TREE.md. */
const CONFIG_FIELDS: Record<string, {key: string; label: string; hint?: string;
                                     options?: string[]; advice?: string}[]> = lazy(() => ({
  capability: [
    {key: "model", label: tr("seat.model_chinh"),
     hint: tr("seat.dang_provider_model_khai_bang")},
    {key: "thinkingDefault", label: tr("seat.muc_suy_nghi"),
     options: ["off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max"],
     advice: tr("seat.seat_quan_ly_high_seat")},
    {key: "timeoutSeconds", label: tr("seat.thoi_gian_toi_da_moi")},
    {key: "compaction.notifyUser", label: tr("seat.bao_khi_nen_ngu_canh"),
     options: ["true", "false"], advice: tr("seat.nen_bat_nguoi_dung_biet")},
  ],
  permission: [
    {key: "sandbox.mode", label: tr("seat.che_do_sandbox"), options: ["off", "non-main", "all"],
     advice: tr("seat.nen_all_mac_dinh_cua")},
    {key: "sandbox.workspaceAccess", label: tr("seat.quyen_vao_workspace"),
     options: ["none", "ro", "rw"]},
    {key: "sandbox.docker.network", label: tr("seat.mang_cua_sandbox"), options: ["none", "bridge"],
     advice: tr("seat.none_tru_khi_seat_nay")},
    {key: "tools.profile", label: tr("seat.bo_tool")},
  ],
  budget: [
    {key: "heartbeat.every", label: tr("seat.nhip_heartbeat"),
     hint: tr("seat.vi_du_30m_1h_hoac"),
     advice: tr("seat.tat_cho_seat_thua_hanh")},
    {key: "heartbeat.activeHours.start", label: tr("seat.gio_bat_dau_hh_mm")},
    {key: "heartbeat.activeHours.end", label: tr("seat.gio_ket_thuc_hh_mm")},
    {key: "maxConcurrent", label: tr("seat.so_luot_chay_song_song")},
  ],
}));

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
          setError(tr("seat.member_khong_co_seat_agent", {p0: memberId})
            + tr("seat.day_co_the_la_mot"));
          return;
        }
        setAgentId(found.id);
      } catch (e: any) {
        setError(e?.message || tr("seat.khong_tra_duoc_seat_cua"));
      }
    })();
  }, [memberId]);

  if (error) return <div className="v8Error">{error}</div>;
  if (agentId == null) return <div className="v8Empty">{tr("seat.dang_tra_seat")}</div>;
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
      setError(e?.message || tr("seat.khong_tai_duoc_ho_so"));
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [agentId]);

  if (loading && !data) return <div className="v8Empty">{tr("seat.dang_tai_ho_so")}</div>;
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
          <b>{seat.name || tr("seat.khong_ten")}</b>
          <small style={{display: "block"}}>
            {[seat.role, seat.department, seat.company].filter(Boolean).join(" · ")}
            {seat.manager ? tr("seat.bao_cao_cho", {p0: seat.manager}) : ""}
          </small>
        </div>
        <span className={`statusPill${data.roster_match === false ? " busy" : ""}`}>
          {data.roster_match === true ? tr("seat.khop_gateway")
            : data.roster_match === false ? tr("seat.khong_co_tren_gateway")
            : tr("seat.chua_ro")}
        </span>
      </div>

      <section className="v14Metrics"
               style={{gridTemplateColumns: "repeat(auto-fit,minmax(178px,1fr))"}}>
        <Kpi label="Seat runtime" value={data.runtime_agent_id || "—"} icon="mesh" source="db"/>
        <Kpi label={tr("seat.vong_doi")} value={seat.lifecycle || "—"} icon="check" source="db"/>
        <Kpi label={tr("seat.model_dang_chay")}
             value={modelOf(data.config?.effective?.model) || seat.model_recorded_in_db || "—"}
             icon="sparkle"
             source={modelOf(data.config?.effective?.model) ? "gateway" : "db"}/>
        <Kpi label={tr("seat.chi_phi_30_ngay")}
             value={seat.cost_30d != null ? `$${Number(seat.cost_30d).toFixed(2)}` : "—"}
             icon="chart" source="db" note={seat.cost_source}/>
      </section>

      {/* Hạn mức ký tự của toàn bộ hồ sơ. Vượt là bị cắt âm thầm. */}
      <div style={{marginTop: 14}}>
        <div style={{display: "flex", justifyContent: "space-between", fontSize: 13}}>
          <span>{tr("seat.tong_ho_so")} {budget.total_chars?.toLocaleString(intlLocale())} / {budget.total_max_chars?.toLocaleString(intlLocale())} {tr("seat.ky_tu")}</span>
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
        <b>{tr("seat.can_biet")}</b>
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
      {tr("seat.nguon")} {source === "db" ? "database" : "gateway"}{note ? " *" : ""}
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
  if (!mine.length) return <div className="v8Empty">{tr("seat.khong_doc_duoc_file_nao")}</div>;
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
      setMsg(tr("seat.da_luu", {p0: out.note || ""}));
      onSaved();
    } catch (e: any) {
      const detail = e?.detail || e?.body?.detail;
      if (detail?.reason === "file_conflict") {
        setConflict(detail.message || tr("seat.file_vua_bi_nguoi_khac"));
      } else {
        setMsg(detail?.message || e?.message || tr("seat.luu_that_bai"));
      }
    } finally { setBusy(false); }
  }

  return <div style={{marginBottom: 20}}>
    <div style={{display: "flex", justifyContent: "space-between", alignItems: "baseline"}}>
      <b>{file.name}</b>
      <small style={{color: over ? "var(--risk)" : "var(--muted)"}}>
        {text.length.toLocaleString(intlLocale())} / {max.toLocaleString(intlLocale())} {tr("seat.ky_tu")}
        {file.name === "USER.md" ? tr("seat.han_muc_rieng_nho_hon") : ""}
      </small>
    </div>

    {file.missing && <div className="v8Empty" style={{margin: "8px 0"}}>
      {tr("seat.file_chua_ton_tai")}{file.expected_absent ? tr("seat.dieu_nay_binh_thuong") : ""}{tr("seat.luu_se_tao_moi")}
    </div>}

    {file.looks_like_shipped_sample && <div className="v8Error" style={{margin: "8px 0"}}>
      {tr("seat.file_nay_van_la")} <b>{tr("seat.ban_mau_xuat_xuong_cua")}</b> {tr("seat.noi_dung_ve_c_3po")}
    </div>}

    <textarea value={text} onChange={e => setText(e.target.value)} rows={16}
              spellCheck={false}
              style={{width: "100%", fontFamily: "ui-monospace, monospace", fontSize: 13,
                      padding: 12, borderRadius: 10,
                      border: `1px solid ${over ? "var(--risk)" : "var(--line)"}`}}/>

    {over && <div className="v8Error" style={{marginTop: 8}}>
      {tr("seat.vuot_han_muc")} {max.toLocaleString(intlLocale())} {tr("seat.ky_tu_openclaw_se")} <b>{tr("seat.cat_bot_khi_dung_prompt")}</b>{tr("seat.nen_agent_chi_doc_duoc")}
    </div>}

    {conflict && <div className="v8Error" style={{marginTop: 8}}>
      {conflict}{" "}
      <button onClick={onSaved} style={{marginLeft: 8}}>{tr("seat.tai_lai_ban_moi")}</button>
    </div>}

    <div style={{display: "flex", gap: 10, alignItems: "center", marginTop: 10}}>
      <button className="primary" onClick={save} disabled={busy || over || !dirty}>
        {busy ? tr("seat.dang_luu") : tr("seat.luu")}
      </button>
      {dirty && !busy && <small>{tr("seat.chua_luu")}</small>}
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
    if (key === "model") cursor = modelOf(cursor);
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
      setMsg(out.no_op ? tr("seat.khong_co_gi_thay_doi")
        : tr("seat.da_luu_thiet_lap", {p0: (out.changed_paths || []).length})
          + (out.requires_restart ? tr("seat.can_khoi_dong_lai_gateway") : tr("seat.ap_dung_ngay")));
      setDraft({});
      onSaved();
    } catch (e: any) {
      const detail = e?.detail || e?.body?.detail;
      setMsg(detail?.message || e?.message || tr("seat.luu_that_bai"));
    } finally { setBusy(false); }
  }

  if (!fields.length) return <div className="v8Empty">{tr("seat.tab_nay_chua_co_truong")}</div>;

  return <div>
    {fields.map(f => {
      const value = draft[f.key] ?? currentValue(f.key);
      return <div key={f.key} style={{marginBottom: 16}}>
        <div style={{display: "flex", justifyContent: "space-between"}}>
          <b style={{fontSize: 14}}>{f.label}</b>
          <small style={{opacity: .7}}>
            {isInherited(f.key) ? tr("seat.thua_huong_tu_agents_defaults") : tr("seat.cua_rieng_seat_nay")}
          </small>
        </div>
        {f.hint && <small style={{display: "block", marginBottom: 4}}>{f.hint}</small>}

        {f.options
          ? <select value={value} onChange={e => setDraft({...draft, [f.key]: e.target.value})}
                    style={{padding: 8, borderRadius: 8, border: "1px solid var(--line)"}}>
              <option value="">{tr("seat.chua_dat")}</option>
              {f.options.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          : <input value={value} onChange={e => setDraft({...draft, [f.key]: e.target.value})}
                   style={{width: "100%", padding: 8, borderRadius: 8,
                           border: "1px solid var(--line)"}}/>}

        {f.advice && <small style={{display: "block", marginTop: 4, opacity: .85}}>
          <b>{tr("seat.goi_y")}</b> {f.advice}
        </small>}

        {/* Đổi giá trị thừa hưởng nghĩa là tạo giá trị riêng cho seat — nói ra,
            vì người dùng dễ tưởng mình đang sửa cho cả công ty (hoặc ngược lại). */}
        {draft[f.key] !== undefined && isInherited(f.key) &&
          <small style={{display: "block", marginTop: 4}}>
            {tr("seat.luu_se_tao_gia_tri")}
          </small>}
      </div>;
    })}

    <div style={{display: "flex", gap: 10, alignItems: "center"}}>
      <button className="primary" onClick={save} disabled={busy || !changed.length}>
        {busy ? tr("seat.dang_luu") : tr("seat.luu_thay_doi", {p0: changed.length || ""})}
      </button>
      {msg && <small>{msg}</small>}
    </div>
  </div>;
}

/* M3: model thừa hưởng từ agents.defaults có dạng {primary, fallbacks}; model
   riêng của seat là chuỗi. Agent tạo bằng agents.create rơi vào dạng đầu — render
   thẳng object làm cả trang hồ sơ sập ("Objects are not valid as a React child"). */
function modelOf(v: any): string {
  if (v && typeof v === "object") return String(v.primary || "");
  return v ? String(v) : "";
}
