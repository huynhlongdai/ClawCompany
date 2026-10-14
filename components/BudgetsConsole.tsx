"use client";
// D2.3 — Ngân sách ba nấc: phạm vi (công ty/phòng ban/seat/dự án/mục tiêu),
// cảnh báo ở warn_pct, hết hạn mức thì seat tạm dừng; mở lại chỉ qua override
// có lý do (ghi audit). Chi tiêu lấy từ sổ cái (đã quyết toán theo gateway),
// không từ ước lượng.
import {useEffect, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiV9, errorText} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {t, lazy} from "../lib/i18n";

const SCOPE_VI: Record<string, string> = lazy(() => ({company: t("costs.cong_ty"), department: t("costs.phong_ban"), member: "Seat", project: t("costs.du_an"), goal: t("costs.muc_tieu")}));
const STATE_VI: Record<string, {label: string; color: string}> = lazy(() => ({
  ok: {label: t("costs.binh_thuong"), color: "#16794c"},
  warned: {label: t("costs.canh_bao_chi_viec_critical"), color: "#b26a00"},
  exhausted: {label: t("costs.het_han_muc_seat_tam"), color: "#b42318"},
}));
const usd = (n: any, d = 4) => `$${Number(n || 0).toFixed(d)}`;

function Bar({b}: {b: any}) {
  const spent = Math.min(100, Number(b.pct || 0));
  const reserved = b.amount_limit ? Math.min(100 - spent, Number(b.amount_reserved || 0) / b.amount_limit * 100) : 0;
  const color = STATE_VI[b.threshold_state]?.color || "#16794c";
  return <div style={{position: "relative", height: 10, background: "#eef0f3", borderRadius: 6, overflow: "hidden", margin: "6px 0"}}>
    <i style={{position: "absolute", left: 0, top: 0, bottom: 0, width: `${spent}%`, background: color}}/>
    <i style={{position: "absolute", left: `${spent}%`, top: 0, bottom: 0, width: `${reserved}%`, background: color, opacity: .35}}/>
    <i title={t("costs.canh_bao_o", {p0: b.warn_pct})} style={{position: "absolute", left: `${b.warn_pct}%`, top: -2, bottom: -2, width: 2, background: "#555"}}/>
  </div>;
}

function Table({title, rows}: {title: string; rows: any[]}) {
  return <div style={{marginTop: 10}}>
    <b style={{fontSize: 13}}>{title}</b>
    {rows.length ? <table style={{width: "100%", fontSize: 13, borderCollapse: "collapse"}}><tbody>
      {rows.map((r: any) => <tr key={r.name} style={{borderBottom: "1px solid #eee"}}>
        <td style={{padding: "4px 0"}}>{r.name}</td><td style={{textAlign: "right"}}>{usd(r.spent_usd)}</td></tr>)}
    </tbody></table> : <div className="v9Empty" style={{padding: 6}}>{t("costs.chua_co_chi_tieu")}</div>}
  </div>;
}

