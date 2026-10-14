"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {useSearchParams} from "next/navigation";
import {Icon} from "./Icon";
import {EmptyState, ErrorState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {apiCosts, errorText} from "../lib/api";
import {t as tr, intlLocale} from "../lib/i18n";

/* M4b — Chi phí: tổng chi model (usage_events từ gateway) + ngân sách 3 nấc
   theo công ty / phòng ban / nhóm / agent. Nấc: cảnh báo → dừng mềm (lượt chạy
   mới cần duyệt trong Hộp việc) → dừng cứng (100%, seat tạm dừng). */

const money = (v: number) => `$${Number(v || 0).toFixed(Number(v) >= 1 ? 2 : 4)}`;
const LEVEL_CLS: Record<string, string> = {ok: "is-ok", warned: "is-warn", soft_stopped: "is-soft", exhausted: "is-hard"};

function Bars({rows, empty}: {rows: {name: string; cost_usd: number}[]; empty: string}) {
  if (!rows.length) return <p className="ui-empty-line">{empty}</p>;
  const max = Math.max(...rows.map(r => r.cost_usd), 1e-9);
  return <ul className="cst-bars">{rows.slice(0, 8).map(r => <li key={r.name}>
    <span className="cst-bar-name">{r.name}</span>
    <span className="cst-bar"><i style={{width: `${Math.max(2, r.cost_usd / max * 100)}%`}}/></span>
    <b className="ui-num">{money(r.cost_usd)}</b>
  </li>)}</ul>;
}

function Overview() {
  const [d, setD] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  const load = useCallback(() => { setErr(null); apiCosts.overview(30).then(setD).catch(setErr); }, []);
  useEffect(() => { load(); }, [load]);
  if (err) return <ErrorState error={err} onRetry={load} context={tr("costs.doc_so_chi_phi")}/>;
  if (!d) return <SkeletonRows n={2} h={76}/>;
  const t = d.totals;
  return <div className="cst-overview">
    <div className="cst-tiles">
      <div><small>{tr("costs.hom_nay")}</small><b>{money(t.today)}</b></div>
      <div><small>{tr("costs.k7_ngay")}</small><b>{money(t.d7)}</b></div>
      <div><small>{d.days} {tr("costs.ngay")}</small><b>{money(t.window)}</b></div>
      <div><small>{tr("costs.luot_goi_model")}</small><b>{t.model_calls.toLocaleString(intlLocale())}</b><em>{t.tokens.toLocaleString(intlLocale())} token</em></div>
    </div>
    {d.alerts > 0 && <Link className="cst-alert" href="?tab=budgets"><Icon name="alert" size={16}/>
      {d.alerts} {tr("costs.ngan_sach_dang_o_nac")}</Link>}
    {t.model_calls === 0 && <EmptyState mood="ngu" title={tr("costs.chua_co_chi_phi_model")}>
      {tr("costs.chi_phi_duoc_ghi_khi")}
    </EmptyState>}
    {t.model_calls > 0 && <div className="cst-cols">
      <section><h3>Theo agent</h3><Bars rows={d.by_agent} empty="—"/></section>
      <section><h3>{tr("costs.theo_phong_ban")}</h3><Bars rows={d.by_department} empty="—"/></section>
      <section><h3>{tr("costs.theo_cong_ty")}</h3><Bars rows={d.by_company} empty="—"/></section>
    </div>}
    <p className="cst-source">{tr("costs.nguon")} {d.source}.</p>
  </div>;
}

function Meter({b}: {b: any}) {
  return <div className="cst-meter" aria-label={tr("costs.da_dung_han_muc", {p0: b.pct})}>
    <i className={LEVEL_CLS[b.threshold_state] || ""} style={{width: `${Math.min(100, b.pct)}%`}}/>
    {b.levels.filter((l: any) => l.pct < 100).map((l: any) =>
      <span key={l.key} className="cst-mark" style={{left: `${l.pct}%`}} title={`${l.label} ${l.pct}%`}/>)}
  </div>;
}

function BudgetCard({b, manage, onChanged}: {b: any; manage: boolean; onChanged: (msg: string) => void}) {
  const [mode, setMode] = useState<"" | "edit" | "raise">("");
  const [limit, setLimit] = useState(String(b.amount_limit)), [warn, setWarn] = useState(String(b.warn_pct));
  const [soft, setSoft] = useState(b.soft_stop_pct ? String(b.soft_stop_pct) : "");
  const [add, setAdd] = useState(""), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  async function run(fn: () => Promise<any>, msg: string) {
    setBusy(true); setErr("");
    try { await fn(); setMode(""); onChanged(msg); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }
  const hard = b.threshold_state === "exhausted";
  return <article className={"cst-budget " + (LEVEL_CLS[b.threshold_state] || "")} data-testid={`budget-${b.id}`}>
    <header>
      <div><b>{b.name}</b><small>{b.scope_vi} · {b.scope_name}</small></div>
      <span className={"cst-level " + (LEVEL_CLS[b.threshold_state] || "")}>{b.level_vi}</span>
    </header>
    <Meter b={b}/>
    <div className="cst-figures">
      <span><b className="ui-num">{money(b.amount_spent)}</b> / {money(b.amount_limit)} ({b.pct}%)</span>
      {b.amount_reserved > 0 && <span>{tr("costs.dang_giu_cho")} {money(b.amount_reserved)}</span>}
      <span>{tr("costs.nac_canh_bao")} {b.warn_pct}%{b.soft_stop_pct ? tr("costs.dung_mem", {p0: b.soft_stop_pct}) : ""} {tr("costs.dung_cung_100")}</span>
    </div>
    {b.pending_approvals > 0 && <Link className="cst-alert" href="/app/inbox?group=approvals">
      <Icon name="check" size={14}/>{b.pending_approvals} {tr("costs.yeu_cau_chi_tiep_dang")}</Link>}
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    {manage && mode === "edit" && <div className="cst-form">
      <label>{tr("costs.han_muc_usd")}<input inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value)} disabled={hard}/></label>
      <label>{tr("costs.canh_bao")}<input inputMode="numeric" value={warn} onChange={e => setWarn(e.target.value)}/></label>
      <label>{tr("costs.dung_mem_2")}<input inputMode="numeric" value={soft} placeholder={tr("costs.tat")} onChange={e => setSoft(e.target.value)}/></label>
      {hard && <small>{tr("costs.ngan_sach_da_dung_cung")}</small>}
      <div className="cst-form-actions">
        <button className="ui-btn is-ghost" onClick={() => setMode("")}>{tr("costs.huy")}</button>
        <button className="ui-btn is-primary" disabled={busy} onClick={() => run(() => apiCosts.update(b.id, {
          ...(hard ? {} : {amount_limit: Number(limit)}), warn_pct: Number(warn), soft_stop_pct: soft ? Number(soft) : null,
        }), tr("costs.da_luu_ngan_sach"))}>{tr("costs.luu")}</button>
      </div>
    </div>}
    {manage && mode === "raise" && <div className="cst-form">
      <label>{tr("costs.cong_them_usd")}<input inputMode="decimal" value={add} onChange={e => setAdd(e.target.value)}/></label>
      <label className="is-wide">{tr("costs.ly_do_luu_vao_nhat")}<input value={reason} onChange={e => setReason(e.target.value)}
        placeholder={tr("costs.vd_chay_chien_dich_he")}/></label>
      <div className="cst-form-actions">
        <button className="ui-btn is-ghost" onClick={() => setMode("")}>{tr("costs.huy")}</button>
        <button className="ui-btn is-primary" disabled={busy || !Number(add)} onClick={() => run(() =>
          apiCosts.override(b.id, {add_usd: Number(add), reason}), tr("costs.da_nang_han_muc_seat"))}>{tr("costs.nang_han_muc")}</button>
      </div>
    </div>}
    {manage && !mode && <div className="cst-actions">
      <button className="ui-btn is-ghost is-sm" onClick={() => setMode("edit")}>{tr("costs.sua_nac")}</button>
      <button className={"ui-btn is-sm " + (hard ? "is-primary" : "is-ghost")} onClick={() => setMode("raise")}>{tr("costs.nang_han_muc")}</button>
      {!hard && <button className="ui-btn is-ghost is-sm" disabled={busy}
        onClick={() => window.confirm(tr("costs.luu_tru_ngan_sach_pham", {p0: b.name}))
          && run(() => apiCosts.archive(b.id), tr("costs.da_luu_tru_ngan_sach"))}>{tr("costs.luu_tru")}</button>}
    </div>}
  </article>;
}

