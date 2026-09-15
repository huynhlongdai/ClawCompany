"use client";
import {useEffect, useState} from "react";
import {apiV19} from "@/lib/api";

type Descriptor = {
  mode:string; native:boolean; gateway_ws:string; gateway_http:string;
  protocol_version:number; scopes_requested:string[]; auto_dispatch:boolean;
  token_configured:boolean; http_denied_tools:string[];
  legacy_contract_map:Record<string,{upstream:string|null; note:string}>;
  notes:string[];
};

export function OpenClawControl(){
  const [protocol,setProtocol] = useState<any>(null);
  const [health,setHealth] = useState<any>(null);
  const [agents,setAgents] = useState<any[]>([]);
  const [roster,setRoster] = useState<any>(null);
  const [seats,setSeats] = useState<Record<string,any>>({});
  const [err,setErr] = useState("");
  const [busy,setBusy] = useState(false);

  async function load(){
    setErr("");
    try{
      const [p,h,s] = await Promise.all([apiV19.protocol(), apiV19.health(), apiV19.seats()]);
      setProtocol(p); setHealth(h); setSeats(s.seats||{});
      try{ const a = await apiV19.gatewayAgents(); setAgents(a.agents||[]); }
      catch(e:any){ /* gateway offline is normal in mock mode */ setAgents([]); }
    }catch(e:any){ setErr(e.message||String(e)); }
  }
  useEffect(()=>{ load(); },[]);

  async function reconcile(){
    setBusy(true); setErr("");
    try{ setRoster(await apiV19.reconcile()); await load(); }
    catch(e:any){ setErr(e.message||String(e)); }
    finally{ setBusy(false); }
  }

  const d:Descriptor|undefined = protocol?.runtime;
  const healthy = health?.health?.status === "healthy";

  return <div style={{display:"grid", gap:16}}>
    {err && <div className="panel pad" style={{borderColor:"var(--risk)"}}><b>Lỗi:</b> {err}</div>}

    <div className="metric5">
      <div className="v8Card"><small>Chế độ runtime</small><b>{d?.mode ?? "…"}</b>
        <span className={`tag ${d?.native?"greenTag":"orangeTag"}`}>{d?.native?"OpenClaw thật":"chưa gắn lõi"}</span></div>
      <div className="v8Card"><small>Gateway</small><b>{d?.gateway_ws ?? "—"}</b>
        <span className={`tag ${healthy?"greenTag":"redTag"}`}>{health?.health?.status ?? "unknown"}</span></div>
      <div className="v8Card"><small>Protocol</small><b>v{d?.protocol_version ?? "—"}</b>
        <span className="tag blueTag">{(d?.scopes_requested||[]).join(" · ")}</span></div>
      <div className="v8Card"><small>Agent trên gateway</small><b>{agents.length}</b>
        <span className="tag">{Object.keys(seats).length} ghế đã gắn</span></div>
      <div className="v8Card"><small>Token gateway</small><b>{d?.token_configured?"đã cấu hình":"trống"}</b>
        <span className="tag">auto-dispatch: {d?.auto_dispatch?"bật":"tắt"}</span></div>
    </div>

    <section className="panel">
      <div className="panelHead"><b>Đối soát nhân sự AI ↔ OpenClaw</b>
        <button className="darkBtn" onClick={reconcile} disabled={busy}>{busy?"Đang đối soát…":"Đối soát ngay"}</button></div>
      <div className="pad">
        {!roster && <p>Đối soát so sánh <code>runtime_agent_id</code> của từng ghế agent với danh sách agent thật trên gateway. Ghế mất agent sẽ bị đánh dấu <code>detached</code>; không có dữ liệu nào bị xoá.</p>}
        {roster && <div className="metric5">
          <div className="v8Card"><small>Khớp</small><b>{roster.counts.matched}</b></div>
          <div className="v8Card"><small>Ghế mồ côi</small><b>{roster.counts.orphaned}</b></div>
          <div className="v8Card"><small>Agent chưa gắn ghế</small><b>{roster.counts.unbound}</b></div>
          <div className="v8Card"><small>Đã cập nhật</small><b>{roster.counts.updated}</b></div>
        </div>}
      </div>
      <table className="dataTable">
        <thead><tr><th>runtime_agent_id</th><th>Nhân sự</th><th>Vòng đời</th><th>Session chính</th></tr></thead>
        <tbody>
          {Object.entries(seats).map(([rid,seat]:any)=><tr key={rid}>
            <td><code>{rid}</code></td><td>{seat.name}</td>
            <td><span className={`tag ${seat.lifecycle==="detached"?"redTag":"greenTag"}`}>{seat.lifecycle}</span></td>
            <td><code>agent:{rid}:main</code></td>
          </tr>)}
          {Object.keys(seats).length===0 && <tr><td colSpan={4}>Chưa có ghế agent nào gắn với OpenClaw.</td></tr>}
        </tbody>
      </table>
    </section>

    <section className="panel">
      <div className="panelHead"><b>Bản đồ hợp đồng: giả định cũ → OpenClaw thật</b></div>
      <table className="dataTable">
        <thead><tr><th>Adapter cũ</th><th>Upstream thật</th><th>Ghi chú</th></tr></thead>
        <tbody>
          {Object.entries(d?.legacy_contract_map||{}).map(([legacy,info]:any)=><tr key={legacy}>
            <td><code>{legacy}</code></td>
            <td>{info.upstream ? <code>{info.upstream}</code> : <span className="tag redTag">không tồn tại</span>}</td>
            <td>{info.note}</td>
          </tr>)}
        </tbody>
      </table>
    </section>

    <section className="panel">
      <div className="panelHead"><b>Công cụ bị chặn trên HTTP</b></div>
      <div className="pad">
        <p>Gateway chặn sẵn các tool có thể đổi trạng thái máy chủ. ClawCompany chặn lại ở phía mình để báo lỗi rõ ràng thay vì trả 404 khó hiểu.</p>
        <p>{(d?.http_denied_tools||[]).map(t=><span key={t} className="tag redTag" style={{marginRight:6}}>{t}</span>)}</p>
        {(d?.notes||[]).map((n,i)=><p key={i}>• {n}</p>)}
      </div>
    </section>
  </div>;
}
