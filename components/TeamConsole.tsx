"use client";
// M2 — Đội ngũ: sơ đồ tổ chức theo quản lý, người & quyền (mời / đổi vai / thu
// hồi), phòng ban (trưởng phòng, người quản lý), tạo công ty từ mẫu & nhập CSV.
// Mọi nút đều theo /api/team/me.capabilities — người không đủ quyền thấy giải
// thích thay vì nút bấm rồi mới bị 403.
import {useEffect, useMemo, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {PageFrame} from "./shell/PageFrame";
import {apiTeam, errorText} from "../lib/api";
import {AgentHRTab} from "./AgentHR";
import {Notice, EmptyState, ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {Icon} from "./Icon";
import Link from "next/link";
import {useCompanyId} from "../lib/prefs";

type Tab = "chart" | "people" | "departments" | "ai" | "training" | "build";
const TAB_IDS: Tab[] = ["chart", "people", "departments", "ai", "training", "build"];
const ROLE_VI: Record<string, string> = {guest: "Khách", member: "Thành viên", manager: "Quản lý", admin: "Quản trị", owner: "Chủ sở hữu"};
const CSV_SAMPLE = `tên,loại,chức danh,phòng ban,quản lý,email,trưởng phòng
Hà,người,Giám đốc,Ban điều hành,,ha@congty.vn,x
Minh,người,Trưởng kho,Kho,Hà,minh@congty.vn,x
Bot đóng gói,agent,Đóng gói đơn,Kho,Minh,,`;

function Node({n}: {n: any}) {
  const pending = n.status === "pending_runtime" || n.lifecycle === "runtime_missing";
  const agent = n.type === "agent";
  const inner = <>
    <span className={"ui-ava is-lg " + (agent ? "is-agent" : "is-human")} aria-hidden="true">{agent ? <Icon name="sparkle" size={16} strokeWidth={2}/> : (n.name || "?").slice(0, 1).toUpperCase()}</span>
    <span><b>{n.name}</b><small>{n.role || "—"}</small>{n.department && <span className="org-dept">{n.department}{n.access_role ? ` · ${ROLE_VI[n.access_role] || n.access_role}` : ""}</span>}</span>
    {(pending || n.cycle) ? <span className="org-flag is-warn">{pending ? "chưa có trên gateway" : "vòng quản lý"}</span>
      : n.is_head ? <span className="org-flag">Trưởng phòng</span> : null}
  </>;
  const cls = "org-node" + (n.is_head ? " is-head" : "") + (agent ? " is-agent" : "");
  return <li>
    {agent ? <Link href={`/app/agents/${n.id}`} className={cls} data-testid={`node-${n.id}`}>{inner}</Link>
      : <div className={cls} data-testid={`node-${n.id}`}>{inner}</div>}
    {n.children?.length > 0 && <ul>{n.children.map((c: any) => <Node key={c.id} n={c}/>)}</ul>}
  </li>;
}

function flatten(tree: any[]): any[] {
  const out: any[] = []; const walk = (ns: any[]) => ns.forEach(n => { out.push(n); walk(n.children || []); });
  walk(tree || []); return out;
}

export function TeamConsole() {
  const router = useRouter(); const params = useSearchParams();
  const raw = params.get("tab") as Tab;
  const tab: Tab = TAB_IDS.includes(raw) ? raw : "chart";
  const [pref, setPref] = useCompanyId();
  const [companyId, setCompanyId] = useState<number | null>(Number(params.get("company")) || pref || null);
  const [me, setMe] = useState<any>(null), [chart, setChart] = useState<any>(null), [people, setPeople] = useState<any>(null);
  const [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  const caps = me?.capabilities || {};

  async function load(cid = companyId) {
    /* ba nguồn song song (trước v2: people gọi sau khi me + sơ đồ về — một nhịp chờ thừa) */
    const [m, c, p] = await Promise.allSettled([apiTeam.me(), apiTeam.orgChart(cid), apiTeam.people()]);
    if (m.status === "fulfilled") setMe(m.value); else setError(m.reason);
    if (c.status === "fulfilled") { setChart(c.value); if (c.value?.company && cid == null) setCompanyId(c.value.company.id); } else setError(c.reason);
    setPeople(p.status === "fulfilled" ? p.value : null);
  }
  useEffect(() => { load(); }, []);
  /* bộ đổi công ty ở sidebar → đổi sơ đồ theo */
  useEffect(() => { if (pref && pref !== companyId) { setCompanyId(pref); load(pref); } // eslint-disable-next-line
  }, [pref]);
  async function act(fn: () => Promise<any>, ok: string | ((r: any) => string)) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(typeof ok === "string" ? ok : ok(r)); await load(); return r; }
    catch (e: any) { setError(e); } finally { setBusy(false); }
  }
  const pickCompany = (v: number) => { setCompanyId(v); setPref(v); load(v); };
  const setTab = (t: Tab) => router.replace(`/app/team?tab=${t}${companyId ? `&company=${companyId}` : ""}`);

  const members = useMemo(() => flatten(chart?.tree || []), [chart]);
  return <PageFrame actions={chart?.companies?.length > 1 ? <label className="tmInline">Công ty
      <select value={companyId ?? ""} onChange={e => pickCompany(Number(e.target.value))} data-testid="team-company">
        {chart.companies.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select></label> : undefined}>
    {me && tab !== "chart" && <Notice testId="team-role">
      Anh đang là <b>{me.role_label}</b> trong {me.organization || "tổ chức"}.{" "}
      {caps.manage_roles ? "Anh mời người, đổi vai, sửa sơ đồ và dựng công ty được."
        : caps.invite ? "Anh mời thành viên và sửa sơ đồ được; đổi vai cần Quản trị."
        : "Anh xem được sơ đồ và danh sách; mời người hay sửa sơ đồ cần vai Quản lý trở lên."}
    </Notice>}
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} onRetry={() => load()} testId="team-error"/> : null}

    {tab === "chart" && <ChartTab chart={chart} onBuild={() => setTab("build")}/>}
    {tab === "people" && <PeopleTab me={me} people={people} chart={chart} busy={busy} act={act}/>}
    {tab === "departments" && <DepartmentsTab chart={chart} members={members} caps={caps} busy={busy} act={act}/>}
    {tab === "ai" && <AgentHRTab companyId={companyId} caps={caps}/>}
    {tab === "training" && <TrainingTab/>}
    {tab === "build" && <BuildTab chart={chart} caps={caps} busy={busy} act={act} onCompany={(id: number) => { pickCompany(id); setTab("chart"); }}/>}
  </PageFrame>;
}

