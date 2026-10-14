"use client";
import {useEffect, useState} from "react";
import {apiV19} from "@/lib/api";
import {Button} from "./ui/Button";
import {Panel} from "./ui/Panel";
import {StatusPill, Tone} from "./ui/StatusPill";
import {ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {Icon} from "./Icon";
import {t as tr, lazy} from "../lib/i18n";

type Descriptor = {
  mode:string; native:boolean; gateway_ws:string; gateway_http:string;
  protocol_version:number; scopes_requested:string[]; auto_dispatch:boolean;
  token_configured:boolean; http_denied_tools:string[];
  legacy_contract_map:Record<string,{upstream:string|null; note:string}>;
  notes:string[];
};

const DOC_TONE:Record<string,Tone> = {ok:"ok", warn:"wait", fail:"risk", skip:"neutral"};
const DOC_VI:Record<string,string> = lazy(() => ({ok:tr("openclaw.on"), warn:tr("openclaw.can_chu_y"), fail:tr("openclaw.loi"), skip:tr("openclaw.bo_qua")}));

export function OpenClawControl(){
  const [protocol,setProtocol] = useState<any>(null);
  const [health,setHealth] = useState<any>(null);
  const [agents,setAgents] = useState<any[]>([]);
  const [roster,setRoster] = useState<any>(null);
  const [seats,setSeats] = useState<Record<string,any>>({});
  const [err,setErr] = useState<unknown>(null);
  const [busy,setBusy] = useState(false);
  const [doc,setDoc] = useState<any>(null);
  const [docBusy,setDocBusy] = useState(false);

  async function runDoctor(){
    setDocBusy(true);
    try{ setDoc(await apiV19.doctor()); }
    catch(e:any){ setDoc({status:"fail", ok:0, total:1, checks:[{id:"api", label:tr("openclaw.goi_kiem_tra"), status:"fail", detail:e.message||String(e), fix:tr("openclaw.kiem_tra_dich_vu_api")}]}); }
    finally{ setDocBusy(false); }
  }

  async function load(){
    setErr(null);
    try{
      const [p,h,s] = await Promise.all([apiV19.protocol(), apiV19.health(), apiV19.seats()]);
      setProtocol(p); setHealth(h); setSeats(s.seats||{});
      try{ const a = await apiV19.gatewayAgents(); setAgents(a.agents||[]); }
      catch(e:any){ /* gateway offline is normal in mock mode */ setAgents([]); }
    }catch(e:any){ setErr(e); }
  }
  useEffect(()=>{ load(); runDoctor(); },[]);

  async function reconcile(){
    setBusy(true); setErr(null);
    try{ setRoster(await apiV19.reconcile()); await load(); }
    catch(e:any){ setErr(e); }
    finally{ setBusy(false); }
  }

  const d:Descriptor|undefined = protocol?.runtime;
  const healthy = health?.health?.status === "healthy";

  return <div className="ui-grid" style={{gap: 16}}>
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} context="OpenClaw"/> : null}

    <Panel title={tr("openclaw.kiem_tra_ket_noi")} testId="openclaw-doctor"
      desc={doc ? tr("openclaw.buoc_on", {p0: doc.ok ?? 0, p1: doc.total ?? (doc.checks || []).length, p2: doc.status === "ok" ? "mọi thứ ổn" : doc.status === "warn" ? "chạy được, có điểm cần chú ý" : "cần xử lý"}) : tr("openclaw.dang_kiem_tra_co_so")}
      actions={<Button size="sm" variant="primary" icon="pulse" busy={docBusy} onClick={runDoctor}>{docBusy ? tr("openclaw.dang_kiem_tra") : tr("openclaw.kiem_tra_lai")}</Button>} flush>
      {!doc ? <div className="ui-panel-body"><SkeletonRows n={4} h={34}/></div> : <ol className="oc-checks">
        {(doc.checks || []).map((c: any) => <li key={c.id} className={"oc-check is-" + c.status}>
          <StatusPill tone={DOC_TONE[c.status] || "neutral"}>{DOC_VI[c.status] || c.status}</StatusPill>
          <div className="oc-check-body"><b>{c.label}</b><span>{c.detail}</span>
            {c.fix && <span className="oc-fix"><Icon name="arrow-right" size={12}/>{c.fix}</span>}
            {c.action && <Button size="sm" disabled={docBusy} onClick={async () => {
              setDocBusy(true);
              try {
                const r: any = await apiV19.doctorAction(c.action.method, c.action.path);
                const bad = (r?.agents || []).filter((a: any) => a.status === "failed");
                if (bad.length) setErr(new Error(tr("openclaw.cai_chua_duoc_cho", {p0: bad.map((a: any) => a.agent_id).join(", "), p1: bad[0].reason || bad[0].error})));
              } catch (e: any) { setErr(e); }
              finally { setDocBusy(false); }
              runDoctor();
            }}>{c.action.label}</Button>}</div>
        </li>)}
      </ol>}
    </Panel>

    <div className="oc-facts">
      <div><small>{tr("openclaw.che_do_chay")}</small><b>{d?.mode ?? "…"}</b><StatusPill tone={d?.native ? "ok" : "wait"}>{d?.native ? tr("openclaw.openclaw_that") : tr("openclaw.chua_gan_loi")}</StatusPill></div>
      <div><small>Gateway</small><b className="ui-ellipsis" translate="no">{d?.gateway_ws ?? "—"}</b><StatusPill tone={healthy ? "ok" : "risk"}>{healthy ? tr("openclaw.dang_ket_noi") : health?.health?.status ?? tr("openclaw.khong_ro")}</StatusPill></div>
      <div><small>{tr("openclaw.giao_thuc")}</small><b>v{d?.protocol_version ?? "—"}</b><span className="ui-row-meta">{(d?.scopes_requested || []).join(", ") || "—"}</span></div>
      <div><small>{tr("openclaw.agent_tren_gateway")}</small><b className="ui-num">{agents.length}</b><span className="ui-row-meta">{Object.keys(seats).length} {tr("openclaw.ghe_da_gan")}</span></div>
      <div><small>Token gateway</small><b>{d?.token_configured ? tr("openclaw.da_cau_hinh") : tr("openclaw.trong")}</b><span className="ui-row-meta">{tr("openclaw.tu_giao_viec")} {d?.auto_dispatch ? tr("openclaw.bat") : tr("openclaw.tat")}</span></div>
    </div>

    <Panel title={tr("openclaw.doi_soat_nhan_su_ai")} desc={tr("openclaw.so_runtime_agent_id_cua")}
      actions={<Button size="sm" busy={busy} onClick={reconcile}>{busy ? tr("openclaw.dang_doi_soat") : tr("openclaw.doi_soat_ngay")}</Button>} flush>
      {roster && <div className="oc-facts" style={{padding: 16, borderBottom: "1px solid var(--border)"}}>
        <div><small>{tr("openclaw.khop")}</small><b className="ui-num">{roster.counts.matched}</b></div>
        <div><small>{tr("openclaw.ghe_mo_coi")}</small><b className="ui-num">{roster.counts.orphaned}</b></div>
        <div><small>{tr("openclaw.agent_chua_gan_ghe")}</small><b className="ui-num">{roster.counts.unbound}</b></div>
        <div><small>{tr("openclaw.da_cap_nhat")}</small><b className="ui-num">{roster.counts.updated}</b></div>
      </div>}
      <div className="ui-table-wrap"><table className="ui-table">
        <thead><tr><th>{tr("openclaw.agent_tren_gateway")}</th><th>{tr("openclaw.nhan_su")}</th><th>{tr("openclaw.trang_thai")}</th><th>{tr("openclaw.phien_chinh")}</th></tr></thead>
        <tbody>
          {Object.entries(seats).map(([rid, seat]: any) => <tr key={rid}>
            <td><code translate="no">{rid}</code></td><td>{seat.name}</td>
            <td><StatusPill tone={seat.lifecycle === "detached" ? "risk" : "ok"}>{seat.lifecycle === "detached" ? tr("openclaw.roi_gateway") : seat.lifecycle === "active" ? tr("openclaw.dang_hoat_dong") : seat.lifecycle}</StatusPill></td>
            <td><code translate="no">agent:{rid}:main</code></td>
          </tr>)}
          {Object.keys(seats).length === 0 && <tr><td colSpan={4} className="ui-row-meta">{tr("openclaw.chua_co_ghe_agent_nao")}</td></tr>}
        </tbody>
      </table></div>
    </Panel>

    <Panel title={tr("openclaw.cong_cu_bi_chan_qua")} desc={tr("openclaw.gateway_chan_san_cac_tool")}>
      <div className="ui-chips">{(d?.http_denied_tools || []).map(t => <StatusPill key={t} tone="risk" dot={false}><span translate="no">{t}</span></StatusPill>)}</div>
      {(d?.notes || []).length > 0 && <ul className="oc-notes">{(d?.notes || []).map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </Panel>
  </div>;
}
