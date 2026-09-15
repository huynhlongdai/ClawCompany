"use client";
import {useEffect, useState} from "react";
import {apiV28} from "@/lib/api";

// v28 panel. Two jobs: rename a project through a *binding* guard, and undo
// an archive. The revision is never held in a hidden field across a session
// -- it is re-read right before the write, because a stale token in a form is
// exactly the bug this version exists to surface.
export function BoardGuardPanel({projects}:{projects:any[]}){
  const [projectId,setProjectId] = useState<number|undefined>();
  const [guards,setGuards] = useState<any>();
  const [history,setHistory] = useState<any>();
  const [name,setName] = useState("");
  const [msg,setMsg] = useState("");
  const [err,setErr] = useState("");
  const [busy,setBusy] = useState(false);

  useEffect(()=>{ apiV28.guards().then(setGuards).catch(()=>{}); },[]);
  useEffect(()=>{ if(projectId) load(); },[projectId]);

  async function load(){
    if(!projectId) return;
    try{ setHistory(await apiV28.history(projectId)); }catch(e:any){ setErr(e?.message||"Không đọc được"); }
  }

  async function run(label:string, fn:()=>Promise<any>){
    setBusy(true); setErr(""); setMsg("");
    try{
      const out = await fn();
      // A 409 here is the feature working: the row moved before our write
      // landed. Report it as a conflict to resolve, not as a failure.
      setMsg(`${label}: ${JSON.stringify(out).slice(0,220)}`);
      await load();
    }catch(e:any){ setErr(`${label}: ${e?.message||"lỗi"}`); }
    finally{ setBusy(false); }
  }

  const restore = history?.restore;
  const truth = history?.truth;

  return <div className="panel">
    <div className="panelHead pad">
      <b>Ghi có bảo vệ &amp; hoàn tác lưu trữ (v28)</b>
      <span style={{opacity:.6}}>{guardSummary(guards)}</span>
    </div>
    <div className="pad" style={{display:"flex",gap:8,flexWrap:"wrap",alignItems:"center"}}>
      <select value={projectId??""} onChange={e=>setProjectId(e.target.value?Number(e.target.value):undefined)}>
        <option value="">— chọn dự án —</option>
        {projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <input placeholder="Tên mới của dự án" value={name} onChange={e=>setName(e.target.value)}/>
      <button className="darkBtn" disabled={busy||!projectId||!name}
        onClick={()=>run("Đổi tên có bảo vệ", async ()=>{
          const fresh = await apiV28.history(projectId!);
          return apiV28.guardedProject(projectId!, fresh.truth.revision, {name});
        })}>Ghi có bảo vệ</button>
      <button className="ghost" disabled={busy||!restore?.is_archived}
        onClick={()=>run("Hoàn tác lưu trữ",()=>apiV28.restore(projectId!))}>Hoàn tác lưu trữ</button>
    </div>

    {truth && <table className="dataTable">
      <thead><tr><th>Revision hiện tại</th><th>Đang lưu trữ</th><th>Trạng thái cũ</th><th>Nhiệm vụ sẽ mở lại</th><th>Sẽ bỏ qua</th></tr></thead>
      <tbody><tr>
        <td><code>{truth.revision}</code></td>
        <td>{restore?.is_archived ? <span className="tag orangeTag">có</span> : <span className="tag greenTag">không</span>}</td>
        <td>{restore?.previous_status}{restore?.previous_status_known ? "" : " (không có trong bản ghi cũ)"}</td>
        <td>{restore?.will_restore_tasks?.length ?? 0}</td>
        <td>{restore?.will_skip_tasks?.length ?? 0}</td>
      </tr></tbody>
    </table>}

    {restore && restore.is_archived && restore.archive_event_id===null &&
      <div className="pad" style={{opacity:.75}}>
        Dự án đang ở trạng thái lưu trữ nhưng không có bản ghi lưu trữ nào, nên không
        thể biết đã huỷ những nhiệm vụ nào. Phải mở lại từng nhiệm vụ bằng tay.
      </div>}

    {restore?.will_skip_tasks?.length ? <div className="pad" style={{opacity:.75}}>
      Những nhiệm vụ đã được người khác chuyển trạng thái sau khi lưu trữ sẽ được giữ nguyên.
    </div> : null}

    {msg && <div className="pad" style={{opacity:.8}}>{msg}</div>}
    {err && <div className="pad" style={{color:"var(--risk)"}}>{err}</div>}
  </div>;
}

function guardSummary(guards:any){
  if(!guards) return "";
  const n = Object.keys(guards.writable||{}).length;
  return `${n} loại thực thể · revision bắt buộc`;
}