function TrainingTab() {
  return <div className="ui-grid is-2">
    <EmptyState mood="lam-viec" title="Đào tạo agent đang được xây (M5)">
      Skill Studio, bộ bài thử có chấm điểm, scorecard từng agent và bài học vào MEMORY.md thuộc module M5 — chưa có API nên chưa có màn hình thật ở đây.
    </EmptyState>
    <section className="ui-panel"><header className="ui-panel-head"><div className="ui-grow"><h2>Dùng được ngay</h2><p>Những phần đào tạo đã chạy</p></div></header>
      <div className="ui-list">
        <Link className="ui-row" href="/app/agent-tools"><Icon name="shield" size={16}/><span className="ui-row-main"><span className="ui-row-title">Kỹ năng & công cụ</span><span className="ui-row-meta">Công cụ agent được gọi, quyền theo ghế</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/team?tab=ai"><Icon name="sparkle" size={16}/><span className="ui-row-main"><span className="ui-row-title">Hồ sơ agent</span><span className="ui-row-meta">Sửa tính cách (SOUL), mô tả công việc, quyền, hạn mức</span></span><Icon name="chevron-right" size={14}/></Link>
        <Link className="ui-row" href="/app/memory"><Icon name="book" size={16}/><span className="ui-row-main"><span className="ui-row-title">Bộ nhớ tổ chức</span><span className="ui-row-meta">Quyết định và tri thức dùng chung</span></span><Icon name="chevron-right" size={14}/></Link>
      </div>
    </section>
  </div>;
}

function ChartTab({chart, onBuild}: {chart: any; onBuild: () => void}) {
  if (!chart) return <SkeletonRows n={4} h={64}/>;
  if (!chart.company) return <EmptyState mood="chao" title="Chưa có công ty nào" action={<button className="ui-btn is-primary" onClick={onBuild}>Dựng công ty từ mẫu</button>}>
    Dựng từ mẫu (shop, agency, kế toán) để có sẵn phòng ban, trưởng phòng là agent và sơ đồ báo cáo.</EmptyState>;
  const s = chart.stats || {};
  return <section className="ui-section" data-testid="org-chart">
    <div className="ui-toolbar">
      <div className="org-stats"><span><b>{s.departments}</b> phòng ban</span><span><b>{s.humans}</b> người</span><span><b>{s.agents}</b> agent</span>
        {s.without_head ? <span className="is-warn"><b>{s.without_head}</b> phòng chưa có trưởng phòng</span> : null}</div>
      <span className="ui-grow"/>
      <div className="org-legend"><span><span className="ui-ava is-agent" style={{width: 14, height: 14}}/>Agent — bấm để mở hồ sơ</span><span><span className="ui-ava is-human" style={{width: 14, height: 14}}/>Người</span></div>
    </div>
    <div className="org" data-testid="org-tree" ref={el => { /* sơ đồ rộng hơn màn hình (điện thoại): mở ra ở giữa, gốc công ty nằm trong tầm nhìn */ if (el && el.scrollWidth > el.clientWidth && !el.dataset.centered) { el.dataset.centered = "1"; el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2; } }}>
      {chart.tree.length ? <ul className="org-tree"><li>
        <div className="org-node is-root"><span className="ui-ava is-lg" aria-hidden="true"><Icon name="building" size={18}/></span>
          <span><b>{chart.company.name}</b><small>{s.departments} phòng · {(s.humans || 0) + (s.agents || 0)} thành viên</small></span></div>
        <ul>{chart.tree.map((n: any) => <Node key={n.id} n={n}/>)}</ul>
      </li></ul> : <EmptyState compact mood="ngu" title="Công ty chưa có thành viên">Mời người ở tab Người &amp; quyền hoặc nhập sơ đồ từ CSV.</EmptyState>}
    </div>
  </section>;
}

