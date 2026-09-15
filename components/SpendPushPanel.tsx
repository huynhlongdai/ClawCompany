"use client";
import {useEffect, useRef, useState} from "react";
import {apiV35} from "@/lib/api";

type SpendRow = {
  delegation_id:number; title:string; contract_status:string; task_id:number|null;
  max_cost_usd:number; spent_usd:number; remaining_usd:number|null; used_ratio:number|null;
  spend_status:string; usage_rows:number; attributable:boolean;
};

type Frame = {kind:string; cursor:number; count:number; at:string};

const STATUS_TAG:Record<string,string> = {
  within:"greenTag", warning:"orangeTag", over:"redTag",
  unbudgeted:"blueTag", unattributable:"",
};

function money(value:number){
  return `$${(value ?? 0).toFixed(4)}`;
}

/**
 * v35 panel. Two halves, both deliberately loud about their limits:
 * left = delegation budget vs metered spend, right = the SSE live channel.
 * The ceilings printed at the bottom come from /api/v35/coverage, not from
 * this file, so the UI cannot claim more than the API admits.
 */
export function SpendPushPanel(){
  const [rows,setRows] = useState<SpendRow[]>([]);
  const [rollup,setRollup] = useState<any>(null);
  const [coverage,setCoverage] = useState<any>(null);
  const [detail,setDetail] = useState<any>(null);
  const [busy,setBusy] = useState(false);
  const [note,setNote] = useState("");

  const [frames,setFrames] = useState<Frame[]>([]);
  const [cursor,setCursor] = useState(0);
  const [streaming,setStreaming] = useState(false);
  const sourceRef = useRef<EventSource|null>(null);

  async function loadSpend(){
    setBusy(true); setNote("");
    try{
      const [report,total,cover]:any[] = await Promise.all([
        apiV35.spendReport(), apiV35.spendRollup(), apiV35.coverage(),
      ]);
      setRows(report?.contracts ?? []);
      setRollup(total ?? null);
      setCoverage(cover ?? null);
    }catch(err:any){
      setNote(`Không tải được: ${err?.message ?? err}`);
    }finally{ setBusy(false); }
  }

  function stopStream(){
    sourceRef.current?.close();
    sourceRef.current = null;
    setStreaming(false);
  }

  useEffect(()=>{ loadSpend(); return stopStream; },[]);

  async function openDetail(id:number){
    setBusy(true);
    try{ setDetail(await apiV35.spendDetail(id)); }
    catch(err:any){ setNote(`Không mở được chi tiết: ${err?.message ?? err}`); }
    finally{ setBusy(false); }
  }

  async function flag(dryRun:boolean){
    if(!dryRun && !window.confirm(
      "Phát event delegation.budget.overrun cho mọi contract vượt trần?\n" +
      "Việc này KHÔNG chặn công việc, chỉ ghi cờ để người soát xét.")) return;
    setBusy(true); setNote("");
    try{
      const res:any = await apiV35.flagOverruns({dry_run:dryRun});
      const n = (res?.flagged ?? []).length;
      const skipped = (res?.skipped ?? []).length;
      setNote(dryRun
        ? `Thử nghiệm: ${n} contract sẽ bị gắn cờ, ${skipped} đã có cờ từ trước.`
        : `Đã gắn cờ ${n} contract (${skipped} đã có cờ). Không có việc nào bị chặn.`);
      if(!dryRun) loadSpend();
    }catch(err:any){
      setNote(`Gắn cờ thất bại: ${err?.message ?? err}`);
    }finally{ setBusy(false); }
  }

  function startStream(){
    stopStream();
    // Reconnect with the cursor we already hold so nothing is replayed twice
    // and nothing still on disk is skipped.
    const source = apiV35.liveStream(cursor);
    if(!source){ setNote("Trình duyệt không hỗ trợ EventSource."); return; }
    sourceRef.current = source;
    setStreaming(true);
    const push = (kind:string) => (event:MessageEvent) => {
      let body:any = {};
      try{ body = JSON.parse(event.data ?? "{}"); }catch{ body = {}; }
      if(typeof body.cursor === "number") setCursor(body.cursor);
      setFrames(prev => [{
        kind,
        cursor: body.cursor ?? 0,
        count: (body.events ?? []).length,
        at: body.at ?? new Date().toISOString(),
      }, ...prev].slice(0,40));
      if(kind === "closed") stopStream();
    };
    for(const kind of ["snapshot","events","heartbeat","closed"]){
      source.addEventListener(kind, push(kind) as any);
    }
    source.onerror = () => {
      setNote("Kết nối SSE bị ngắt. Bấm mở lại để nối tiếp từ cursor hiện tại.");
      stopStream();
    };
  }

  const over = rows.filter(row => row.spend_status === "over");
  const warn = rows.filter(row => row.spend_status === "warning");

  return <div className="panel pad">
    <div className="panelHead">
      <h3>Ngân sách delegation & kênh live (v35)</h3>
      <div style={{display:"flex",gap:8}}>
        <button className="ghost" onClick={loadSpend} disabled={busy}>Tải lại</button>
        <button className="ghost" onClick={()=>flag(true)} disabled={busy}>Thử gắn cờ</button>
        <button className="darkBtn" onClick={()=>flag(false)} disabled={busy}>Gắn cờ thật</button>
      </div>
    </div>

    {note && <p style={{fontSize:13,marginTop:0}}>{note}</p>}

    {rollup && <div className="kpi4" style={{marginBottom:12}}>
      <div><span>Tổng trần</span><b>{money(rollup.budget_total_usd)}</b></div>
      <div><span>Đã tiêu (quy được)</span><b>{money(rollup.spent_total_usd)}</b></div>
      <div><span>Vượt trần</span><b>{rollup.over_count}</b></div>
      <div><span>Không quy được</span><b>{rollup.unattributable}</b></div>
    </div>}

    <table className="dataTable">
      <thead><tr>
        <th>#</th><th>Contract</th><th>Trần</th><th>Đã tiêu</th><th>Tỷ lệ</th><th>Trạng thái</th><th>Usage</th><th></th>
      </tr></thead>
      <tbody>
        {rows.map(row => <tr key={row.delegation_id}>
          <td>{row.delegation_id}</td>
          <td>{row.title}<div style={{fontSize:11,opacity:.6}}>{row.contract_status}{row.task_id ? ` · task ${row.task_id}` : " · chưa gắn task"}</div></td>
          <td>{row.max_cost_usd > 0 ? money(row.max_cost_usd) : "—"}</td>
          <td>{row.attributable ? money(row.spent_usd) : "—"}</td>
          <td>{row.used_ratio === null ? "—" : `${Math.round(row.used_ratio*100)}%`}</td>
          <td><span className={`tag ${STATUS_TAG[row.spend_status] ?? ""}`}>{row.spend_status}</span></td>
          <td>{row.usage_rows}</td>
          <td><button className="ghost" onClick={()=>openDetail(row.delegation_id)}>Chi tiết</button></td>
        </tr>)}
        {!rows.length && <tr><td colSpan={8} style={{opacity:.6}}>Chưa có delegation contract nào đang mở.</td></tr>}
      </tbody>
    </table>

    {(over.length > 0 || warn.length > 0) && <p style={{fontSize:13}}>
      {over.length} contract đã vượt trần, {warn.length} contract đã dùng quá 80%.
      Vượt trần <b>không chặn</b> công việc đang chạy.
    </p>}

    {detail && <div className="panel pad" style={{marginTop:12}}>
      <div className="panelHead">
        <h4>Contract #{detail.contract?.delegation_id} · {detail.contract?.title}</h4>
        <button className="ghost" onClick={()=>setDetail(null)}>Đóng</button>
      </div>
      <p style={{fontSize:12,opacity:.75,marginTop:0}}>
        Cửa sổ quy chi phí: {detail.contract?.window_start} → {detail.contract?.window_end}.
        Tối đa {detail.usage_events_capped_at} dòng usage.
      </p>
      <table className="dataTable">
        <thead><tr><th>#</th><th>Loại</th><th>SL</th><th>Tiền</th><th>Run</th><th>Lúc</th></tr></thead>
        <tbody>
          {(detail.usage_events ?? []).map((item:any) => <tr key={item.usage_event_id}>
            <td>{item.usage_event_id}</td><td>{item.event_type}</td>
            <td>{item.quantity} {item.unit}</td><td>{money(item.amount)}</td>
            <td>{item.runtime_run_id || "—"}</td><td>{item.created_at ?? "—"}</td>
          </tr>)}
          {!(detail.usage_events ?? []).length && <tr><td colSpan={6} style={{opacity:.6}}>
            Không có dòng usage nào quy được cho contract này.
          </td></tr>}
        </tbody>
      </table>
    </div>}

    <div className="panel pad" style={{marginTop:12}}>
      <div className="panelHead">
        <h4>Kênh live (SSE) · cursor {cursor}</h4>
        <div style={{display:"flex",gap:8}}>
          <button className="ghost" onClick={startStream} disabled={streaming}>Mở kênh</button>
          <button className="ghost" onClick={stopStream} disabled={!streaming}>Đóng kênh</button>
        </div>
      </div>
      <p style={{fontSize:12,opacity:.75,marginTop:0}}>
        {streaming ? "Đang mở một kết nối SSE. Trình duyệt không còn poll."
                   : "Kênh đang đóng. Mở lại sẽ nối tiếp từ cursor hiện tại."}
      </p>
      <table className="dataTable">
        <thead><tr><th>Frame</th><th>Cursor</th><th>Số event</th><th>Lúc</th></tr></thead>
        <tbody>
          {frames.map((item,index) => <tr key={`${item.at}-${index}`}>
            <td><span className={`tag ${item.kind === "closed" ? "orangeTag" : item.kind === "events" ? "greenTag" : "blueTag"}`}>{item.kind}</span></td>
            <td>{item.cursor}</td><td>{item.count}</td><td>{item.at}</td>
          </tr>)}
          {!frames.length && <tr><td colSpan={4} style={{opacity:.6}}>Chưa có frame nào.</td></tr>}
        </tbody>
      </table>
    </div>

    {coverage && <div style={{marginTop:12,fontSize:12,opacity:.8,lineHeight:1.6}}>
      <b>Giới hạn do API tự khai:</b>
      <div>• Chi phí quy theo <code>{coverage.spend_attribution?.basis}</code>; usage_events không có cột delegation_id;
        không phải chi phí runner báo về; <b>không chặn</b> trước khi dispatch.</div>
      <div>• Kênh live là <code>{coverage.live_channel?.transport}</code>, chưa có WebSocket.
        Bỏ poll ở trình duyệt nhưng server vẫn poll DB mỗi {coverage.live_channel?.server_poll_seconds}s.
        Nối lại chỉ lấy được event còn trong {coverage.live_channel?.replay_limited_by_retention_days} ngày retention.
        Chưa từng quan sát trên môi trường thật.</div>
    </div>}
  </div>;
}