function CreateBudget({scopes, onDone}: {scopes: any; onDone: (msg: string) => void}) {
  const [type, setType] = useState("department"), [sid, setSid] = useState("");
  const [limit, setLimit] = useState("20"), [warn, setWarn] = useState("80"), [soft, setSoft] = useState("90");
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const opts: any[] = scopes?.[type] || [];
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      await apiCosts.create({scope_type: type, scope_id: sid ? Number(sid) : null, amount_limit: Number(limit),
        warn_pct: Number(warn), soft_stop_pct: soft ? Number(soft) : null});
      onDone(tr("costs.da_tao_ngan_sach"));
    } catch (e2) { setErr(errorText(e2)); } finally { setBusy(false); }
  }
  return <form className="cst-form cst-create" onSubmit={submit}>
    <label>{tr("costs.pham_vi")}<select value={type} onChange={e => { setType(e.target.value); setSid(""); }}>
      <option value="company">{tr("costs.cong_ty")}</option><option value="department">{tr("costs.phong_ban")}</option>
      <option value="team">{tr("costs.nhom")}</option><option value="member">Agent</option></select></label>
    <label className="is-wide">{tr("costs.ap_cho")}<select value={sid} onChange={e => setSid(e.target.value)} required>
      <option value="">{tr("costs.chon")}</option>{opts.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
    <label>{tr("costs.han_muc_usd")}<input inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value)} required/></label>
    <label>{tr("costs.canh_bao")}<input inputMode="numeric" value={warn} onChange={e => setWarn(e.target.value)}/></label>
    <label>{tr("costs.dung_mem_2")}<input inputMode="numeric" value={soft} placeholder={tr("costs.tat")} onChange={e => setSoft(e.target.value)}/></label>
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    <div className="cst-form-actions"><button className="ui-btn is-primary" disabled={busy}>{busy ? tr("costs.dang_tao") : tr("costs.tao_ngan_sach")}</button></div>
  </form>;
}