function PeopleTab({me, people, chart, busy, act}: any) {
  const caps = me?.capabilities || {};
  const [email, setEmail] = useState(""), [role, setRole] = useState("member"), [title, setTitle] = useState("");
  const [dept, setDept] = useState(""), [link, setLink] = useState("");
  if (!people) return <SkeletonRows n={4}/>;
  const roles: string[] = people.assignable_roles || [];
  async function invite() {
    const r = await act(() => apiTeam.invite({email, role, job_title: title, company_id: chart?.company?.id || null,
      department_id: dept ? Number(dept) : null}), (x: any) => `Đã tạo lời mời cho ${x.email} (${x.role_label}). Gửi link bên dưới — link chỉ hiện một lần, hết hạn sau 7 ngày.`);
    if (r?.invite_path) { setLink(window.location.origin + r.invite_path); setEmail(""); setTitle(""); }
  }
  return <div className="ui-grid is-2">
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>Người có quyền</b><span>Vai quyết định ai được mời, sửa sơ đồ, dựng công ty</span></div></div>
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
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>Mời người</b><span>{caps.invite ? "Tạo link mời; người nhận đặt mật khẩu và vào thẳng sơ đồ" : "Cần vai Quản lý trở lên để mời"}</span></div></div>
      {caps.invite && <div className="ui-form">
        <div className="ui-form-row">
          <label>Email<input value={email} onChange={e => setEmail(e.target.value)} placeholder="ten@congty.vn" data-testid="invite-email"/></label>
          <label>Vai<select value={role} onChange={e => setRole(e.target.value)} data-testid="invite-role">
            {roles.map((r: string) => <option key={r} value={r}>{ROLE_VI[r]}</option>)}</select></label>
        </div>
        <div className="ui-form-row">
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
      <div className="tm-list" data-testid="invite-list">
        {people.invitations.slice(0, 12).map((i: any) => <div key={i.id} className="tmInvite">
          <span><b>{i.email}</b> · {i.role_label}{i.job_title ? ` · ${i.job_title}` : ""}</span>
          <small className={`is-${i.status}`}>{({pending: "đang chờ", accepted: "đã nhận", revoked: "đã thu hồi", expired: "hết hạn"} as any)[i.status] || i.status}</small>
          {i.status === "pending" && caps.invite && <button className="ui-btn is-ghost is-sm" disabled={busy}
            onClick={() => act(() => apiTeam.revokeInvite(i.id), `Đã thu hồi lời mời ${i.email}`)}>Thu hồi</button>}
        </div>)}
        {!people.invitations.length && <div className="ui-empty-line">Chưa có lời mời nào.</div>}
      </div>
    </section>
  </div>;
}

function DepartmentsTab({chart, members, caps, busy, act}: any) {
  if (!chart?.company) return <EmptyState compact mood="chao" title="Chưa có công ty">Dựng công ty ở tab Dựng công ty.</EmptyState>;
  const can = !!caps.edit_org_chart;
  return <div className="tmDepts" data-testid="dept-list">
    {!can && <div className="ui-banner">Bạn đang xem. Chọn trưởng phòng hay đổi người quản lý cần vai Quản lý trở lên.</div>}
    {chart.departments.map((d: any) => {
      const inDept = members.filter((m: any) => m.department_id === d.id);
      return <section key={d.id} className="ui-panel tm-card" data-testid={`dept-${d.id}`}>
        <div className="tm-card-head"><div><b>{d.name}</b><span>{d.humans} người · {d.agents} agent</span></div></div>
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
  return <div className="ui-grid is-2">
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>Tạo công ty từ mẫu</b><span>{can ? "Mỗi phòng có trưởng phòng là agent; trưởng phòng báo cáo Giám đốc" : "Cần vai Quản trị để dựng công ty"}</span></div></div>
      <div className="tm-list">
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
    <section className="ui-panel tm-card">
      <div className="tm-card-head"><div><b>Nhập sơ đồ từ CSV</b><span>Vào {chart?.company?.name || "công ty đang chọn"} · cột: tên, loại, chức danh, phòng ban, quản lý, email, trưởng phòng</span></div></div>
      {can ? <div className="ui-form">
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
