"use client";
import {useEffect, useState} from "react";
import {apiV29} from "@/lib/api";

type Kind = "companies"|"departments"|"members";
const LABEL: Record<Kind,string> = {
  companies: "Công ty",
  departments: "Phòng ban",
  members: "Nhân sự / agent",
};

// v29 panel. The rule here is that nothing archives without the operator
// having seen the blast radius first: a company archive touches departments,
// members and the whole board, and a member may be holding a live OpenClaw
// session. "Force" is offered, but it never claims to have stopped anything
// inside the runtime -- it lists what it left running.
export function EntityArchivePanel(){
  const [kind,setKind] = useState<Kind>("members");
  const [id,setId] = useState<string>("");
  const [preview,setPreview] = useState<any>();
  const [restore,setRestore] = useState<any>();
  const [audit,setAudit] = useState<any>();
  const [onlyConflicts,setOnlyConflicts] = useState(false);
  const [msg,setMsg] = useState("");
  const [err,setErr] = useState("");
  const [busy,setBusy] = useState(false);

  useEffect(()=>{ loadAudit(); },[onlyConflicts]);

  async function loadAudit(){
    try{
      setAudit(await apiV29.audit({limit:12, category: onlyConflicts?["conflict"]:undefined}));
    }catch(e:any){ setErr(e?.message||"Không đọc được sổ kiểm toán"); }
  }

  async function look(){
    const n = Number(id);
    if(!n) return;
    setBusy(true); setErr(""); setMsg(""); setPreview(undefined); setRestore(undefined);
    try{
      setPreview(await apiV29.archivePreview(kind, n));
      setRestore(await apiV29.restorePreview(kind, n));
    }catch(e:any){ setErr(e?.message||"lỗi"); }
    finally{ setBusy(false); }
  }

  async function run(label:string, fn:()=>Promise<any>){
    setBusy(true); setErr(""); setMsg("");
    try{
      const out = await fn();
      setMsg(`${label}: ${JSON.stringify(out).slice(0,240)}`);
      await look(); await loadAudit();
    }catch(e:any){ setErr(`${label}: ${e?.message||"lỗi"}`); }
    finally{ setBusy(false); }
  }

  const n = Number(id)||0;
  const blocked = !!preview?.blocked;
  const counts = preview?.counts;

  return <div className="panel">
    <div className="panelHead pad">
      <b>Lưu trữ dây chuyền &amp; sổ kiểm toán (v29)</b>
      <span style={{opacity:.6}}>không xoá dòng nào</span>
    </div>

    <div className="pad" style={{display:"grid", gap:10}}>
      <div style={{display:"flex", gap:8, flexWrap:"wrap", alignItems:"center"}}>
        <select value={kind} onChange={e=>{setKind(e.target.value as Kind); setPreview(undefined); setRestore(undefined);}}>
          {(Object.keys(LABEL) as Kind[]).map(k=><option key={k} value={k}>{LABEL[k]}</option>)}
        </select>
        <input placeholder="ID" value={id} onChange={e=>setId(e.target.value)} style={{width:90}}/>
        <button className="ghost" disabled={busy||!n} onClick={look}>Xem trước ảnh hưởng</button>
      </div>

      {preview && <div style={{display:"grid", gap:6}}>
        <div>
          <b>{preview.name}</b>{" "}
          <span className={preview.already_archived?"tag orangeTag":"tag greenTag"}>
            {preview.already_archived?"đã lưu trữ":"đang hoạt động"}
          </span>
        </div>
        {counts && <div style={{opacity:.8}}>
          Sẽ ảnh hưởng: {counts.departments} phòng ban · {counts.members} nhân sự · {counts.projects} dự án ·{" "}
          {counts.agents} agent giữ nguyên đăng ký
        </div>}
        {blocked && <div className="tag redTag">
          {preview.live_runtime_sessions.length} phiên OpenClaw đang chạy — hãy dừng qua /api/v19/tasks/&#123;id&#125;/abort,
          hoặc bấm “Lưu trữ cưỡng chế” (phiên vẫn chạy, hệ thống chỉ ghi lại).
        </div>}
        <div style={{display:"flex", gap:8, flexWrap:"wrap"}}>
          <button className="darkBtn" disabled={busy||preview.already_archived}
            onClick={()=>run("Lưu trữ", ()=>apiV29.archive(kind, n, false))}>Lưu trữ</button>
          <button className="ghost" disabled={busy||!blocked}
            onClick={()=>run("Lưu trữ cưỡng chế", ()=>apiV29.archive(kind, n, true))}>Lưu trữ cưỡng chế</button>
          <button className="ghost" disabled={busy||!preview.already_archived}
            onClick={()=>run("Hoàn tác lưu trữ", ()=>apiV29.restore(kind, n))}>Hoàn tác lưu trữ</button>
        </div>
        {restore && preview.already_archived && <div style={{opacity:.8}}>
          Khi hoàn tác: trả về “{restore.restore_to}”
          {restore.prior_state_known ? " (theo trạng thái đã ghi)" : " (không có bản ghi cũ — dùng mặc định)"};
          {" "}{restore.will_restore_members?.length||0} nhân sự sẽ được phục hồi.
          {(restore.projects_restored_separately?.length||0)>0 &&
            ` ${restore.projects_restored_separately.length} dự án phải mở lại riêng bằng v28.`}
        </div>}
      </div>}

      {msg && <div style={{opacity:.85}}>{msg}</div>}
      {err && <div className="tag redTag">{err}</div>}
    </div>

    <div className="panelHead pad">
      <b>Sổ ghi có bảo vệ</b>
      <label style={{display:"flex", gap:6, alignItems:"center", opacity:.8}}>
        <input type="checkbox" checked={onlyConflicts} onChange={e=>setOnlyConflicts(e.target.checked)}/>
        chỉ xem xung đột
      </label>
    </div>
    <table className="dataTable">
      <thead><tr><th>Thời điểm</th><th>Loại</th><th>Đối tượng</th><th>Diễn giải</th></tr></thead>
      <tbody>
        {(audit?.rows||[]).map((r:any)=><tr key={r.id}>
          <td>{(r.occurred_at||"").replace("T"," ").slice(0,16)}</td>
          <td><span className={r.category==="conflict"?"tag redTag":r.category==="archive"?"tag orangeTag":"tag blueTag"}>{r.category}</span></td>
          <td>{r.entity_type} #{r.entity_id}</td>
          <td>{r.summary}</td>
        </tr>)}
        {!(audit?.rows||[]).length && <tr><td colSpan={4} style={{opacity:.6}}>Chưa có bản ghi nào.</td></tr>}
      </tbody>
    </table>
    {audit?.truncated && <div className="pad" style={{opacity:.6}}>
      Chỉ hiển thị {audit.returned} bản ghi mới nhất — sổ còn dài hơn.
    </div>}
  </div>;
}
