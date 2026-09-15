"use client";
import {useEffect,useState} from "react";
import {activeOrganizationId} from "../lib/auth";
import {apiV11} from "../lib/api";
type Any=Record<string,any>;
export function RepositoryRegistryConsole(){
 const [items,setItems]=useState<Any[]>([]),[selected,setSelected]=useState<Any|null>(null),[error,setError]=useState("");
 const [name,setName]=useState("nova-product"),[project,setProject]=useState("");
 const load=async()=>{try{const data=await apiV11.repositories() as Any[];setItems(data);setError("");if(data[0]&&!selected)setSelected(await apiV11.repository(data[0].id) as Any)}catch(e:any){setError(e.message)}};
 useEffect(()=>{load()},[]);
 const create=async()=>{try{await apiV11.createRepository({organization_id:activeOrganizationId(),name,provider:"local",default_branch:"main",project_id:project?Number(project):null,initialize:true});await load()}catch(e:any){setError(e.message)}};
 const inspect=async(id:number)=>{try{setSelected(await apiV11.repository(id) as Any)}catch(e:any){setError(e.message)}};
 return <><div className="v11Flow"><span>Artifact Bundle</span><i>→</i><b>Repository Registry</b><i>→</i><b>Isolated Worktree</b><i>→</i><span>Commit Agent</span></div>
 <div className="v10Grid"><section className="v8Card"><div className="v8CardHead"><div><b>Register repository</b><small>Local Git works immediately. GitHub/generic remotes stay behind provider credentials.</small></div></div><div className="v9Form"><label>Name<input value={name} onChange={e=>setName(e.target.value)}/></label><label>Project ID (optional)<input value={project} onChange={e=>setProject(e.target.value)}/></label><button className="v8Primary" onClick={create}>Create & initialize</button></div>{error&&<div className="portalError">{error}</div>}</section>
 <section className="v8Card"><div className="v8CardHead"><div><b>Repository state</b><small>Exact branch, head SHA and clean/dirty state from Git.</small></div></div>{selected?<div className="v11RepoState"><b>{selected.repository?.name}</b><span>{selected.repository?.provider}</span><code>{selected.state?.path||"not initialized"}</code><div><small>Branch</small><strong>{selected.state?.branch||"—"}</strong></div><div><small>HEAD</small><strong>{String(selected.state?.head||"—").slice(0,12)}</strong></div><div><small>Status</small><strong>{selected.state?.status||"clean"}</strong></div></div>:<div className="v8Empty">Select a repository</div>}</section></div>
 <section className="v8Card"><div className="v8CardHead"><div><b>Repository Registry</b><small>Tenant-bound repositories and delivery targets</small></div></div><div className="v11RepoTable"><div className="v11RepoHead"><span>Name</span><span>Provider</span><span>Branch</span><span>Status</span><span/></div>{items.map(x=><div className="v11RepoRow" key={x.id}><b>{x.name}</b><span>{x.provider}</span><code>{x.default_branch}</code><em>{x.status}</em><button onClick={()=>inspect(x.id)}>Inspect</button></div>)}</div></section></>
}
