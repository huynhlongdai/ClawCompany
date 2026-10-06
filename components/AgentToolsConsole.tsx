"use client";
import {useEffect, useMemo, useState} from "react";
import {AuthGate} from "./AuthGate";
import {V9AppShell} from "./V9AppShell";
import {api, apiMcp, errorText} from "../lib/api";

/* D1.5 + D1.6 — "Công cụ của agent".

   Trước D1.5 agent không có tool nào đọc dữ liệu công ty, nên Nina trả lời
   "công ty có mấy dự án" bằng kiến thức chung. Trang này cho admin thấy và
   chỉnh đúng ba thứ quyết định agent được làm gì:
   * ma trận tool × bậc ghế (trưởng nhóm / thực thi), ba mức: được dùng,
     hỏi duyệt (tạo Approval, cấp 24h khi duyệt), tắt (MCP trả 403);
   * đoạn cấu hình để gắn máy chủ MCP vào OpenClaw;
   * nhật ký gọi tool lấy thẳng từ event bus (`mcp.tool.called/denied`). */

type Row = Record<string, any>;

const LEVEL_VI: Record<string, {text: string; cls: string}> = {
  allowed: {text: "Được dùng", cls: "low"},
  ask: {text: "Hỏi duyệt", cls: "mid"},
  off: {text: "Tắt", cls: "high"},
};
const REASON_VI: Record<string, string> = {
  level_off: "quyền đang tắt", scope: "API key thiếu scope",
};
const TIER_VI: Record<string, string> = {lead: "Trưởng nhóm", executor: "Thực thi"};
const GROUP_VI: Record<string, string> = {
  context: "Ngữ cảnh", work: "Công việc", knowledge: "Tri thức", collab: "Phối hợp",
  control: "Kiểm soát", report: "Báo cáo",
};

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
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("vi-VN",
    {day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"});
}

function payloadOf(ev: Row): Row {
  if (ev.payload && typeof ev.payload === "object") return ev.payload;
  try { return JSON.parse(ev.payload_json || "{}"); } catch { return {}; }
}

function Pill({level}: {level: string}) {
  const l = LEVEL_VI[level] || {text: level, cls: "mid"};
  return <span className={`prio ${l.cls}`}>{l.text}</span>;
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
    } catch (e) { setError(errorText(e, "Không tải được bảng quyền")); }
    try { setLog(await apiMcp.toolLog(40)); }
    catch (e) { setError(errorText(e, "Không tải được nhật ký gọi tool")); }
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
    catch (e) { setError(errorText(e, "Không lưu được quyền")); }
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
      headers: {"X-API-Key": "<API key gắn với ghế agent>"},
      toolFilter: ["company_*"],
    }}},
  }, null, 2);

  return <AuthGate><V9AppShell title="Công cụ của agent"
      subtitle={`Máy chủ MCP ${catalog?.server?.name || "clawcompany"} · ${catalog?.count ?? "…"} tool company_* · quyền theo bậc ghế`}>
    {error && <div className="v8Error" data-testid="tools-error">{error}</div>}

    <div className="v9Grid2">
      <section className="v8Card">
        <div className="v8CardHead"><div><b>Tóm tắt quyền</b>
          <span>Agent không có dòng quyền nào thì bị từ chối (mặc định deny)</span></div></div>
        <div data-testid="tool-counts" style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12}}>
          {tiers.map(tier => <div key={tier} style={{border: "1px solid var(--line)", borderRadius: 10, padding: "10px 12px"}}>
            <div style={{fontSize: 12.5, color: "var(--muted)", marginBottom: 6}}>{TIER_VI[tier] || tier}</div>
            <div style={{display: "flex", gap: 6, flexWrap: "wrap"}}>
              <span className="prio low">{counts[tier]?.allowed ?? 0} được dùng</span>
              <span className="prio mid">{counts[tier]?.ask ?? 0} hỏi duyệt</span>
              <span className="prio high">{counts[tier]?.off ?? 0} tắt</span>
            </div></div>)}
        </div>
        <p style={{fontSize: 13, color: "var(--muted)", margin: "12px 0 0"}}>
          Thứ tự áp dụng: ngoại lệ theo thành viên → bậc ghế → mặc định. "Hỏi duyệt" tạo
          một phê duyệt <code>tool:&lt;tên&gt;</code> trong Hộp việc; duyệt xong ghế đó được dùng 24 giờ.
          {perm?.member_overrides?.length ? ` Đang có ${perm.member_overrides.length} ngoại lệ theo thành viên.` : ""}
        </p>
      </section>
      <section className="v8Card">
        <div className="v8CardHead"><div><b>Gắn vào OpenClaw</b>
          <span>Mỗi ghế agent dùng một API key riêng; lượt chạy nhận qua header X-OpenClaw-Session-Key</span></div></div>
        <pre data-testid="mcp-snippet" style={{fontSize: 12, background: "var(--paper-2, #efeee9)",
          padding: 12, borderRadius: 8, overflowX: "auto", margin: 0}}>{snippet}</pre>
      </section>
    </div>

    <section className="v8Card" data-testid="tool-matrix">
      <div className="v8CardHead"><div><b>Ma trận quyền</b>
        <span>{isAdmin ? "Chọn mức cho từng tool theo bậc ghế" : "Chỉ admin được đổi quyền"}</span></div>
        <input placeholder="Lọc tool…" value={filter} onChange={e => setFilter(e.target.value)}
               style={{maxWidth: 220}}/></div>
      <div style={{overflowX: "auto"}}>
        <table style={{width: "100%", borderCollapse: "collapse", fontSize: 13}}>
          <thead><tr style={{textAlign: "left", color: "var(--muted)"}}>
            <th style={{padding: "6px 8px"}}>Tool</th><th style={{padding: "6px 8px"}}>Nhóm</th>
            <th style={{padding: "6px 8px"}}>Scope</th>
            {tiers.map(t => <th key={t} style={{padding: "6px 8px"}}>{TIER_VI[t] || t}</th>)}
          </tr></thead>
          <tbody>{tools.map(t => <tr key={t.name} style={{borderTop: "1px solid var(--line)"}}>
            <td style={{padding: "8px"}}><code>{t.name}</code>{t.writes && <span className="prio mid"
              style={{marginLeft: 6}}>ghi</span>}
              <div style={{color: "var(--muted)", fontSize: 12}}>{t.description}</div></td>
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
                {cell.source === "override" && <small style={{marginLeft: 6, color: "var(--muted)"}}>đã chỉnh</small>}
              </td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>
    </section>

    <section className="v8Card" data-testid="tool-log">
      <div className="v8CardHead"><div><b>Nhật ký gọi tool</b>
        <span>40 lượt gần nhất từ event bus · gồm cả lượt bị từ chối</span></div>
        <button onClick={load}>Tải lại</button></div>
      {log.length === 0
        ? <div className="v9Empty">Chưa có agent nào gọi tool. Gắn máy chủ MCP vào OpenClaw rồi giao việc cho agent.</div>
        : <div className="v9List">{log.map(ev => {
            const p = payloadOf(ev);
            const denied = ev.event_type === "mcp.tool.denied";
            const ok = !denied && p.ok;
            const pending = denied && p.reason === "ask_pending";
            const label = pending ? `chờ duyệt${p.approval_id ? ` · #${p.approval_id}` : ""}`
              : denied ? `từ chối · ${REASON_VI[p.reason] || p.reason || ""}`
              : ok ? `ok · ${p.ms ?? 0} ms` : `lỗi · ${p.error || ""}`;
            return <div className="v9LedgerRow" key={ev.id}>
              <span><code>{p.tool || "?"}</code></span>
              <b className={`prio ${ok ? "low" : pending ? "mid" : "high"}`}>{label}</b>
              <small>{memberName[ev.actor_member_id] || `ghế #${ev.actor_member_id ?? "?"}`}
                {p.run_id ? ` · lượt chạy #${p.run_id}` : ""} · {when(ev.occurred_at)}</small>
            </div>;
          })}</div>}
    </section>
  </V9AppShell></AuthGate>;
}
