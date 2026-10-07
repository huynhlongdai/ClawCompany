"use client";
// M2 — Đội ngũ: sơ đồ tổ chức theo quản lý, người & quyền (mời / đổi vai / thu
// hồi), phòng ban (trưởng phòng, người quản lý), tạo công ty từ mẫu & nhập CSV.
// Mọi nút đều theo /api/team/me.capabilities — người không đủ quyền thấy giải
// thích thay vì nút bấm rồi mới bị 403.
import {useEffect, useMemo, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {AuthGate} from "./AuthGate";
import {V17AppShell} from "./V17AppShell";
import {apiTeam, errorText} from "../lib/api";
import {AgentHRTab} from "./AgentHR";

type Tab = "chart" | "people" | "departments" | "ai" | "build";
const TABS: [Tab, string][] = [["chart", "Sơ đồ"], ["people", "Người & quyền"], ["departments", "Phòng ban"], ["ai", "Nhân sự AI"], ["build", "Tạo công ty & CSV"]];
const ROLE_VI: Record<string, string> = {guest: "Khách", member: "Thành viên", manager: "Quản lý", admin: "Quản trị", owner: "Chủ sở hữu"};
const CSV_SAMPLE = `tên,loại,chức danh,phòng ban,quản lý,email,trưởng phòng
Hà,người,Giám đốc,Ban điều hành,,ha@congty.vn,x
Minh,người,Trưởng kho,Kho,Hà,minh@congty.vn,x
Bot đóng gói,agent,Đóng gói đơn,Kho,Minh,,`;

function Node({n}: {n: any}) {
  const pending = n.status === "pending_runtime" || n.lifecycle === "runtime_missing";
  return <li>
    <div className={"tmNode" + (n.is_head ? " is-head" : "") + (n.type === "agent" ? " is-agent" : "")} data-testid={`node-${n.id}`}>
      <b>{n.name}</b>
      <small>{n.role || "—"}</small>
      <span className="tmTags">
        <em>{n.type === "agent" ? "AI" : "Người"}</em>
        {n.department && <em>{n.department}</em>}
        {n.is_head && <em className="is-head">Trưởng phòng</em>}
        {n.access_role && <em>{ROLE_VI[n.access_role] || n.access_role}</em>}
        {pending && <em className="is-warn">chưa có trên gateway</em>}
        {n.cycle && <em className="is-warn">vòng quản lý</em>}
      </span>
    </div>
    {n.children?.length > 0 && <ul>{n.children.map((c: any) => <Node key={c.id} n={c}/>)}</ul>}
  </li>;
}

function flatten(tree: any[]): any[] {
  const out: any[] = []; const walk = (ns: any[]) => ns.forEach(n => { out.push(n); walk(n.children || []); });
  walk(tree || []); return out;
}

export function TeamConsole() {
  const router = useRouter(); const params = useSearchParams();
  const tab = (params.get("tab") as Tab) || "chart";
  const [companyId, setCompanyId] = useState<number | null>(Number(params.get("company")) || null);
  const setTab = (t: Tab) => router.replace(`/app/team?tab=${t}${companyId ? `&company=${companyId}` : ""}`);
  const [me, setMe] = useState<any>(null), [chart, setChart] = useState<any>(null), [people, setPeople] = useState<any>(null);
  const [error, setError] = useState(""), [note, setNote] = useState(""), [busy, setBusy] = useState(false);
  const caps = me?.capabilities || {};

  async function load(cid = companyId) {
    try {
      const [m, c] = await Promise.all([apiTeam.me(), apiTeam.orgChart(cid)]);
      setMe(m); setChart(c); if (c?.company && cid == null) setCompanyId(c.company.id);
      apiTeam.people().then(setPeople).catch(() => setPeople(null));
    } catch (e: any) { setError(errorText(e)); }
  }
  useEffect(() => { load(); }, []);
  async function act(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(""); setNote("");
    try { const r = await fn(); setNote(typeof ok === "string" ? ok : ok(r)); await load(); return r; }
    catch (e: any) { setError(errorText(e)); } finally { setBusy(false); }
  }

  const members = useMemo(() => flatten(chart?.tree || []), [chart]);
  return <AuthGate><V17AppShell title="Đội ngũ" subtitle="Sơ đồ tổ chức, mời người, phân quyền và trưởng phòng">
    {me && <div className="ui-banner tmRole" data-testid="team-role">
      Bạn đang là <b>{me.role_label}</b> trong {me.organization || "tổ chức"}.{" "}
      {caps.manage_roles ? "Bạn mời người, đổi vai, sửa sơ đồ và dựng công ty được."
        : caps.invite ? "Bạn mời thành viên và sửa sơ đồ được; đổi vai cần Quản trị."
        : "Bạn xem được sơ đồ và danh sách; mời người hay sửa sơ đồ cần vai Quản lý trở lên."}
    </div>}
    {error && <div className="ui-banner is-error" data-testid="team-error">{error}</div>}
    {note && <div className="ui-banner tmNote" data-testid="team-note">{note}</div>}
    <div className="ui-toolbar" style={{margin: "12px 0"}}>
      <div className="ui-seg" role="tablist" aria-label="Đội ngũ">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-pressed={tab === k} onClick={() => setTab(k)} data-testid={`tab-${k}`}>{l}</button>)}
      </div>
      {chart?.companies?.length > 0 && <label className="tmInline">Công ty
        <select value={companyId ?? ""} onChange={e => { const v = Number(e.target.value); setCompanyId(v); load(v); }} data-testid="team-company">
          {chart.companies.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></label>}
    </div>

    {tab === "chart" && <ChartTab chart={chart}/>}
    {tab === "people" && <PeopleTab me={me} people={people} chart={chart} busy={busy} act={act}/>}
    {tab === "departments" && <DepartmentsTab chart={chart} members={members} caps={caps} busy={busy} act={act}/>}
    {tab === "ai" && <AgentHRTab companyId={companyId} caps={caps}/>}
    {tab === "build" && <BuildTab chart={chart} caps={caps} busy={busy} act={act} onCompany={(id: number) => { setCompanyId(id); load(id); setTab("chart"); }}/>}
  </V17AppShell></AuthGate>;
}

