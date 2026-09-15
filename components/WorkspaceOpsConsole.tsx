"use client";
import {useEffect, useState} from "react";
import {BoardTruthPanel} from "@/components/BoardTruthPanel";
import {BoardGuardPanel} from "@/components/BoardGuardPanel";
import {RevisionAuditPanel} from "@/components/RevisionAuditPanel";
import {FieldHistoryPanel} from "@/components/FieldHistoryPanel";
import {HousekeepingPanel} from "@/components/HousekeepingPanel";
import {RecoveryPanel} from "@/components/RecoveryPanel";
import {ReplayPanel} from "@/components/ReplayPanel";
import {SpendPushPanel} from "@/components/SpendPushPanel";
import {apiV17, apiV18} from "@/lib/api";

type Vocab = {
  company_statuses:string[]; member_statuses:string[]; project_statuses:string[];
  task_statuses:string[]; task_priorities:string[]; access_levels:string[];
  task_transitions:Record<string,string[]>;
};

function Field({label,children}:{label:string;children:any}){
  return <label style={{display:"block",marginBottom:10}}>
    <span style={{display:"block",fontSize:12,opacity:.7,marginBottom:4}}>{label}</span>
    {children}
  </label>;
}

export function WorkspaceOpsConsole(){
  const [vocab,setVocab] = useState<Vocab|null>(null);
  const [companies,setCompanies] = useState<any[]>([]);
  const [people,setPeople] = useState<any[]>([]);
  const [projects,setProjects] = useState<any[]>([]);
  const [tasks,setTasks] = useState<any[]>([]);
  const [error,setError] = useState("");
  const [note,setNote] = useState("");
  const [busy,setBusy] = useState(false);

  // form state
  const [company,setCompany] = useState({name:"",industry:"",status:"active"});
  const [dept,setDept] = useState({company_id:0,name:"",access_level:"restricted"});
  const [member,setMember] = useState({name:"",member_type:"human",company_id:0,role:"",runtime_agent_id:"",model:""});
  const [project,setProject] = useState({company_id:0,name:"",description:"",owner_member_id:0});
  const [task,setTask] = useState({project_id:0,title:"",priority:"medium",assignee_member_id:0});

  async function reload(){
    try{
      const [v,ov,pe,pr,tk] = await Promise.all([
        apiV18.vocabulary(), apiV17.overview(), apiV17.people(), apiV17.projects(), apiV17.tasks(),
      ]);
      setVocab(v as Vocab);
      setCompanies((ov as any).companies || []);
      setPeople(pe as any[]); setProjects(pr as any[]); setTasks(tk as any[]);
      setError("");
    }catch(e:any){ setError(e?.message || "Không tải được dữ liệu workspace"); }
  }
  useEffect(()=>{ reload(); },[]);

  // Every mutation goes through here so one failure path is surfaced, never swallowed.
  async function run(label:string, fn:()=>Promise<any>){
    setBusy(true); setNote(""); setError("");
    try{ await fn(); setNote(`${label} thành công`); await reload(); }
    catch(e:any){ setError(e?.message || `${label} thất bại`); }
    finally{ setBusy(false); }
  }

  const nz = (v:number) => (v ? v : undefined);

  return <div style={{display:"grid",gap:16}}>
    {error && <div className="panel pad" style={{borderColor:"#b4453f",color:"#b4453f"}}>{error}</div>}
    {note && <div className="panel pad" style={{borderColor:"#2f7d52",color:"#2f7d52"}}>{note}</div>}

    <div className="companyGrid">
      <div className="panel pad">
        <div className="panelHead"><b>Lập công ty</b></div>
        <Field label="Tên công ty"><input value={company.name} onChange={e=>setCompany({...company,name:e.target.value})}/></Field>
        <Field label="Ngành"><input value={company.industry} onChange={e=>setCompany({...company,industry:e.target.value})}/></Field>
        <Field label="Trạng thái">
          <select value={company.status} onChange={e=>setCompany({...company,status:e.target.value})}>
            {(vocab?.company_statuses||["active"]).map(s=><option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <button className="darkBtn" disabled={busy||!company.name} onClick={()=>run("Tạo công ty",()=>apiV18.createCompany(company))}>Tạo công ty</button>
      </div>

      <div className="panel pad">
        <div className="panelHead"><b>Lập phòng ban</b></div>
        <Field label="Công ty">
          <select value={dept.company_id} onChange={e=>setDept({...dept,company_id:Number(e.target.value)})}>
            <option value={0}>— chọn —</option>
            {companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Tên phòng ban"><input value={dept.name} onChange={e=>setDept({...dept,name:e.target.value})}/></Field>
        <Field label="Mức truy cập">
          <select value={dept.access_level} onChange={e=>setDept({...dept,access_level:e.target.value})}>
            {(vocab?.access_levels||["restricted"]).map(s=><option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <button className="darkBtn" disabled={busy||!dept.company_id||!dept.name} onClick={()=>run("Tạo phòng ban",()=>apiV18.createDepartment(dept))}>Tạo phòng ban</button>
      </div>

      <div className="panel pad">
        <div className="panelHead"><b>Tuyển nhân sự / đăng ký agent</b></div>
        <Field label="Loại">
          <select value={member.member_type} onChange={e=>setMember({...member,member_type:e.target.value})}>
            <option value="human">Người</option>
            <option value="agent">AI Agent</option>
          </select>
        </Field>
        <Field label="Tên"><input value={member.name} onChange={e=>setMember({...member,name:e.target.value})}/></Field>
        <Field label="Công ty">
          <select value={member.company_id} onChange={e=>setMember({...member,company_id:Number(e.target.value)})}>
            <option value={0}>— chưa gán —</option>
            {companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Vai trò"><input value={member.role} onChange={e=>setMember({...member,role:e.target.value})}/></Field>
        {member.member_type==="agent" && <>
          <Field label="runtime_agent_id (bắt buộc với agent)">
            <input value={member.runtime_agent_id} onChange={e=>setMember({...member,runtime_agent_id:e.target.value})} placeholder="oc-nina"/>
          </Field>
          <Field label="Model"><input value={member.model} onChange={e=>setMember({...member,model:e.target.value})} placeholder="openclaw-core"/></Field>
        </>}
        <button className="darkBtn" disabled={busy||!member.name||(member.member_type==="agent"&&!member.runtime_agent_id)}
          onClick={()=>run("Tạo nhân sự",()=>apiV18.createMember({...member,company_id:nz(member.company_id)}))}>Thêm vào tổ chức</button>
      </div>

      <div className="panel pad">
        <div className="panelHead"><b>Mở dự án</b></div>
        <Field label="Công ty">
          <select value={project.company_id} onChange={e=>setProject({...project,company_id:Number(e.target.value)})}>
            <option value={0}>— chọn —</option>
            {companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Tên dự án"><input value={project.name} onChange={e=>setProject({...project,name:e.target.value})}/></Field>
        <Field label="Chủ dự án">
          <select value={project.owner_member_id} onChange={e=>setProject({...project,owner_member_id:Number(e.target.value)})}>
            <option value={0}>— chưa gán —</option>
            {people.map(p=><option key={p.id} value={p.id}>{p.name} · {p.member_type}</option>)}
          </select>
        </Field>
        <button className="darkBtn" disabled={busy||!project.company_id||!project.name}
          onClick={()=>run("Tạo dự án",()=>apiV18.createProject({...project,owner_member_id:nz(project.owner_member_id)}))}>Tạo dự án</button>
      </div>
    </div>

    <div className="panel pad">
      <div className="panelHead"><b>Giao nhiệm vụ</b></div>
      <div className="companyGrid">
        <Field label="Dự án">
          <select value={task.project_id} onChange={e=>setTask({...task,project_id:Number(e.target.value)})}>
            <option value={0}>— chọn —</option>
            {projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Tiêu đề"><input value={task.title} onChange={e=>setTask({...task,title:e.target.value})}/></Field>
        <Field label="Ưu tiên">
          <select value={task.priority} onChange={e=>setTask({...task,priority:e.target.value})}>
            {(vocab?.task_priorities||["medium"]).map(s=><option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Người/agent thực hiện">
          <select value={task.assignee_member_id} onChange={e=>setTask({...task,assignee_member_id:Number(e.target.value)})}>
            <option value={0}>— chưa gán —</option>
            {people.map(p=><option key={p.id} value={p.id}>{p.name} · {p.member_type}</option>)}
          </select>
        </Field>
      </div>
      <button className="darkBtn" disabled={busy||!task.project_id||!task.title}
        onClick={()=>run("Tạo nhiệm vụ",()=>apiV18.createTask({...task,assignee_member_id:nz(task.assignee_member_id)}))}>Tạo nhiệm vụ</button>
    </div>

    <BoardTruthPanel projects={projects}/>

    <BoardGuardPanel projects={projects}/>
    <RevisionAuditPanel/>
    <FieldHistoryPanel/>
      <HousekeepingPanel/>
      <RecoveryPanel/>
      <ReplayPanel/>
      <SpendPushPanel/>

    <div className="panel">
      <div className="panelHead pad"><b>Hàng đợi nhiệm vụ</b><span style={{opacity:.6}}>{tasks.length} mục</span></div>
      <table className="dataTable">
        <thead><tr><th>Nhiệm vụ</th><th>Dự án</th><th>Phụ trách</th><th>Trạng thái</th><th>Chuyển sang</th></tr></thead>
        <tbody>
          {tasks.map((t:any)=>{
            const next = vocab?.task_transitions?.[t.status] || [];
            return <tr key={t.id}>
              <td>{t.title}</td>
              <td>{t.project_name || t.project_id}</td>
              <td>{t.assignee_name || "—"}</td>
              <td><span className="tag blueTag">{t.status}</span></td>
              <td style={{display:"flex",gap:6,flexWrap:"wrap"}}>
                {/* Only legal transitions are rendered; the server re-checks anyway. */}
                {next.length===0 ? <i style={{opacity:.5}}>không còn bước</i> :
                  next.map(s=><button key={s} className="ghost" disabled={busy}
                    onClick={()=>run(`Chuyển "${t.title}" → ${s}`,()=>apiV18.moveTask(t.id,s))}>{s}</button>)}
              </td>
            </tr>;
          })}
          {tasks.length===0 && <tr><td colSpan={5} style={{opacity:.6}}>Chưa có nhiệm vụ nào.</td></tr>}
        </tbody>
      </table>
    </div>
  </div>;
}
