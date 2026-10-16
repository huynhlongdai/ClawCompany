"use client";
// R1 — vai trò theo công ty (chủ / quản lý / người duyệt / người xem) + một người nhiều ghế.
// R2 — cho thuê agent (seat_leases): bên cho thuê "Cho thuê", bên thuê "Agent đi thuê".
import {useState} from "react";
import {apiRental} from "../lib/api";
import {ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {t as tr, type Key} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

export const usd = (v: number | null | undefined) => v == null ? "—" : `$${(Math.round(v * 10000) / 10000).toLocaleString("en-US")}`;

export function CompanyRolesTab({companyId, members}: {companyId: number | null; members: any[]}) {
  const {data, error, reload} = useLoad(() => companyId ? apiRental.companyAccess(companyId) : Promise.resolve(null), [companyId]);
  const [email, setEmail] = useState(""), [role, setRole] = useState("viewer"), [seat, setSeat] = useState<string>("");
  const [err, setErr] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const toast = useToast();
  if (!companyId) return <p><small>{tr("rental.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="roles-error"/>;
  if (!data) return <SkeletonRows n={3} h={40}/>;
  const d: any = data;
  const humans = (members || []).filter((m: any) => m.type !== "agent");
  async function save() {
    setBusy(true); setErr(null);
    try {
      const r = await apiRental.setCompanyAccess({company_id: companyId, role, email});
      if (seat) await apiRental.linkSeat({user_id: r.user_id, member_id: Number(seat)});
      toast(tr("rental.role_saved")); setEmail(""); setSeat(""); reload();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function remove(id: number) {
    setBusy(true); setErr(null);
    try { await apiRental.removeCompanyAccess(id); toast(tr("rental.role_removed")); reload(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return <section className="ui-section" data-testid="company-roles">
    <p className="tmGuide">{tr("rental.roles_explain")}</p>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} testId="roles-save-error"/> : null}
    <div className="ui-panel"><table className="ui-table" data-testid="company-roles-table"><thead><tr>
      <th>{tr("rental.person")}</th><th>{tr("rental.role")}</th><th>{tr("rental.seat")}</th><th>{tr("rental.status")}</th><th/></tr></thead>
      <tbody>{d.items.length === 0 ? <tr><td colSpan={5}><small>{tr("rental.no_roles")}</small></td></tr>
        : d.items.map((a: any) => <tr key={a.id}><td><b>{a.display_name || a.email}</b><br/><small>{a.email}</small></td>
          <td><span className="ui-pill">{tr(`rental.role_${a.role}` as Key)}</span></td>
          <td>{a.seat ? a.seat.name : "—"}</td><td>{a.status === "active" ? tr("rental.active") : tr("rental.revoked")}</td>
          <td>{a.status === "active" && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => remove(a.id)}>{tr("rental.remove")}</button>}</td>
        </tr>)}</tbody></table></div>
    <h3 className="ops-cat">{tr("rental.add_role")}</h3>
    <FormRow>
      <Field label={tr("rental.email")}><input className="ui-input" value={email} onChange={e => setEmail(e.target.value)} data-testid="role-email"/></Field>
      <Field label={tr("rental.role")}><select className="ui-input" value={role} onChange={e => setRole(e.target.value)} data-testid="role-pick">
        {(d.roles || []).map((r: string) => <option key={r} value={r}>{tr(`rental.role_${r}` as Key)}</option>)}</select></Field>
      <Field label={tr("rental.seat_optional")}><select className="ui-input" value={seat} onChange={e => setSeat(e.target.value)}>
        <option value="">—</option>{humans.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></Field>
    </FormRow>
    <button className="ui-btn is-primary" disabled={busy || !email} onClick={save} data-testid="role-save">{tr("rental.save_role")}</button>
  </section>;
}
