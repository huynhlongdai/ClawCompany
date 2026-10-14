"use client";
import {useEffect, useMemo, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiMcp, errorText} from "../lib/api";
import {t as tr, lazy, intlLocale} from "../lib/i18n";
import {ErrorBanner} from "./ui/EmptyState";

/* D1.5 + D1.6 — "Công cụ của agent".

   Trước D1.5 agent không có tool nào đọc dữ liệu công ty, nên Nina trả lời
   "công ty có mấy dự án" bằng kiến thức chung. Trang này cho admin thấy và
   chỉnh đúng ba thứ quyết định agent được làm gì:
   * ma trận tool × bậc ghế (trưởng nhóm / thực thi), ba mức: được dùng,
     hỏi duyệt (tạo Approval, cấp 24h khi duyệt), tắt (MCP trả 403);
   * đoạn cấu hình để gắn máy chủ MCP vào OpenClaw;
   * nhật ký gọi tool lấy thẳng từ event bus (`mcp.tool.called/denied`). */

type Row = Record<string, any>;

const LEVEL_VI: Record<string, {text: string; cls: string}> = lazy(() => ({
  allowed: {text: tr("tools.duoc_dung"), cls: "low"},
  ask: {text: tr("tools.hoi_duyet"), cls: "mid"},
  off: {text: tr("tools.tat"), cls: "high"},
}));
const REASON_VI: Record<string, string> = lazy(() => ({
  level_off: tr("tools.quyen_dang_tat"), scope: tr("tools.api_key_thieu_scope"),
}));
const TIER_VI: Record<string, string> = lazy(() => ({lead: tr("tools.truong_nhom"), executor: tr("tools.thuc_thi")}));
const GROUP_VI: Record<string, string> = lazy(() => ({
  context: tr("tools.ngu_canh"), work: tr("tools.cong_viec"), knowledge: tr("tools.tri_thuc"), collab: tr("tools.phoi_hop"),
  control: tr("tools.kiem_soat"), report: tr("tools.bao_cao"),
}));

/* /auth/me trả User, không có vai trò; vai trò nằm trong JWT đang đăng nhập.
   Chỉ dùng để ẩn/hiện ô chọn — backend vẫn chặn PUT bằng require_role("admin"). */
function tokenRole(): string {
  try {
    const t = localStorage.getItem("clawcompany_token") || "";
    const body = t.split(".")[1] || "";
    return JSON.parse(atob(body.replace(/-/g, "+").replace(/_/g, "/"))).role || "";
  } catch { return ""; }
}