function ChartTab({chart}: {chart: any}) {
  if (!chart) return <div className="ui-empty">Đang tải…</div>;
  if (!chart.company) return <div className="ui-empty">Chưa có công ty nào — vào “Tạo công ty & CSV” để dựng từ mẫu.</div>;
  const s = chart.stats || {};
  return <section className="v8Card">
    <div className="v8CardHead"><div><b>{chart.company.name}</b>
      <span>{s.departments} phòng ban · {s.humans} người · {s.agents} agent{s.without_head ? ` · ${s.without_head} phòng chưa có trưởng phòng` : ""}</span></div></div>
    <div className="tmTree" data-testid="org-tree"><ul>{chart.tree.map((n: any) => <Node key={n.id} n={n}/>)}</ul></div>
    {!chart.tree.length && <div className="ui-empty">Công ty chưa có thành viên.</div>}
  </section>;
}

function PeopleTab({me, people, chart, busy, act}: any) {
  const caps = me?.capabilities || {};
  const [email, setEmail] = useState(""), [role, setRole] = useState("member"), [title, setTitle] = useState("");
  const [dept, setDept] = useState(""), [link, setLink] = useState("");
  if (!people) return <div className="ui-empty">Đang tải…</div>;
  const roles: string[] = people.assignable_roles || [];
  async function invite() {
    const r = await act(() => apiTeam.invite({email, role, job_title: title, company_id: chart?.company?.id || null,
      department_id: dept ? Number(dept) : null}), (x: any) => `Đã tạo lời mời cho ${x.email} (${x.role_label}). Gửi link bên dưới — link chỉ hiện một lần, hết hạn sau 7 ngày.`);
    if (r?.invite_path) { setLink(window.location.origin + r.invite_path); setEmail(""); setTitle(""); }
  }
  return <div className="v9Grid2">
    <section className="v8Card">
      <div className="v8CardHead"><div><b>Người có quyền</b><span>Vai quyết định ai được mời, sửa sơ đồ, dựng công ty</span></div></div>
      <table className="tmTable" data-testid="people-table"><tbody>
        {people.users.map((u: any) => <tr key={u.user_id} className={u.status !== "active" ? "is-off" : ""}>
          <td><b>{u.display_name || u.email}</b>{u.is_self && " (bạn)"}<br/><small>{u.email}{u.member_name ? ` · ghế ${u.member_name}` : ""}</small></td>
          <td>{u.status !== "active" ? <small>đã thu hồi</small> : u.editable
            ? <select value={u.role} disabled={busy} data-testid={`role-${u.user_id}`}
                onChange={e => act(() => apiTeam.setRole(u.user_id, e.target.value), `Đã đổi vai ${u.email} → ${ROLE_VI[e.target.value]}`)}>
                {Array.from(new Set([...roles, u.role])).map((r: string) => <option key={r} value={r}>{ROLE_VI[r] || r}</option>)}
              </select>
            : <small>{u.role_label}</small>}</td>
          <td style={{textAlign: "right"}}>{u.editable && <button className="ui-btn is-ghost is-sm" disabled={busy}
            onClick={() => confirm(`Thu hồi quyền của ${u.email}? Phiên đăng nhập của họ sẽ bị chặn ngay.`) && act(() => apiTeam.revokeAccess(u.user_id), `Đã thu hồi quyền ${u.email}`)}>Thu hồi</button>}</td>
        </tr>)}
      </tbody></table>
    </section>
    <section className="v8Card">
      <div className="v8CardHead"><div><b>Mời người</b><span>{caps.invite ? "Tạo link mời; người nhận đặt mật khẩu và vào thẳng sơ đồ" : "Cần vai Quản lý trở lên để mời"}</span></div></div>
      {caps.invite && <div className="v9Form">
        <div className="v9FormRow">
          <label>Email<input value={email} onChange={e => setEmail(e.target.value)} placeholder="ten@congty.vn" data-testid="invite-email"/></label>
          <label>Vai<select value={role} onChange={e => setRole(e.target.value)} data-testid="invite-role">
            {roles.map((r: string) => <option key={r} value={r}>{ROLE_VI[r]}</option>)}</select></label>
        </div>
        <div className="v9FormRow">
          <label>Chức danh<input value={title} onChange={e => setTitle(e.target.value)} placeholder="VD: Nhân viên bán hàng"/></label>
          <label>Phòng ban<select value={dept} onChange={e => setDept(e.target.value)} data-testid="invite-dept">
            <option value="">— chưa xếp —</option>
            {(chart?.departments || []).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        </div>
        <button className="ui-btn is-primary" disabled={busy || !email} onClick={invite} data-testid="invite-submit">Tạo lời mời</button>
        {link && <div className="tmLink" data-testid="invite-link"><code>{link}</code>
          <button className="ui-btn is-ghost is-sm" onClick={() => navigator.clipboard?.writeText(link)}>Sao chép</button></div>}
      </div>}
      <b style={{display: "block", marginTop: 14, fontSize: 13}}>Lời mời gần đây</b>
      <div className="v9List" data-testid="invite-list">
        {people.invitations.slice(0, 12).map((i: any) => <div key={i.id} className="tmInvite">
          <span><b>{i.email}</b> · {i.role_label}{i.job_title ? ` · ${i.job_title}` : ""}</span>
          <small className={`is-${i.status}`}>{({pending: "đang chờ", accepted: "đã nhận", revoked: "đã thu hồi", expired: "hết hạn"} as any)[i.status] || i.status}</small>
          {i.status === "pending" && caps.invite && <button className="ui-btn is-ghost is-sm" disabled={busy}
            onClick={() => act(() => apiTeam.revokeInvite(i.id), `Đã thu hồi lời mời ${i.email}`)}>Thu hồi</button>}
        </div>)}
        {!people.invitations.length && <div className="v9Empty">Chưa có lời mời nào.</div>}
      </div>
    </section>
  </div>;
}

function DepartmentsTab({chart, members, caps, busy, act}: any) {
  if (!chart?.company) return <div className="ui-empty">Chưa có công ty.</div>;
  const can = !!caps.edit_org_chart;
  return <div className="tmDepts" data-testid="dept-list">
    {!can && <div className="ui-banner">Bạn đang xem. Chọn trưởng phòng hay đổi người quản lý cần vai Quản lý trở lên.</div>}
    {chart.departments.map((d: any) => {
      const inDept = members.filter((m: any) => m.department_id === d.id);
      return <section key={d.id} className="v8Card" data-testid={`dept-${d.id}`}>
        <div className="v8CardHead"><div><b>{d.name}</b><span>{d.humans} người · {d.agents} agent</span></div></div>
        <label className="tmInline">Trưởng phòng
          <select value={d.head_member_id ?? ""} disabled={!can || busy} data-testid={`head-${d.id}`}
            onChange={e => act(() => apiTeam.setHead(d.id, e.target.value ? Number(e.target.value) : null),
              (r: any) => `Đã đặt trưởng phòng ${d.name}${r.reassigned ? ` · ${r.reassigned} người chuyển sang báo cáo trưởng phòng mới` : ""}`)}>
            <option value="">— chưa có —</option>
            {members.map((m: any) => <option key={m.id} value={m.id}>{m.name}{m.department_id !== d.id ? ` (${m.department || "chưa xếp"})` : ""}</option>)}
          </select></label>
        {d.guide && <small className="tmGuide">{d.guide}</small>}
        <table className="tmTable"><tbody>
          {inDept.map((m: any) => <tr key={m.id}>
            <td><b>{m.name}</b>{m.is_head && " · trưởng phòng"}<br/><small>{m.role || "—"} · {m.type === "agent" ? "AI" : "người"}</small></td>
            <td style={{textAlign: "right"}}><label className="tmInline">Báo cáo cho
              <select value={m.manager_id ?? ""} disabled={!can || busy} data-testid={`mgr-${m.id}`}
                onChange={e => act(() => apiTeam.setManager(m.id, e.target.value ? Number(e.target.value) : null), `Đã đổi người quản lý của ${m.name}`)}>
                <option value="">— không ai —</option>
                {members.filter((x: any) => x.id !== m.id).map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}
              </select></label></td>
          </tr>)}
          {!inDept.length && <tr><td><small>Phòng chưa có ai.</small></td></tr>}
        </tbody></table>
      </section>;
    })}
  </div>;
}

function BuildTab({chart, caps, busy, act, onCompany}: any) {
  const [templates, setTemplates] = useState<any[]>([]), [name, setName] = useState<Record<string, string>>({});
  const [result, setResult] = useState<any>(null), [csv, setCsv] = useState(CSV_SAMPLE), [report, setReport] = useState<any>(null);
  useEffect(() => { apiTeam.templates().then(setTemplates).catch(() => {}); }, []);
  const can = !!caps.create_company;
  async function build(key: string) {
    const r = await act(() => apiTeam.fromTemplate(key, name[key] || ""), (x: any) =>
      `Đã dựng “${x.company_name}”: ${x.departments} phòng ban, ${x.agents_bound}/${x.agents} agent đã có trên gateway.`);
    if (r) setResult(r);
  }
  async function runCsv(dry: boolean) {
    const r = await act(() => apiTeam.importCsv(chart.company.id, csv, dry), (x: any) => x.dry_run
      ? (x.ok ? `Kiểm tra xong: ${x.summary.create} tạo mới, ${x.summary.update} cập nhật — chưa ghi gì.` : `Có ${x.summary.errors} dòng lỗi — sửa rồi kiểm tra lại.`)
      : x.applied ? `Đã nhập vào ${chart.company.name}.` : "Chưa nhập vì còn lỗi.");
    if (r) setReport(r);
  }
  return <div className="v9Grid2">
    <section className="v8Card">
      <div className="v8CardHead"><div><b>Tạo công ty từ mẫu</b><span>{can ? "Mỗi phòng có trưởng phòng là agent; trưởng phòng báo cáo Giám đốc" : "Cần vai Quản trị để dựng công ty"}</span></div></div>
      <div className="v9List">
        {templates.map(t => <div key={t.key} className="tmTpl" data-testid={`tpl-${t.key}`}>
          <b>{t.name}</b><small>{t.description}</small>
          <small>{t.departments.map((d: any) => `${d.name} (${[d.head, ...d.staff].join(", ")})`).join(" · ")}</small>
          {can && <div className="tmRow">
            <input value={name[t.key] || ""} onChange={e => setName({...name, [t.key]: e.target.value})} placeholder={`Tên công ty (mặc định: ${t.name})`}/>
            <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => build(t.key)} data-testid={`tpl-build-${t.key}`}>
              {busy ? "Đang dựng…" : `Dựng · ${t.agents} agent`}</button>
          </div>}
        </div>)}
      </div>
      {result && <div className="tmResult" data-testid="tpl-result">
        <b>{result.company_name}</b> · việc #{result.job_id} · {result.job_status === "ready" ? "xong" : "một phần"}
        {result.runtime_issues?.map((i: any) => <small key={i.runtime_agent_id} className="is-warn">⚠ {i.runtime_agent_id}: {i.hint || i.lifecycle}</small>)}
        <button className="ui-btn is-ghost is-sm" onClick={() => onCompany(result.company_id)}>Xem sơ đồ</button>
      </div>}
    </section>
    <section className="v8Card">
      <div className="v8CardHead"><div><b>Nhập sơ đồ từ CSV</b><span>Vào {chart?.company?.name || "công ty đang chọn"} · cột: tên, loại, chức danh, phòng ban, quản lý, email, trưởng phòng</span></div></div>
      {can ? <div className="v9Form">
        <textarea rows={8} value={csv} onChange={e => { setCsv(e.target.value); setReport(null); }} data-testid="csv-text" style={{width: "100%", fontFamily: "var(--font-mono)", fontSize: 12}}/>
        <div className="tmRow">
          <label className="ui-btn is-ghost is-sm">Chọn file .csv<input type="file" accept=".csv,text/csv" hidden
            onChange={async e => { const f = e.target.files?.[0]; if (f) { setCsv(await f.text()); setReport(null); } }}/></label>
          <button className="ui-btn is-ghost" disabled={busy || !chart?.company} onClick={() => runCsv(true)} data-testid="csv-check">Kiểm tra</button>
          <button className="ui-btn is-primary" disabled={busy || !report?.ok || !report?.dry_run} onClick={() => runCsv(false)} data-testid="csv-apply">Nhập</button>
        </div>
        <small>Người có email sẽ nhận link mời gắn đúng ghế; agent được tạo trên gateway OpenClaw.</small>
      </div> : <div className="ui-empty">Cần vai Quản trị để nhập CSV.</div>}
      {report && <div className="tmReport" data-testid="csv-report">
        <small>{report.summary.rows} dòng · {report.summary.create} tạo mới · {report.summary.update} cập nhật · {report.summary.agents} agent · {report.summary.invitations} lời mời
          {report.summary.departments_new?.length ? ` · phòng mới: ${report.summary.departments_new.join(", ")}` : ""}</small>
        <table className="tmTable"><tbody>
          {report.rows.map((r: any) => <tr key={r.line} className={r.errors.length ? "is-err" : ""}>
            <td><small>dòng {r.line}</small></td><td><b>{r.name || "—"}</b> <small>{r.type === "agent" ? "AI" : "người"} · {r.department || "chưa xếp"}{r.manager ? ` → ${r.manager}` : ""}{r.is_head ? " · trưởng phòng" : ""}</small></td>
            <td><small>{r.errors.length ? r.errors.join("; ") : r.action === "create" ? "tạo mới" : "cập nhật"}{r.warnings.length ? ` (${r.warnings.join("; ")})` : ""}</small></td>
          </tr>)}
        </tbody></table>
        {report.invitations?.length > 0 && <div className="tmLink"><b>Link mời (chỉ hiện một lần):</b>
          {report.invitations.map((i: any) => <code key={i.id}>{i.name}: {typeof window !== "undefined" ? window.location.origin : ""}/invite/{i.token}</code>)}</div>}
      </div>}
    </section>
  </div>;
}
