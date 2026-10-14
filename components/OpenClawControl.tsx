"use client";
import {useEffect, useState} from "react";
import {apiV19} from "@/lib/api";
import {Button} from "./ui/Button";
import {Panel} from "./ui/Panel";
import {StatusPill, Tone} from "./ui/StatusPill";
import {ErrorBanner} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {Icon} from "./Icon";

type Descriptor = {
  mode:string; native:boolean; gateway_ws:string; gateway_http:string;
  protocol_version:number; scopes_requested:string[]; auto_dispatch:boolean;
  token_configured:boolean; http_denied_tools:string[];
  legacy_contract_map:Record<string,{upstream:string|null; note:string}>;
  notes:string[];
};

const DOC_TONE:Record<string,Tone> = {ok:"ok", warn:"wait", fail:"risk", skip:"neutral"};
const DOC_VI:Record<string,string> = {ok:"Ổn", warn:"Cần chú ý", fail:"Lỗi", skip:"Bỏ qua"};

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
    catch(e:any){ setDoc({status:"fail", ok:0, total:1, checks:[{id:"api", label:"Gọi kiểm tra", status:"fail", detail:e.message||String(e), fix:"Kiểm tra dịch vụ API (cổng 8000) đang chạy rồi bấm Kiểm tra lại."}]}); }
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

    <Panel title="Kiểm tra kết nối" testId="openclaw-doctor"
      desc={doc ? `${doc.ok ?? 0}/${doc.total ?? (doc.checks || []).length} bước ổn · ${doc.status === "ok" ? "mọi thứ ổn" : doc.status === "warn" ? "chạy được, có điểm cần chú ý" : "cần xử lý"}` : "Đang kiểm tra cơ sở dữ liệu, gateway, model và agent…"}
      actions={<Button size="sm" variant="primary" icon="pulse" busy={docBusy} onClick={runDoctor}>{docBusy ? "Đang kiểm tra…" : "Kiểm tra lại"}</Button>} flush>
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
                if (bad.length) setErr(new Error(`Cài chưa được cho ${bad.map((a: any) => a.agent_id).join(", ")}: ${bad[0].reason || bad[0].error}`));
              } catch (e: any) { setErr(e); }
              finally { setDocBusy(false); }
              runDoctor();
            }}>{c.action.label}</Button>}</div>
        </li>)}
      </ol>}
    </Panel>

    <div className="oc-facts">
      <div><small>Chế độ chạy</small><b>{d?.mode ?? "…"}</b><StatusPill tone={d?.native ? "ok" : "wait"}>{d?.native ? "OpenClaw thật" : "chưa gắn lõi"}</StatusPill></div>
      <div><small>Gateway</small><b className="ui-ellipsis" translate="no">{d?.gateway_ws ?? "—"}</b><StatusPill tone={healthy ? "ok" : "risk"}>{healthy ? "Đang kết nối" : health?.health?.status ?? "không rõ"}</StatusPill></div>
      <div><small>Giao thức</small><b>v{d?.protocol_version ?? "—"}</b><span className="ui-row-meta">{(d?.scopes_requested || []).join(", ") || "—"}</span></div>
      <div><small>Agent trên gateway</small><b className="ui-num">{agents.length}</b><span className="ui-row-meta">{Object.keys(seats).length} ghế đã gắn</span></div>
      <div><small>Token gateway</small><b>{d?.token_configured ? "Đã cấu hình" : "Trống"}</b><span className="ui-row-meta">Tự giao việc: {d?.auto_dispatch ? "bật" : "tắt"}</span></div>
    </div>

    <Panel title="Đối soát nhân sự AI ↔ OpenClaw" desc="So runtime_agent_id của từng ghế với agent thật trên gateway. Ghế mất agent bị đánh dấu “rời gateway”; không xoá dữ liệu."
      actions={<Button size="sm" busy={busy} onClick={reconcile}>{busy ? "Đang đối soát…" : "Đối soát ngay"}</Button>} flush>
      {roster && <div className="oc-facts" style={{padding: 16, borderBottom: "1px solid var(--border)"}}>
        <div><small>Khớp</small><b className="ui-num">{roster.counts.matched}</b></div>
        <div><small>Ghế mồ côi</small><b className="ui-num">{roster.counts.orphaned}</b></div>
        <div><small>Agent chưa gắn ghế</small><b className="ui-num">{roster.counts.unbound}</b></div>
        <div><small>Đã cập nhật</small><b className="ui-num">{roster.counts.updated}</b></div>
      </div>}
      <div className="ui-table-wrap"><table className="ui-table">
        <thead><tr><th>Agent trên gateway</th><th>Nhân sự</th><th>Trạng thái</th><th>Phiên chính</th></tr></thead>
        <tbody>
          {Object.entries(seats).map(([rid, seat]: any) => <tr key={rid}>
            <td><code translate="no">{rid}</code></td><td>{seat.name}</td>
            <td><StatusPill tone={seat.lifecycle === "detached" ? "risk" : "ok"}>{seat.lifecycle === "detached" ? "Rời gateway" : seat.lifecycle === "active" ? "Đang hoạt động" : seat.lifecycle}</StatusPill></td>
            <td><code translate="no">agent:{rid}:main</code></td>
          </tr>)}
          {Object.keys(seats).length === 0 && <tr><td colSpan={4} className="ui-row-meta">Chưa có ghế agent nào gắn với OpenClaw.</td></tr>}
        </tbody>
      </table></div>
    </Panel>

    <Panel title="Công cụ bị chặn qua HTTP" desc="Gateway chặn sẵn các tool có thể đổi trạng thái máy chủ; ClawCompany chặn lại ở phía mình để báo lỗi rõ ràng.">
      <div className="ui-chips">{(d?.http_denied_tools || []).map(t => <StatusPill key={t} tone="risk" dot={false}><span translate="no">{t}</span></StatusPill>)}</div>
      {(d?.notes || []).length > 0 && <ul className="oc-notes">{(d?.notes || []).map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </Panel>
  </div>;
}
