"use client";
import {useEffect, useState} from "react";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill, toneOf} from "./ui/StatusPill";
import {LogoLockup} from "./Logo";
import {LanguageSwitcher} from "./LanguageSwitcher";
import {describeError} from "../lib/api";
import {fmtNum, fmtUsd, getLocale, t} from "../lib/i18n";
import {viStatus} from "../lib/labels";

/* Cổng khách hàng: khách đăng nhập bằng tài khoản portal riêng, xem đội AI, dự án được chia sẻ và mức dùng. */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";
type PortalData = {
  user: {display_name: string; email: string};
  customer: {name: string; plan: string; usage_percent: number};
  agents: {agent_id: number; name: string; role: string; status: string}[];
  projects: {id: number; name: string; status: string; progress: number; visibility: string}[];
  subscription?: {plan: string; mrr: number; status: string; renewal_date: string};
  usage: {events: number; quantity: number; cost: number; by_type: Record<string, number>};
};
const H = () => ({"Accept-Language": getLocale()});
async function fetchPortal(token: string) {
  const r = await fetch(`${API_BASE}/portal/me`, {headers: {...H(), Authorization: `Bearer ${token}`}, cache: "no-store"});
  if (!r.ok) throw describeError(r.status, await r.text());
  return r.json();
}

export function CustomerPortal() {
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState("client@acme.local");
  const [password, setPassword] = useState("ChangeMe123!");
  const [data, setData] = useState<PortalData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const tk = localStorage.getItem("clawcompany_portal_token");
    if (tk) { setToken(tk); fetchPortal(tk).then(setData).catch(() => { localStorage.removeItem("clawcompany_portal_token"); setToken(null); }); }
  }, []);
  async function login(e: React.FormEvent) {
    e.preventDefault(); setError(null); setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/portal/auth/login`, {method: "POST", headers: {...H(), "Content-Type": "application/json"}, body: JSON.stringify({email, password})});
      if (!r.ok) throw describeError(r.status, await r.text());
      const j = await r.json(); localStorage.setItem("clawcompany_portal_token", j.access_token); setToken(j.access_token); setData(await fetchPortal(j.access_token));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  if (!token || !data) return <div className="auth">
    <form className="auth-card" onSubmit={login} noValidate>
      <LogoLockup hole="var(--surface)"/>
      <div><h1>{t("portal.login_title")}</h1><p>{t("portal.login_desc")}</p></div>
      <Field label="Email"><input type="email" value={email} autoComplete="username" onChange={e => setEmail(e.target.value)}/></Field>
      <Field label={t("portal.password")}><input type="password" value={password} autoComplete="current-password" onChange={e => setPassword(e.target.value)}/></Field>
      {error ? <ErrorBanner error={error} context={t("portal.login_fail")}/> : null}
      <Button type="submit" variant="primary" size="lg" block busy={busy}>{busy ? t("portal.signing_in") : t("portal.sign_in")}</Button>
      <div style={{display: "flex", justifyContent: "center"}}><LanguageSwitcher compact saveProfile={false}/></div>
    </form>
  </div>;
  const sub = data.subscription;
  return <div className="pt-shell">
    <aside className="pt-side">
      <LogoLockup hole="var(--bg)"/>
      <small>{t("portal.brand")}</small>
      <nav className="ui-list">
        <a className="ui-row is-active" href="/portal">{t("portal.overview")}</a>
        <a className="ui-row" href="/portal/chat">{t("portal.conversations")}</a>
      </nav>
      <div className="ui-panel ui-panel-body"><small>{t("portal.workspace")}</small><br/><b>{data.customer.name}</b><br/><small>{data.customer.plan}</small></div>
    </aside>
    <main className="pt-main">
      <div className="ui-pagehead">
        <div><h1>{t("portal.hello", {p0: data.user.display_name || data.customer.name})}</h1></div>
        <div className="ui-pagehead-actions"><LanguageSwitcher compact saveProfile={false}/>
          <Button onClick={() => { localStorage.removeItem("clawcompany_portal_token"); location.reload(); }}>{t("portal.sign_out")}</Button></div>
      </div>
      <Panel title={t("portal.team_working")} desc={t("portal.team_working_desc")}>
        <div className="lab-stats">
          <div className="lab-stat"><span>{t("portal.usage_month")}</span><b>{data.customer.usage_percent}%</b>
            <span className="ui-meter" style={{display: "block"}}><i style={{width: `${Math.min(100, data.customer.usage_percent)}%`}}/></span></div>
          <div className="lab-stat"><span>{t("portal.ai_cost", {p0: ""})}</span><b>{fmtUsd(data.usage.cost)}</b></div>
          <div className="lab-stat"><span>{t("portal.usage_events")}</span><b>{fmtNum(data.usage.events)}</b></div>
        </div>
      </Panel>
      <div className="ui-grid is-2">
        <Panel title={t("portal.your_team")} desc={t("portal.employees", {p0: data.agents.length})} flush>
          {data.agents.length ? <div className="ui-list">{data.agents.map(a => <div className="ui-row" key={a.agent_id}>
            <span className="ui-ava">{a.name[0]}</span>
            <span className="ui-row-main"><span className="ui-row-title">{a.name}</span><span className="ui-row-meta">{a.role}</span></span>
            <span className="ui-row-end"><StatusPill tone={toneOf(a.status)}>{viStatus(a.status)}</StatusPill>
              <Button size="sm" onClick={() => { location.href = `/portal/chat?agent=${a.agent_id}`; }}>{t("portal.chat")}</Button></span>
          </div>)}</div> : <p className="ui-empty-line" style={{padding: 16}}>{t("portal.no_agents")}</p>}
        </Panel>
        <Panel title={t("portal.plan")} desc={sub?.plan}>
          <dl className="ui-kv">
            <dt>{t("portal.monthly")}</dt><dd>{fmtUsd(sub?.mrr || 0, 0)}</dd>
            <dt>{t("portal.usage_events")}</dt><dd>{fmtNum(data.usage.events)}</dd>
            <dt>{t("portal.renewal")}</dt><dd>{sub?.renewal_date || "—"}</dd>
            <dt>{t("portal.status")}</dt><dd><StatusPill tone={toneOf(sub?.status || "active")}>{viStatus(sub?.status || "active")}</StatusPill></dd>
          </dl>
        </Panel>
      </div>
      <Panel title={t("portal.projects")} desc={t("portal.projects_desc")}>
        {data.projects.length === 0 ? <p className="ui-empty-line">{t("portal.no_projects")}</p> :
          <div className="ui-table-wrap"><table className="ui-table"><tbody>{data.projects.map(p => <tr key={p.id}>
            <td><b>{p.name}</b><br/><small>{viStatus(p.status)}</small></td>
            <td style={{width: "40%"}}><span className="ui-meter" style={{display: "block"}}><i style={{width: `${p.progress}%`}}/></span></td>
            <td className="is-num">{p.progress}%</td></tr>)}</tbody></table></div>}
      </Panel>
    </main>
  </div>;
}
