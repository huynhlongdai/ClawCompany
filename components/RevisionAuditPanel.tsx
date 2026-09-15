"use client";
import {useEffect, useState} from "react";
import {apiV30} from "@/lib/api";

// v30 panel. Two things it refuses to blur:
// 1. A guard is either exact (counter) or inherited from v27 (timestamp).
//    The badge says which one this row would get, because only one of them
//    survives two writes inside the same clock tick.
// 2. Reopening a company's board is a batch with a preview, not a side
//    effect of un-archiving the company.
export function RevisionAuditPanel(){
  const [kind,setKind] = useState("project");
  const [id,setId] = useState("");
  const [rev,setRev] = useState<any>();
  const [companyId,setCompanyId] = useState("");
  const [plan,setPlan] = useState<any>();
  const [rows,setRows] = useState<any[]>([]);
  const [cursor,setCursor] = useState<number|undefined>();
  const [next,setNext] = useState<number|undefined>();
  const [msg,setMsg] = useState("");
  const [err,setErr] = useState("");

  async function loadPage(from?:number){
    setErr("");
    try{
      const out = await apiV30.audit({cursor: from, limit: 20});
      setRows(from ? [...rows, ...out.rows] : out.rows);
      setCursor(from);
      setNext(out.next_cursor ?? undefined);
    }catch(e:any){ setErr(String(e?.message||e)); }
  }

  useEffect(()=>{ loadPage(undefined); }, []);

  async function readRevision(){
    setErr(""); setRev(undefined);
    try{ setRev(await apiV30.revision(kind, Number(id))); }
    catch(e:any){ setErr(String(e?.message||e)); }
  }

  async function previewBatch(){
    setErr(""); setMsg("");
    try{ setPlan(await apiV30.batchRestorePreview(Number(companyId))); }
    catch(e:any){ setErr(String(e?.message||e)); }
  }

  async function runBatch(){
    setErr(""); setMsg("");
    try{
      const out = await apiV30.batchRestore(Number(companyId));
      setMsg(`Đã mở lại ${out.restored_count}/${out.recorded_projects} dự án`
        + (out.complete ? "" : ` · ${out.failed.length} lỗi`)
        + (out.company_still_archived ? " · công ty vẫn đang lưu trữ" : ""));
      setPlan(undefined);
      loadPage(undefined);
    }catch(e:any){ setErr(String(e?.message||e)); }
  }

  return (
    <section className="panel">
      <div className="panelHead">
        <b>Revision chính xác và sổ kiểm toán phân trang (v30)</b>
        <span className="tag blueTag">migration 0013</span>
      </div>
      <div className="pad">
        {err && <p className="tag redTag">{err}</p>}
        {msg && <p className="tag greenTag">{msg}</p>}

        <h4>Revision của một hàng</h4>
        <div style={{display:"flex", gap:8, flexWrap:"wrap", alignItems:"center"}}>
          <select value={kind} onChange={e=>setKind(e.target.value)}>
            {["company","department","member","project","task"].map(k=>
              <option key={k} value={k}>{k}</option>)}
          </select>
          <input value={id} onChange={e=>setId(e.target.value)} placeholder="id" style={{width:90}}/>
          <button className="darkBtn" onClick={readRevision} disabled={!id}>Đọc revision</button>
        </div>
        {rev && (
          <table className="dataTable">
            <tbody>
              <tr><td>Token nên dùng</td><td><code>{rev.revision}</code></td></tr>
              <tr><td>Token cũ (v27)</td><td><code>{rev.legacy_revision}</code></td></tr>
              <tr><td>Chế độ</td><td>
                <span className={rev.exact ? "tag greenTag" : "tag orangeTag"}>
                  {rev.exact ? "counter · chính xác" : "timestamp · có thể nhập nhằng"}
                </span>
              </td></tr>
              <tr><td>Ghi chú</td><td>{rev.note}</td></tr>
            </tbody>
          </table>
        )}

        <h4>Mở lại bảng dự án sau khi lưu trữ công ty</h4>
        <div style={{display:"flex", gap:8, alignItems:"center"}}>
          <input value={companyId} onChange={e=>setCompanyId(e.target.value)}
                 placeholder="company id" style={{width:120}}/>
          <button className="ghost" onClick={previewBatch} disabled={!companyId}>Xem trước</button>
          <button className="darkBtn" onClick={runBatch} disabled={!plan}>Mở lại tất cả</button>
        </div>
        {plan && (
          <div>
            <p>{plan.recorded_projects} dự án trong bản ghi lưu trữ ·
              mở lại {plan.will_restore.length} · bỏ qua {plan.will_skip.length}</p>
            {plan.company_still_archived &&
              <p className="tag orangeTag">Công ty vẫn đang lưu trữ — mở lại bảng không mở lại công ty</p>}
            <table className="dataTable">
              <thead><tr><th>Dự án</th><th>Về trạng thái</th><th>Nhiệm vụ mở lại</th></tr></thead>
              <tbody>
                {plan.will_restore.map((p:any)=>(
                  <tr key={p.project_id}>
                    <td>{p.name}</td>
                    <td>{p.restore_to}{p.previous_status_known ? "" : " (không có bản ghi)"}</td>
                    <td>{p.tasks_to_restore}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
        )}

        <h4>Sổ kiểm toán</h4>
        <table className="dataTable">
          <thead><tr><th>Lúc</th><th>Phân loại</th><th>Đối tượng</th><th>Diễn giải</th></tr></thead>
          <tbody>
            {rows.map((r:any)=>(
              <tr key={r.id}>
                <td>{r.occurred_at}</td>
                <td><span className={r.category==="conflict" ? "tag redTag" : "tag blueTag"}>{r.category}</span></td>
                <td>{r.entity_type} #{r.entity_id}</td>
                <td>{r.summary}</td>
              </tr>))}
          </tbody>
        </table>
        <div style={{display:"flex", gap:8, alignItems:"center"}}>
          <button className="ghost" onClick={()=>loadPage(next)} disabled={!next}>Tải thêm</button>
          <span>{next ? `còn nữa (cursor ${next})` : "đã hết lịch sử khớp bộ lọc"}</span>
        </div>
      </div>
    </section>
  );
}
