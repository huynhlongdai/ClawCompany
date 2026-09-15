"use client";
import {useState} from "react";
import {apiV27} from "@/lib/api";

// v27: the project progress column stopped being a number somebody typed.
// This panel shows what the board says, the drift against the stored value,
// and what archiving would cancel -- before anything is written.
export function BoardTruthPanel({projects}:{projects:any[]}){
  const [projectId,setProjectId] = useState(0);
  const [truth,setTruth] = useState<any>(null);
  const [preview,setPreview] = useState<any>(null);
  const [msg,setMsg] = useState("");
  const [err,setErr] = useState("");
  const [busy,setBusy] = useState(false);

  async function run(label:string, fn:()=>Promise<any>){
    setBusy(true); setErr(""); setMsg("");
    try {
      const out = await fn();
      setMsg(label + " ✓");
      return out;
    } catch(e:any){
      // A 409 here is the feature working, not a crash: it means somebody
      // else edited the row, or a live OpenClaw session is still attached.
      setErr(label + ": " + (e?.message || String(e)));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function load(){
    if(!projectId) return;
    const t = await run("Đọc sự thật bảng", ()=>apiV27.truth(projectId));
    if(t) setTruth(t);
    const p = await run("Xem trước lưu trữ", ()=>apiV27.archivePreview(projectId));
    if(p) setPreview(p);
  }

  async function sync(){
    if(!truth) return;
    // Send the revision we read with, so a stale tab cannot overwrite a
    // newer edit. The 409 carries the current revision.
    const out = await run("Đồng bộ tiến độ", ()=>apiV27.syncProgress(projectId, truth.revision));
    if(out) setTruth(out);
  }

  async function archive(force:boolean){
    const out = await run(force ? "Lưu trữ (ép)" : "Lưu trữ dự án",
      ()=>apiV27.archive(projectId, truth?.revision, force));
    if(out) await load();
  }

  return <div className="panel">
    <div className="panelHead pad">
      <b>Sự thật bảng dự án (v27)</b>
      <span style={{opacity:.6}}>tiến độ suy từ nhiệm vụ · khoá lạc quan · lưu trữ có dây chuyền</span>
    </div>
    <div className="pad" style={{display:"grid",gap:10}}>
      <div style={{display:"flex",gap:8,alignItems:"center",flexWrap:"wrap"}}>
        <select value={projectId} onChange={e=>{setProjectId(Number(e.target.value)); setTruth(null); setPreview(null);}}>
          <option value={0}>— chọn dự án —</option>
          {projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button className="ghost" disabled={busy||!projectId} onClick={load}>Đọc</button>
        <button className="darkBtn" disabled={busy||!truth?.derivable||truth?.drift===0} onClick={sync}>Đồng bộ tiến độ</button>
      </div>

      {err && <div style={{color:"#b4453f"}}>{err}</div>}
      {msg && !err && <div style={{color:"#2f7d52"}}>{msg}</div>}

      {truth && <table className="dataTable">
        <tbody>
          <tr><td>Tiến độ suy từ bảng</td><td>
            {truth.derivable
              ? <b>{truth.derived_progress}%</b>
              : <span className="tag orangeTag">chưa đo được</span>}
          </td></tr>
          <tr><td>Tiến độ đang lưu</td><td>{truth.stored_progress}%</td></tr>
          <tr><td>Lệch</td><td>
            {truth.drift === null
              ? <span style={{opacity:.6}}>không có nhiệm vụ nào để đếm — không suy ra 0%</span>
              : <span className={truth.drift === 0 ? "tag greenTag" : "tag orangeTag"}>
                  {truth.drift > 0 ? "+" : ""}{truth.drift}
                </span>}
          </td></tr>
          <tr><td>Đã xong / đếm được</td><td>{truth.complete} / {truth.countable} (bỏ {truth.excluded} đã huỷ)</td></tr>
          <tr><td>Revision</td><td><code>{truth.revision}</code></td></tr>
        </tbody>
      </table>}

      {truth && !truth.derivable && <div style={{opacity:.7,fontSize:13}}>
        Dự án chưa có nhiệm vụ nào đếm được. Hệ thống <b>không</b> ghi 0% lên cột:
        “không có gì để đo” và “đo được 0” là hai câu khác nhau.
      </div>}

      {preview && <div style={{borderTop:"1px solid #e6ddcd",paddingTop:10}}>
        <div style={{marginBottom:6}}><b>Lưu trữ sẽ làm gì</b></div>
        <table className="dataTable">
          <tbody>
            <tr><td>Huỷ nhiệm vụ còn mở</td><td>{preview.will_cancel_tasks}</td></tr>
            <tr><td>Giữ nguyên nhiệm vụ đã xong</td><td>{preview.will_keep_done_tasks}</td></tr>
            <tr><td>Xoá dữ liệu</td><td><span className="tag greenTag">không — chỉ chuyển trạng thái</span></td></tr>
            <tr><td>Phiên OpenClaw đang chạy</td><td>
              {preview.live_runtime_sessions?.length
                ? <span className="tag redTag">{preview.live_runtime_sessions.length} phiên đang bám</span>
                : <span className="tag greenTag">không có</span>}
            </td></tr>
          </tbody>
        </table>
        {preview.live_runtime_sessions?.length > 0 && <div style={{opacity:.75,fontSize:13,marginTop:6}}>
          Lưu trữ bị chặn: huỷ nhiệm vụ đang chạy sẽ để agent chạy tiếp bên trong OpenClaw
          mà không còn ai ghi nhận. Hãy dừng ở <code>/api/v19/tasks/&#123;id&#125;/abort</code>,
          hoặc ép lưu trữ và chấp nhận các phiên đó vẫn chạy.
        </div>}
        <div style={{display:"flex",gap:8,marginTop:8}}>
          <button className="darkBtn" disabled={busy||preview.blocked||preview.already_archived} onClick={()=>archive(false)}>Lưu trữ dự án</button>
          {preview.blocked && <button className="ghost" disabled={busy} onClick={()=>archive(true)}>Ép lưu trữ (để phiên chạy tiếp)</button>}
        </div>
      </div>}
    </div>
  </div>;
}