function when(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(intlLocale(),
    {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"});
}

function payloadOf(ev: Row): Row {
  if (ev.payload && typeof ev.payload === "object") return ev.payload;
  try { return JSON.parse(ev.payload_json || "{}"); } catch { return {}; }
}

function Pill({level}: {level: string}) {
  const l = LEVEL_VI[level] || {text: level, cls: "mid"};
  return <span className={`ui-pill ${l.cls}`}>{l.text}</span>;
}

export function AgentToolsConsole() {
  const [perm, setPerm] = useState<Row | null>(null);
  const [catalog, setCatalog] = useState<Row | null>(null);
  const [log, setLog] = useState<Row[]>([]);
  const [members, setMembers] = useState<Row[]>([]);
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState("");
  const [filter, setFilter] = useState("");

  async function load() {
    setError("");
    try {
      const [p, c, m] = await Promise.all([apiMcp.permissions(), apiMcp.tools(), api.members()]);
      setPerm(p); setCatalog(c); setMembers(m || []);
    } catch (e) { setError(errorText(e, tr("tools.khong_tai_duoc_bang_quyen"))); }
    try { setLog(await apiMcp.toolLog(40)); }
    catch (e) { setError(errorText(e, tr("tools.khong_tai_duoc_nhat_ky"))); }
  }
  useEffect(() => { setRole(tokenRole()); load(); }, []);

  const isAdmin = ["owner", "admin"].includes(role);
  const memberName = useMemo(() => {
    const map: Record<number, string> = {};
    for (const m of members) map[m.id] = m.name || m.email || `#${m.id}`;
    return map;
  }, [members]);
  const scopeOf = useMemo(() => {
    const map: Record<string, string> = {};
    for (const t of catalog?.tools || []) map[t.name] = t.scope;
    return map;
  }, [catalog]);

  async function change(tool: string, role: string, level: string) {
    setSaving(`${tool}:${role}`); setError("");
    try { setPerm(await apiMcp.setPermission({tool, role, level})); }
    catch (e) { setError(errorText(e, tr("tools.khong_luu_duoc_quyen"))); }
    finally { setSaving(""); }
  }

  const tools: Row[] = (perm?.tools || []).filter((t: Row) =>
    !filter || t.name.includes(filter) || (t.description || "").toLowerCase().includes(filter.toLowerCase()));
  const tiers: string[] = perm?.tiers || ["lead", "executor"];
  const counts = useMemo(() => {
    const c: Record<string, Record<string, number>> = {};
    for (const tier of tiers) {
      c[tier] = {allowed: 0, ask: 0, off: 0};
      for (const t of perm?.tools || []) {
        const lv = perm?.matrix?.[tier]?.[t.name]?.level;
        if (lv in c[tier]) c[tier][lv] += 1;
      }
    }
    return c;
  }, [perm]);

  const base = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api").replace(/\/$/, "");
  const snippet = JSON.stringify({
    mcp: {servers: {clawcompany: {
      url: `${base}/mcp`,
      transport: "streamable-http",
      headers: {"X-API-Key": tr("tools.api_key_gan_voi_ghe")},
      toolFilter: ["company_*"],
    }}},
  }, null, 2);

  return <PageFrame title={tr("tools.cong_cu_cua_agent")}
      subtitle={tr("tools.may_chu_mcp_tool_company", {p0: catalog?.server?.name || "clawcompany", p1: catalog?.count ?? "…"})}>
    {error && <ErrorBanner error={error}  testId="tools-error"/>}

    <div className="ui-grid is-2">
      <section className="ui-panel ui-panel-body">
        <div className="lab-cardhead"><div><b>{tr("tools.tom_tat_quyen")}</b>
          <span>{tr("tools.agent_khong_co_dong_quyen")}</span></div></div>
        <div data-testid="tool-counts" style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12}}>
          {tiers.map(tier => <div key={tier} style={{border: "1px solid var(--border)", borderRadius: 10, padding: "10px 12px"}}>
            <div style={{fontSize: 12.5, color: "var(--text-muted)", marginBottom: 6}}>{TIER_VI[tier] || tier}</div>
            <div style={{display: "flex", gap: 6, flexWrap: "wrap"}}>
              <span className="ui-pill is-low">{counts[tier]?.allowed ?? 0} {tr("tools.duoc_dung_2")}</span>
              <span className="ui-pill is-mid">{counts[tier]?.ask ?? 0} {tr("tools.hoi_duyet_2")}</span>
              <span className="ui-pill is-high">{counts[tier]?.off ?? 0} {tr("tools.tat_2")}</span>
            </div></div>)}
        </div>
        <p style={{fontSize: 13, color: "var(--text-muted)", margin: "12px 0 0"}}>
          {tr("tools.thu_tu_ap_dung_ngoai")} <code>{tr("tools.tool_lt_ten_gt")}</code> {tr("tools.trong_hop_viec_duyet_xong")}
          {perm?.member_overrides?.length ? tr("tools.dang_co_ngoai_le_theo", {p0: perm.member_overrides.length}) : ""}
        </p>
      </section>
      <section className="ui-panel ui-panel-body">
        <div className="lab-cardhead"><div><b>{tr("tools.gan_vao_openclaw")}</b>
          <span>{tr("tools.moi_ghe_agent_dung_mot")}</span></div></div>
        <pre data-testid="mcp-snippet" style={{fontSize: 12, background: "var(--paper-2, #efeee9)",
          padding: 12, borderRadius: 8, overflowX: "auto", margin: 0}}>{snippet}</pre>
      </section>
    </div>

    <section className="ui-panel ui-panel-body" data-testid="tool-matrix">
      <div className="lab-cardhead"><div><b>{tr("tools.ma_tran_quyen")}</b>
        <span>{isAdmin ? tr("tools.chon_muc_cho_tung_tool") : tr("tools.chi_admin_duoc_doi_quyen")}</span></div>
        <input placeholder={tr("tools.loc_tool")} value={filter} onChange={e => setFilter(e.target.value)}
               style={{maxWidth: 220}}/></div>
      <div style={{overflowX: "auto"}}>
        <table style={{width: "100%", borderCollapse: "collapse", fontSize: 13}}>
          <thead><tr style={{textAlign: "left", color: "var(--text-muted)"}}>
            <th style={{padding: "6px 8px"}}>Tool</th><th style={{padding: "6px 8px"}}>{tr("tools.nhom")}</th>
            <th style={{padding: "6px 8px"}}>Scope</th>
            {tiers.map(t => <th key={t} style={{padding: "6px 8px"}}>{TIER_VI[t] || t}</th>)}
          </tr></thead>
          <tbody>{tools.map(t => <tr key={t.name} style={{borderTop: "1px solid var(--border)"}}>
            <td style={{padding: "8px"}}><code>{t.name}</code>{t.writes && <span className="ui-pill is-mid"
              style={{marginLeft: 6}}>ghi</span>}
              <div style={{color: "var(--text-muted)", fontSize: 12}}>{t.description}</div></td>
            <td style={{padding: "8px"}}>{GROUP_VI[t.group] || t.group}</td>
            <td style={{padding: "8px"}}><small>{scopeOf[t.name] || "—"}</small></td>
            {tiers.map(tier => {
              const cell = perm?.matrix?.[tier]?.[t.name] || {level: "off", source: "default"};
              const key = `${t.name}:${tier}`;
              return <td key={tier} style={{padding: "8px", whiteSpace: "nowrap"}}>
                {isAdmin
                  ? <select aria-label={`${t.name} ${tier}`} data-testid={`perm-${key}`} value={cell.level}
                      disabled={saving === key} onChange={e => change(t.name, tier, e.target.value)}>
                      {(perm?.levels || ["allowed", "ask", "off"]).map((lv: string) =>
                        <option key={lv} value={lv}>{LEVEL_VI[lv]?.text || lv}</option>)}
                    </select>
                  : <Pill level={cell.level}/>}
                {cell.source === "override" && <small style={{marginLeft: 6, color: "var(--text-muted)"}}>{tr("tools.da_chinh")}</small>}
              </td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>
    </section>

    <section className="ui-panel ui-panel-body" data-testid="tool-log">
      <div className="lab-cardhead"><div><b>{tr("tools.nhat_ky_goi_tool")}</b>
        <span>{tr("tools.k40_luot_gan_nhat_tu")}</span></div>
        <button onClick={load}>{tr("tools.tai_lai")}</button></div>
      {log.length === 0
        ? <div className="ui-empty-line">{tr("tools.chua_co_agent_nao_goi")}</div>
        : <div className="ui-list">{log.map(ev => {
            const p = payloadOf(ev);
            const denied = ev.event_type === "mcp.tool.denied";
            const ok = !denied && p.ok;
            const pending = denied && p.reason === "ask_pending";
            const label = pending ? tr("tools.cho_duyet", {p0: p.approval_id ? ` · #${p.approval_id}` : ""})
              : denied ? tr("tools.tu_choi", {p0: REASON_VI[p.reason] || p.reason || ""})
              : ok ? `ok · ${p.ms ?? 0} ms` : tr("tools.loi", {p0: p.error || ""});
            return <div className="ui-row" key={ev.id}>
              <span><code>{p.tool || "?"}</code></span>
              <b className={`ui-pill ${ok ? "is-low" : pending ? "is-mid" : "is-high"}`}>{label}</b>
              <small>{memberName[ev.actor_member_id] || tr("tools.ghe", {p0: ev.actor_member_id ?? "?"})}
                {p.run_id ? tr("tools.luot_chay", {p0: p.run_id}) : ""} · {when(ev.occurred_at)}</small>
            </div>;
          })}</div>}
    </section>
  </PageFrame>;
}