export function BudgetsConsole() {
  const [data, setData] = useState<any>(null), [sel, setSel] = useState<number | null>(null), [detail, setDetail] = useState<any>(null);
  const [error, setError] = useState(""), [note, setNote] = useState("");
  const [members, setMembers] = useState<any[]>([]), [departments, setDepartments] = useState<any[]>([]), [projects, setProjects] = useState<any[]>([]);
  const [form, setForm] = useState<any>({name: "", scope_type: "member", scope_id: "", amount_limit: "1", warn_pct: "80"});
  const [ov, setOv] = useState<any>({reason: "", add_usd: "1"});

  async function load() {
    try { const d = await apiV9.budgetsOverview(); setData(d); if (sel == null && d.budgets[0]) setSel(d.budgets[0].id); }
    catch (e: any) { setError(errorText(e)); }
  }
  useEffect(() => {
    load();
    api.members().then((x: any) => setMembers(x || [])).catch(() => {});
    api.departments().then((x: any) => setDepartments(x || [])).catch(() => {});
    api.projects().then((x: any) => setProjects(x || [])).catch(() => {});
  }, []);
  useEffect(() => { if (sel != null) apiV9.budget(sel).then(setDetail).catch((e: any) => setError(errorText(e))); }, [sel, data]);

  const b = data?.budgets?.find((x: any) => x.id === sel);
  const options = form.scope_type === "member" ? members.filter((m: any) => m.member_type === "agent")
    : form.scope_type === "department" ? departments : form.scope_type === "project" ? projects : [];
  const nameOf = (x: any) => {
    const list = x.scope_type === "member" ? members : x.scope_type === "department" ? departments : x.scope_type === "project" ? projects : [];
    const hit = list.find((m: any) => m.id === x.scope_id);
    return hit ? (hit.name || hit.title) : (x.scope_id ? `#${x.scope_id}` : t("costs.toan_bo"));
  };

  async function create() {
    setError(""); setNote("");
    try {
      await apiV9.createBudget({organization_id: activeOrganizationId(), name: form.name, scope_type: form.scope_type,
        scope_id: form.scope_id ? Number(form.scope_id) : null, amount_limit: Number(form.amount_limit), warn_pct: Number(form.warn_pct)});
      setNote(t("costs.da_tao_phong_bi")); setForm({...form, name: ""}); await load();
    } catch (e: any) { setError(errorText(e)); }
  }
  async function override() {
    if (!b) return;
    setError(""); setNote("");
    try {
      const r: any = await apiV9.overrideBudget(b.id, {reason: ov.reason, add_usd: Number(ov.add_usd)});
      setNote(t("costs.da_nang_han_muc_len", {p0: usd(r.budget.amount_limit, 2), p1: r.restored_members.length, p2: r.restored_tasks.length, p3: r.requeued_wakeups.length}));
      setOv({reason: "", add_usd: "1"}); await load();
    } catch (e: any) { setError(errorText(e)); }
  }

  return <PageFrame title={t("costs.ngan_sach_ai")} subtitle={t("costs.giu_cho_truoc_khi_gui")}>
    {error && <div className="v8Error" data-testid="budget-error">{error}</div>}
    {note && <div className="v8Card" style={{padding: 10, marginBottom: 10, borderLeft: "3px solid #16794c"}} data-testid="budget-note">{note}</div>}
    <div className="v9Grid2">
      <section className="v8Card">
        <div className="v8CardHead"><div><b>{t("costs.phong_bi_ngan_sach")}</b><span>{t("costs.het_han_muc_thi_gateway")}</span></div></div>
        <div className="v9List">
          {(data?.budgets || []).map((x: any) => <button className="v9BudgetButton" key={x.id} onClick={() => setSel(x.id)} data-testid={`budget-${x.id}`}
            style={{display: "block", textAlign: "left", width: "100%", outline: x.id === sel ? "2px solid #4f46e5" : undefined}}>
            <div style={{display: "flex", justifyContent: "space-between", gap: 8}}>
              <b>{x.name}</b>
              <small style={{color: STATE_VI[x.threshold_state]?.color}}>{STATE_VI[x.threshold_state]?.label || x.threshold_state}</small>
            </div>
            <small>{SCOPE_VI[x.scope_type] || x.scope_type}: {nameOf(x)} {t("costs.canh_bao_o_2")} {x.warn_pct}%</small>
            <Bar b={x}/>
            <small>{t("costs.da_tieu")} {usd(x.amount_spent)} {t("costs.dang_giu")} {usd(x.amount_reserved)} {t("costs.han_muc")} {usd(x.amount_limit, 2)} ({Number(x.pct).toFixed(1)}%)</small>
          </button>)}
          {data && !data.budgets.length && <div className="v9Empty">{t("costs.chua_co_phong_bi_nao")}</div>}
        </div>
        <div className="v9Form" style={{marginTop: 12}}>
          <b>{t("costs.tao_phong_bi")}</b>
          <div className="v9FormRow">
            <label>{t("costs.ten")}<input value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder={t("costs.vd_nina_thang_10")}/></label>
            <label>{t("costs.pham_vi")}<select value={form.scope_type} onChange={e => setForm({...form, scope_type: e.target.value, scope_id: ""})}>
              {Object.entries(SCOPE_VI).filter(([k]) => k !== "goal").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            {form.scope_type !== "company" && <label>{t("costs.thuoc")}<select value={form.scope_id} onChange={e => setForm({...form, scope_id: e.target.value})}>
              <option value="">{t("costs.chon")}</option>{options.map((o: any) => <option key={o.id} value={o.id}>{o.name || o.title}</option>)}</select></label>}
          </div>
          <div className="v9FormRow">
            <label>{t("costs.han_muc_usd")}<input type="number" step="0.01" value={form.amount_limit} onChange={e => setForm({...form, amount_limit: e.target.value})}/></label>
            <label>{t("costs.canh_bao_o_3")}<input type="number" value={form.warn_pct} onChange={e => setForm({...form, warn_pct: e.target.value})}/></label>
          </div>
          <button className="v8Primary" onClick={create} disabled={!form.name}>{t("costs.tao")}</button>
        </div>
      </section>
      <section className="v8Card">
        <div className="v8CardHead"><div><b>{b ? b.name : t("costs.chon_mot_phong_bi")}</b><span>{t("costs.chi_tieu_that_theo_seat")}</span></div></div>
        {b ? <div data-testid="budget-detail">
          <div className="v9LedgerSummary">
            <span>{t("costs.han_muc_2")}<b>{usd(b.amount_limit, 2)}</b></span><span>{t("costs.dang_giu_2")}<b>{usd(b.amount_reserved)}</b></span>
            <span>{t("costs.da_tieu")}<b>{usd(b.amount_spent)}</b></span><span>{t("costs.con_lai")}<b>{usd(b.remaining)}</b></span>
          </div>
          <Table title="Theo seat" rows={b.spend.by_seat}/>
          <Table title="Theo task" rows={b.spend.by_task}/>
          <Table title={t("costs.theo_du_an")} rows={b.spend.by_project}/>
          <div className="v9Form" style={{marginTop: 12, borderTop: "1px solid #eee", paddingTop: 10}}>
            <b>{t("costs.nang_han_muc_override")}</b>
            <small>{t("costs.can_ly_do_ghi_vao")}</small>
            <div className="v9FormRow">
              <label>{t("costs.them_usd")}<input type="number" step="0.01" value={ov.add_usd} onChange={e => setOv({...ov, add_usd: e.target.value})}/></label>
              <label>{t("costs.ly_do")}<input value={ov.reason} onChange={e => setOv({...ov, reason: e.target.value})} placeholder={t("costs.vd_duyet_them_cho_chien")} data-testid="override-reason"/></label>
            </div>
            <button className="v8Primary" onClick={override} disabled={ov.reason.trim().length < 3} data-testid="override-submit">{t("costs.nang_han_muc")}</button>
          </div>
          {detail && <div className="v9Ledger" style={{marginTop: 12}}>
            <b style={{fontSize: 13}}>{t("costs.so_cai")}</b>
            {detail.ledger.slice(0, 30).map((x: any) => <div className="v9LedgerRow" key={x.id}>
              <span>{({reserve: t("costs.giu_cho"), spend: t("costs.tieu"), release: t("costs.tra_lai"), credit: t("costs.dieu_chinh_giam")} as any)[x.entry_type] || x.entry_type}</span>
              <b>{usd(x.amount)}</b><small>{x.source_id} · {x.memo}</small></div>)}
          </div>}
        </div> : <div className="v9Empty">{t("costs.chon_mot_phong_bi_de")}</div>}
      </section>
    </div>
    {data?.all && <section className="v8Card" style={{marginTop: 12}}>
      <div className="v8CardHead"><div><b>{t("costs.toan_to_chuc")}</b><span>{t("costs.moi_luot_chay_chi_dem")} {usd(data.all.total_usd)}</span></div></div>
      <div className="v9Grid2"><Table title="Theo seat" rows={data.all.by_seat}/><Table title={t("costs.theo_du_an")} rows={data.all.by_project}/></div>
    </section>}
  </PageFrame>;
}
