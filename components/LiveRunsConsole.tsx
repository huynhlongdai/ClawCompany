"use client";
import {useEffect, useState} from "react";
import {apiV20, apiV21, apiV22, apiV24, apiV25, apiV26} from "@/lib/api";

type Stream = {session_key:string; task_id:number|null; status:string; events:number; approvals:number; last_event_type:string; error:string; started_at:string; lease_backend?:string};
type Approval = {id:number; action:string; risk:string; status:string; policy_key:string};
type Lease = {backend:string; single_process_only:boolean; ttl_seconds:number; owner:string; redis_error:string};
type Readiness = {ready:boolean; missing:string[]; method:string; hint:string;
  method_source?:string; allow_always_enabled?:boolean; note_delivered_upstream?:boolean};
type Registry = {registry:{backend:string; cluster_wide:boolean; redis_error:string}; sweep_enabled:boolean; sweep_seconds:number; auto_dispatch:boolean};
type Orphan = {task_id:number; title:string; session_key:string};
// v24: a hole in the transcript. observed=false means we never recorded
// anything for the session, which is not the same as a gap of zero.
type Gap = {task_id:number; title:string; session_key:string; observed:boolean;
  last_event_at:string|null; gap_seconds:number|null; significant:boolean};
type BackfillReadiness = {ready:boolean; missing:string[]; method:string; runtime:string};

const statusTag:Record<string,string> = {running:"greenTag", finished:"blueTag", stopped:"orangeTag", failed:"redTag", declined:"orangeTag"};
const riskTag:Record<string,string> = {high:"redTag", medium:"orangeTag", low:"greenTag"};