function Budgets() {
  const [d, setD] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const load = useCallback(() => { setErr(null); apiCosts.budgets().then(setD).catch(setErr); }, []);
  useEffect(() => { load(); }, [load]);
  const changed = (msg: string) => { toast(msg); setCreating(false); load(); };
  if (err) return <ErrorState error={err} onRetry={load} context={tr("costs.mo_so_ngan_sach")}/>;
  if (!d) return <SkeletonRows n={2} h={120}/>;
  return <div className="cst-budgets">
    <p className="cst-help">{tr("costs.ba_nac_tren_moi_ngan")} <b>{tr("costs.canh_bao_2")}</b> {tr("costs.bao_vao_hop_viec_agent")}
      <b> {tr("costs.dung_mem_3")}</b> {tr("costs.moi_luot_chay_moi_can")}
      <b> {tr("costs.dung_cung")}</b> {tr("costs.o_100_seat_tam_dung")}</p>
    {d.caps.manage && (creating ? <CreateBudget scopes={d.scopes} onDone={changed}/>
      : <button className="ui-btn is-primary" onClick={() => setCreating(true)}><Icon name="plus" size={14}/>{tr("costs.them_ngan_sach")}</button>)}
    {!d.budgets.length && !creating && <EmptyState mood="chao" title={tr("costs.chua_co_ngan_sach_nao")}>
      {tr("costs.dat_han_muc_cho_cong")}
    </EmptyState>}
    <div className="cst-list">{d.budgets.map((b: any) => <BudgetCard key={b.id} b={b} manage={d.caps.manage} onChanged={changed}/>)}</div>
  </div>;
}

export function CostsBoard() {
  /* Tab Tổng quan / Ngân sách nằm ở khung trang (lib/nav.ts) — đổi URL, chia sẻ được. */
  const tab = useSearchParams().get("tab") === "budgets" ? "budgets" : "overview";
  return <div className="cst">
    {tab === "overview" ? <Overview/> : <Budgets/>}
  </div>;
}
