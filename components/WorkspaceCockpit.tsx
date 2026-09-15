"use client";
import {useEffect, useState} from "react";
import {apiV17} from "../lib/api";

type Row = Record<string, any>;
type Tab = "home" | "companies" | "people" | "agents" | "projects" | "tasks" | "knowledge";

const TABS: [Tab, string][] = [
  ["home","Trang chủ"],["companies","Công ty"],["people","Nhân sự"],["agents","AI Agents"],
  ["projects","Dự án"],["tasks","Nhiệm vụ"],["knowledge","Kiến thức"],
];

function Tag({value}:{value?:string|null}){
  const v=(value||"").toLowerCase();
  const cls = /active|done|completed|healthy|indexed/.test(v) ? "tag greenTag"
    : /planning|pending|review|in_progress|backlog/.test(v) ? "tag orangeTag"
    : /risk|failed|blocked|denied/.test(v) ? "tag redTag" : "tag blueTag";
  return <span className={cls}>{value||"—"}</span>;
}

function Bar({value}:{value:number}){
  return <div style={{background:"rgba(0,0,0,.08)",borderRadius:99,height:6,width:120}}>
    <div style={{width:`${Math.max(0,Math.min(100,value))}%`,height:6,borderRadius:99,background:"#1f6feb"}}/>
  </div>;
}