export function LiveRunsConsole(){
  const [streams,setStreams] = useState<Stream[]>([]);
  const [autoDispatch,setAutoDispatch] = useState(false);
  const [approvals,setApprovals] = useState<Approval[]>([]);
  const [lease,setLease] = useState<Lease|null>(null);
  const [resumable,setResumable] = useState<number>(0);
  const [readiness,setReadiness] = useState<Readiness|null>(null);
  const [cluster,setCluster] = useState<Registry|null>(null);
  const [orphans,setOrphans] = useState<Orphan[]>([]);
  const [gaps,setGaps] = useState<Gap[]>([]);
  const [backfillReady,setBackfillReady] = useState<BackfillReadiness|null>(null);
  const [reconcileInfo,setReconcileInfo] = useState<any|null>(null);
  const [fabric,setFabric] = useState<any|null>(null);
  const [err,setErr] = useState("");
  const [note,setNote] = useState("");
  const [busy,setBusy] = useState(false);

  async function load(){
    setBusy(true);
    try{
      const [s,a,l,r,k,c,o,g,b,rc,fb] = await Promise.all([
        apiV22.streams(), apiV20.approvals("pending"),
        apiV21.leases(), apiV21.resumable(), apiV21.approvalReadiness(),
        apiV22.registry(), apiV22.orphans(),
        apiV24.gaps(), apiV24.backfillReadiness(),
        apiV25.reconcileStatus(), apiV26.fabric(),
      ]);
      // v22: the stream list now comes from the shared registry, so it covers
      // every worker rather than whichever one answered this request.
      setStreams(s.streams||[]); setApprovals(a||[]);
      setLease(l.lease||null); setResumable(r.count||0); setReadiness(k||null);
      setCluster(c||null); setOrphans(o?.orphans||[]); setAutoDispatch(!!c?.auto_dispatch);
      setGaps(g?.gaps||[]); setBackfillReady(b||null); setReconcileInfo(rc||null); setFabric(fb||null); setErr("");
    }catch(e:any){ setErr(e?.message||"Không tải được trạng thái luồng"); }
    finally{ setBusy(false); }
  }

  async function resume(){
    setBusy(true);
    try{ await apiV21.resume(); await load(); }
    catch(e:any){ setErr(e?.message||"Không khôi phục được người theo dõi"); setBusy(false); }
  }

  async function claim(){
    setBusy(true);
    try{ await apiV22.claim(); await load(); }
    catch(e:any){ setErr(e?.message||"Không tiếp quản được phiên"); setBusy(false); }
  }

  async function backfill(taskId:number){
    setBusy(true);
    try{ await apiV24.backfill(taskId); await load(); }
    catch(e:any){ setErr(e?.message||"Không lấy lại được yêu cầu quyền"); setBusy(false); }
  }

  async function reconcileNow(taskId:number){
    setBusy(true);
    try{ await apiV25.reconcile(taskId); await load(); }
    catch(e:any){ setErr(e?.message||"Không đối soát được phiên"); setBusy(false); }
  }

  async function decide(id:number, decision:"approved"|"approved_always"|"denied"){
    setBusy(true);
    try{
      const res = await apiV21.decide(id, decision, note);
      if(!res.delivered){
        setErr(`Đã ghi quyết định trong ClawCompany nhưng CHƯA gửi tới OpenClaw: ${res.delivery_error||"chưa cấu hình"}`);
      } else { setErr(""); }
      setNote(""); await load();
    }catch(e:any){ setErr(e?.message||"Không ghi được quyết định"); setBusy(false); }
  }

  useEffect(()=>{ load(); const t = setInterval(load, 10000); return ()=>clearInterval(t); },[]);

  const running = streams.filter(s=>s.status==="running").length;
  const failed = streams.filter(s=>s.status==="failed").length;
  const events = streams.reduce((n,s)=>n+s.events,0);

  return <div>
    {err && <div className="panel pad" style={{borderColor:"var(--risk)"}}>{err}</div>}

    <div className="metric5">
      <div className="v8Card"><div className="kpi4">{running}</div><div>Phiên đang theo dõi</div></div>
      <div className="v8Card"><div className="kpi4">{events}</div><div>Sự kiện đã ghi</div></div>
      <div className="v8Card"><div className="kpi4">{approvals.length}</div><div>Chờ phê duyệt</div></div>
      <div className="v8Card"><div className="kpi4">{resumable}</div><div>Phiên cần nối lại</div></div>
      <div className="v8Card"><div className="kpi4">{autoDispatch?"BẬT":"TẮT"}</div><div>Tự giao việc</div></div>
    </div>

    <div className="panel">
      <div className="panelHead">
        <b>Quyền sở hữu phiên (lease)</b>
        <span>
          <button className="ghost" onClick={resume} disabled={busy}>Nối lại người theo dõi</button>{" "}
          <button className="ghost" onClick={load} disabled={busy}>{busy?"Đang tải…":"Làm mới"}</button>
        </span>
      </div>
      <div className="pad">
        {lease && <p style={{marginTop:0}}>
          Nền lease: <span className={"tag "+(lease.backend==="redis"?"greenTag":"orangeTag")}>{lease.backend}</span>{" "}
          · TTL {lease.ttl_seconds}s · chủ sở hữu <code>{lease.owner}</code>
        </p>}
        {lease?.single_process_only && <p style={{opacity:.75,marginBottom:0}}>
          Không kết nối được Redis nên lease chỉ có hiệu lực trong tiến trình này ({lease.redis_error || "không rõ lý do"}).
          Hãy chạy một worker duy nhất cho tới khi Redis hoạt động, nếu không hai worker có thể cùng theo một phiên.
        </p>}
      </div>
    </div>

    <div className="panel">
      <div className="panelHead">
        <b>Phạm vi quan sát (v22)</b>
        <span>
          <button className="ghost" onClick={claim} disabled={busy || orphans.length===0}>
            Tiếp quản phiên bỏ trống ({orphans.length})
          </button>
        </span>
      </div>
      <div className="pad">
        {cluster && <p style={{marginTop:0}}>
          Sổ theo dõi: <span className={"tag "+(cluster.registry.cluster_wide?"greenTag":"orangeTag")}>
            {cluster.registry.cluster_wide?"toàn cụm":"chỉ tiến trình này"}
          </span>{" "}
          · quét tiếp quản: <span className={"tag "+(cluster.sweep_enabled?"greenTag":"orangeTag")}>
            {cluster.sweep_enabled?`mỗi ${cluster.sweep_seconds}s`:"tắt"}
          </span>
        </p>}
        {cluster && !cluster.registry.cluster_wide && <p style={{opacity:.75,marginBottom:0}}>
          Không có Redis nên bảng dưới chỉ là các phiên của tiến trình này ({cluster.registry.redis_error || "không rõ lý do"}).
          Con số phiên đang chạy vì thế có thể thiếu, không phải là toàn bộ hệ thống.
        </p>}
        {orphans.length>0 && <p style={{marginBottom:0}}>
          {orphans.length} phiên đang chạy mà không worker nào theo dõi — sự kiện và yêu cầu quyền của chúng hiện không được ghi lại.
        </p>}
      </div>
    </div>

    <div className="panel">
      <div className="panelHead"><b>Hạ tầng dùng chung (v26)</b></div>
      <div className="pad">
        <p style={{marginTop:0}}>
          Lease, sổ theo dõi và sổ đối soát nay dùng <b>chung một kết nối Redis</b>, nên chúng không
          thể báo cáo lệch nhau về việc có Redis hay không.{" "}
          <span className={"tag "+(fabric?.cluster_wide?"greenTag":"orangeTag")}>
            {fabric?.cluster_wide?"toàn cụm":"chỉ tiến trình này"}
          </span>{" "}
          {fabric && !fabric.consistent &&
            <span className="tag redTag">ba kho đang báo lệch nhau</span>}
        </p>
        {fabric && <table className="dataTable">
          <tbody>
            <tr><td>Kết nối</td><td><code>{fabric.pool?.url}</code>{" "}
              <span className={"tag "+(fabric.pool?.available?"greenTag":"redTag")}>{fabric.pool?.backend}</span></td></tr>
            <tr><td>Lỗi gần nhất</td><td>{fabric.pool?.error
              ? <><span className="tag redTag">{fabric.pool.error}</span>{" "}thử lại sau {fabric.pool.retry_in}s</>
              : <span style={{opacity:.5}}>—</span>}</td></tr>
            <tr><td>Kết nối lại</td><td>{fabric.pool?.reconnects} lần / {fabric.pool?.failures} lần hỏng</td></tr>
            <tr><td>Chỉ mục lease</td><td><code>{fabric.lease?.index_key}</code>{" "}
              đã dọn {fabric.lease?.index_pruned} mục hết hạn</td></tr>
            <tr><td>Sổ đối soát</td><td>TTL {fabric.reconcile_ledger?.ttl_seconds}s,{" "}
              chống dội {fabric.reconcile_ledger?.cooldown_seconds}s{" "}
              <span className={"tag "+(fabric.reconcile_ledger?.cluster_wide?"greenTag":"orangeTag")}>
                {fabric.reconcile_ledger?.cluster_wide?"dùng chung":"cục bộ"}</span></td></tr>
          </tbody>
        </table>}
        <p style={{opacity:.8,marginBottom:0}}>
          Mất kết nối không còn là cửa một chiều: pool tự thử lại mỗi {fabric?.retry_seconds||10}s.{" "}
          <button className="ghost" disabled={busy}
            onClick={async()=>{ setBusy(true);
              try{ await apiV26.reconnect(); await load(); }
              catch(e:any){ setErr(e?.message||"Không kết nối lại được Redis"); setBusy(false); } }}>
            Kết nối lại ngay
          </button>
        </p>
      </div>
    </div>

    <div className="panel">
      <div className="panelHead"><b>Đối soát tự động (v25)</b></div>
      <div className="pad">
        <p style={{marginTop:0}}>
          Mỗi lần một worker bám vào phiên (khởi động lại, tiếp quản, đổi chủ lease), hệ thống tự
          ghi khoảng trống rồi hỏi gateway những yêu cầu quyền phát sinh lúc không ai nghe —
          không cần ai bấm nút.{" "}
          <span className={"tag "+(reconcileInfo?.enabled?"greenTag":"orangeTag")}>
            {reconcileInfo?.enabled?"đang bật":"đang tắt"}
          </span>
        </p>
        {reconcileInfo && <p style={{opacity:.8}}>
          Chống dội: {reconcileInfo.cooldown_seconds}s mỗi phiên.{" "}
          {fabric?.reconcile_ledger?.cluster_wide
            ? <>Từ v26 lịch sử và chống dội <b>dùng chung toàn cụm</b>, nên ba worker không còn hỏi
               gateway ba lần trong cùng một cửa sổ.</>
            : <>Không có Redis nên lịch sử dưới đây chỉ của <b>worker này</b>, và mỗi worker có
               cửa sổ chống dội riêng.</>}{" "}
          Dấu vết bền vẫn là sự kiện <code>{reconcileInfo.event_type}</code> trong event bus.
        </p>}
        {(reconcileInfo?.history||[]).length===0 && <p style={{opacity:.7,marginBottom:0}}>
          Worker này chưa chạy lượt đối soát nào.
        </p>}
        {(reconcileInfo?.history||[]).length>0 && <table className="dataTable">
          <thead><tr><th>Session key</th><th>Lý do</th><th>Khoảng trống</th><th>Lấy lại</th><th>Lỗi</th></tr></thead>
          <tbody>
            {reconcileInfo.history.map((h:any)=><tr key={h.session_key+h.at}>
              <td><code>{h.session_key}</code></td>
              <td>{h.reason}{h.skipped && <> <span className="tag orangeTag">{h.skipped}</span></>}</td>
              <td>{h.gap ? <span className="tag redTag">{Math.round((h.gap.gap_seconds||0)/60)} phút</span>
                          : <span style={{opacity:.6}}>không đáng kể</span>}</td>
              <td>{h.backfill?.supported
                    ? <>{(h.backfill.recorded||[]).length} yêu cầu</>
                    : <span className="tag orangeTag">không hỗ trợ</span>}</td>
              <td>{h.error ? <span className="tag redTag">{h.error}</span> : <span style={{opacity:.5}}>—</span>}</td>
            </tr>)}
          </tbody>
        </table>}
      </div>
    </div>

    <div className="panel">
      <div className="panelHead"><b>Khoảng trống quan sát (v24)</b></div>
      <div className="pad">
        <p style={{marginTop:0}}>
          Tiếp quản một phiên <b>không</b> phát lại những gì đã xảy ra lúc không ai theo dõi.
          OpenClaw không replay sự kiện cũ, nên phần đó vĩnh viễn thiếu trong nhật ký công ty —
          hệ thống ghi lại một dấu <code>openclaw.stream.gap</code> để không ai tưởng nhật ký là liền mạch.
        </p>
        {backfillReady && <p style={{opacity:.8}}>
          Lấy lại yêu cầu quyền (<code>{backfillReady.method}</code>):{" "}
          <span className={"tag "+(backfillReady.ready?"greenTag":"orangeTag")}>
            {backfillReady.ready?"sẵn sàng":"chưa dùng được"}
          </span>
          {!backfillReady.ready && <> — thiếu: {backfillReady.missing.join(", ")}</>}
        </p>}
        {gaps.length===0 && <p style={{opacity:.7,marginBottom:0}}>Không có phiên nào đang bỏ trống.</p>}
        {gaps.length>0 && <table className="dataTable">
          <thead><tr><th>Nhiệm vụ</th><th>Session key</th><th>Không quan sát</th><th>Sự kiện cuối</th><th></th></tr></thead>
          <tbody>
            {gaps.map(g=><tr key={g.session_key}>
              <td>{g.title} <span style={{opacity:.6}}>#{g.task_id}</span></td>
              <td><code>{g.session_key}</code></td>
              <td>
                {!g.observed
                  ? <span className="tag orangeTag">chưa từng ghi nhận</span>
                  : <span className={"tag "+(g.significant?"redTag":"greenTag")}>
                      {Math.round((g.gap_seconds||0)/60)} phút
                    </span>}
              </td>
              <td>{g.last_event_at ? new Date(g.last_event_at).toLocaleString() : "—"}</td>
              <td>
                <button className="ghost" onClick={()=>backfill(g.task_id)}
                        disabled={busy || !backfillReady?.ready}>
                  Lấy lại yêu cầu quyền
                </button>{" "}
                {/* v25: ghì cả hai nửa — ghi khoảng trống và lấy lại yêu cầu — trong một lượt,
                    bỏ qua chống dội vì ngưọi bấm biết rõ hơn giới hạn của chúng ta. */}
                <button className="ghost" onClick={()=>reconcileNow(g.task_id)} disabled={busy}>
                  Đối soát lại
                </button>
              </td>
            </tr>)}
          </tbody>
        </table>}
      </div>
    </div>

    <div className="panel">
      <div className="panelHead"><b>Phiên OpenClaw đang mở</b></div>
      <div className="pad">
        <table className="dataTable">
          <thead><tr><th>Session key</th><th>Nhiệm vụ</th><th>Trạng thái</th><th>Lease</th><th>Sự kiện</th><th>Phê duyệt</th><th>Sự kiện cuối</th></tr></thead>
          <tbody>
            {streams.map(s=><tr key={s.session_key}>
              <td><code>{s.session_key}</code></td>
              <td>{s.task_id ?? "—"}</td>
              <td><span className={"tag "+(statusTag[s.status]||"blueTag")}>{s.status}</span>{s.error && <div style={{color:"var(--risk)"}}>{s.error}</div>}</td>
              <td>{s.lease_backend||"—"}</td>
              <td>{s.events}</td>
              <td>{s.approvals}</td>
              <td>{s.last_event_type||"—"}</td>
            </tr>)}
            {!streams.length && <tr><td colSpan={7}>Chưa có phiên nào được theo dõi trong tiến trình này.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>

    <div className="panel">
      <div className="panelHead"><b>Yêu cầu quyền từ gateway</b></div>
      <div className="pad">
        {readiness && !readiness.ready && <p style={{marginTop:0,color:"var(--warn)"}}>
          Quyết định bấm ở đây sẽ được ghi lại nhưng <b>chưa gửi được tới OpenClaw</b>: thiếu {readiness.missing.join(", ")}.
          Tên RPC không được đoán — hãy lấy đúng tên từ tài liệu bản gateway đang dùng.
        </p>}
        {readiness?.ready && <p style={{marginTop:0,fontSize:12,color:"var(--warn)"}}>
          OpenClaw không có trường lý do cho phê duyệt, nên <b>chỉ quyết định được gửi đi</b>; ghi chú chỉ nằm lại trong ClawCompany.
          {" "}Method: <code>{readiness.method}</code> <span className="tag blueTag">{readiness.method_source||"—"}</span>
        </p>}
        <input value={note} onChange={e=>setNote(e.target.value)} placeholder="Ghi chú quyết định (chỉ lưu nội bộ)"
               style={{width:"100%",padding:8,marginBottom:10}} />
        <table className="dataTable">
          <thead><tr><th>#</th><th>Hành động</th><th>Rủi ro</th><th>Khoá chính sách</th><th>Quyết định</th></tr></thead>
          <tbody>
            {approvals.map(a=><tr key={a.id}>
              <td>{a.id}</td><td>{a.action}</td>
              <td><span className={"tag "+(riskTag[a.risk]||"orangeTag")}>{a.risk}</span></td>
              <td><code>{a.policy_key}</code></td>
              <td>
                <button className="darkBtn" onClick={()=>decide(a.id,"approved")} disabled={busy}>Duyệt 1 lần</button>{" "}
                {readiness?.allow_always_enabled && <>
                  <button className="ghost" onClick={()=>decide(a.id,"approved_always")} disabled={busy}
                          title="Tạo standing grant trên máy gateway, gắn với đúng lệnh và thư mục">Luôn cho phép</button>{" "}
                </>}
                <button className="ghost" onClick={()=>decide(a.id,"denied")} disabled={busy}>Từ chối</button>
              </td>
            </tr>)}
            {!approvals.length && <tr><td colSpan={5}>Không có yêu cầu nào đang chờ.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  </div>;
}