export function WorkspaceCockpit(){
  const [tab,setTab]=useState<Tab>("home");
  const [overview,setOverview]=useState<Row|null>(null);
  const [chart,setChart]=useState<Row|null>(null);
  const [people,setPeople]=useState<Row[]>([]);
  const [agents,setAgents]=useState<Row[]>([]);
  const [projects,setProjects]=useState<Row[]>([]);
  const [tasks,setTasks]=useState<Row[]>([]);
  const [docs,setDocs]=useState<Row[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);

  async function load(){
    setBusy(true); setError("");
    try{
      const [o,c,h,a,p,t,k]=await Promise.all([
        apiV17.overview(), apiV17.orgChart(), apiV17.people("human"), apiV17.people("agent"),
        apiV17.projects(), apiV17.tasks(), apiV17.knowledge(),
      ]);
      setOverview(o); setChart(c); setPeople(h||[]); setAgents(a||[]);
      setProjects(p||[]); setTasks(t||[]); setDocs(k||[]);
    }catch(e:any){ setError(e?.message||"Không tải được dữ liệu workspace"); }
    finally{ setBusy(false); }
  }
  useEffect(()=>{ load(); },[]);

  const k=overview?.kpis||{};
  const companies:Row[]=overview?.companies||[];

  return <div>
    {error && <div className="v8Card" style={{borderColor:"#b4453f"}}>{error} — đăng nhập lại hoặc kiểm tra API.</div>}

    <section className="v14Hero">
      <div>
        <h2>{overview?.organization?.name||"Workspace"}</h2>
        <p>Toàn bộ số liệu trên màn hình này lấy trực tiếp từ API <code>/api/v17/workspace/*</code> — không còn dữ liệu demo.</p>
      </div>
      <button className="v8Ghost" onClick={load} disabled={busy}>{busy?"Đang tải…":"Làm mới"}</button>
    </section>

    <nav style={{display:"flex",gap:8,flexWrap:"wrap",margin:"12px 0"}}>
      {TABS.map(([id,label])=>
        <button key={id} className="v8Ghost" onClick={()=>setTab(id)}
          style={tab===id?{borderColor:"#1f6feb",color:"#1f6feb",fontWeight:600}:undefined}>{label}</button>)}
    </nav>

    {tab==="home" && <>
      <section className="v14Metrics">
        {[["Công ty",k.companies],["Nhân sự",k.members],["Human",k.humans],["AI Agents",k.agents],
          ["Dự án đang chạy",k.projects_active],["Khách hàng",k.customers],
          ["Chờ phê duyệt",k.approvals_pending],["Tài liệu",k.knowledge_documents]].map(([l,v])=>
          <div key={String(l)} className="v8Card"><small>{l}</small><b>{v??0}</b></div>)}
      </section>
      <section className="v13Split">
        <div className="v8Card">
          <h3>Các công ty con</h3>
          <table className="v14Table"><thead><tr><th>Công ty</th><th>Ngành</th><th>Nhân sự</th><th>Agents</th><th>Dự án</th></tr></thead>
            <tbody>{companies.map(c=><tr key={c.id}><td>{c.name}</td><td>{c.industry||"—"}</td><td>{c.members}</td><td>{c.agents}</td><td>{c.projects}</td></tr>)}
              {!companies.length && <tr><td colSpan={5}>Chưa có công ty nào.</td></tr>}</tbody></table>
        </div>
        <div className="v8Card">
          <h3>Sơ đồ tổ chức</h3>
          {(chart?.companies||[]).map((c:Row)=>
            <div key={c.id} style={{marginBottom:10}}>
              <b>{c.name}</b> <small>{c.industry}</small>
              <ul style={{margin:"4px 0 0 16px"}}>
                {(c.departments||[]).map((d:Row)=><li key={d.id}>{d.name} · {d.members?.length||0} thành viên</li>)}
                {!!(c.unassigned_members||[]).length && <li>Chưa xếp phòng · {c.unassigned_members.length}</li>}
              </ul>
            </div>)}
          {!chart && <p>Đang tải sơ đồ…</p>}
        </div>
      </section>
    </>}

    {tab==="companies" && <section className="v8Card">
      <h3>Công ty</h3>
      <table className="v14Table"><thead><tr><th>Tên</th><th>Ngành</th><th>Trạng thái</th><th>Nhân sự</th><th>Agents</th><th>Dự án</th></tr></thead>
        <tbody>{companies.map(c=><tr key={c.id}><td>{c.name}</td><td>{c.industry||"—"}</td><td><Tag value={c.status}/></td><td>{c.members}</td><td>{c.agents}</td><td>{c.projects}</td></tr>)}</tbody></table>
    </section>}

    {(tab==="people"||tab==="agents") && <section className="v8Card">
      <h3>{tab==="people"?"Nhân sự (human)":"AI Agents"}</h3>
      <table className="v14Table">
        <thead><tr><th>Tên</th><th>Vai trò</th><th>Công ty</th><th>Phòng ban</th>{tab==="agents"&&<><th>Model</th><th>Thành công</th><th>Chi phí 30d</th></>}<th>Trạng thái</th></tr></thead>
        <tbody>{(tab==="people"?people:agents).map(m=><tr key={m.id}>
          <td>{m.name}</td><td>{m.role||"—"}</td><td>{m.company_name||"—"}</td><td>{m.department_name||"—"}</td>
          {tab==="agents"&&<><td>{m.agent?.model||"—"}</td><td>{m.agent?`${Math.round((m.agent.success_rate||0)*100)}%`:"—"}</td><td>{m.agent?`$${m.agent.cost_30d}`:"—"}</td></>}
          <td><Tag value={m.status}/></td></tr>)}
          {!(tab==="people"?people:agents).length && <tr><td colSpan={8}>Chưa có dữ liệu.</td></tr>}</tbody></table>
    </section>}

    {tab==="projects" && <section className="v8Card">
      <h3>Dự án</h3>
      <table className="v14Table"><thead><tr><th>Dự án</th><th>Công ty</th><th>Tiến độ</th><th>Nhiệm vụ</th><th>Trạng thái</th></tr></thead>
        <tbody>{projects.map(p=><tr key={p.id}><td>{p.name}</td><td>{p.company_name||"—"}</td>
          <td><Bar value={p.progress||0}/> {p.progress||0}%</td>
          <td>{p.tasks_done}/{p.tasks_total}</td><td><Tag value={p.status}/></td></tr>)}
          {!projects.length && <tr><td colSpan={5}>Chưa có dự án.</td></tr>}</tbody></table>
    </section>}

    {tab==="tasks" && <section className="v8Card">
      <h3>Nhiệm vụ</h3>
      <table className="v14Table"><thead><tr><th>Nhiệm vụ</th><th>Dự án</th><th>Người/Agent</th><th>Ưu tiên</th><th>Trạng thái</th></tr></thead>
        <tbody>{tasks.map(t=><tr key={t.id}><td>{t.title}</td><td>{t.project_name||"—"}</td>
          <td>{t.assignee_name||"—"}{t.assignee_type==="agent"?" ✦":""}</td><td>{t.priority}</td><td><Tag value={t.status}/></td></tr>)}
          {!tasks.length && <tr><td colSpan={5}>Chưa có nhiệm vụ.</td></tr>}</tbody></table>
    </section>}

    {tab==="knowledge" && <section className="v8Card">
      <h3>Kiến thức</h3>
      <table className="v14Table"><thead><tr><th>Tài liệu</th><th>Công ty</th><th>Nguồn</th><th>Mức truy cập</th><th>Đã index</th></tr></thead>
        <tbody>{docs.map(d=><tr key={d.id}><td>{d.title}</td><td>{d.company_name||"—"}</td><td>{d.source_type}</td><td>{d.access_level}</td><td>{d.indexed?"Có":"Chưa"}</td></tr>)}
          {!docs.length && <tr><td colSpan={5}>Chưa có tài liệu.</td></tr>}</tbody></table>
    </section>}
  </div>;
}
