"use client";
import {useEffect,useState} from "react";

const API_BASE=process.env.NEXT_PUBLIC_API_BASE||"http://localhost:8000/api";

type PortalData={
  user:{display_name:string,email:string};
  customer:{name:string,plan:string,usage_percent:number};
  agents:{agent_id:number;name:string;role:string;status:string}[];
  projects:{id:number;name:string;status:string;progress:number;visibility:string}[];
  subscription?:{plan:string;mrr:number;status:string;renewal_date:string};
  usage:{events:number;quantity:number;cost:number;by_type:Record<string,number>};
};

async function fetchPortal(token:string){
  const r=await fetch(`${API_BASE}/portal/me`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

export function CustomerPortal(){
  const [token,setToken]=useState<string|null>(null);
  const [email,setEmail]=useState("client@acme.local");
  const [password,setPassword]=useState("ChangeMe123!");
  const [data,setData]=useState<PortalData|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{const t=localStorage.getItem("clawcompany_portal_token");if(t){setToken(t);fetchPortal(t).then(setData).catch(()=>localStorage.removeItem("clawcompany_portal_token"));}},[]);
  async function login(){
    setError("");
    const r=await fetch(`${API_BASE}/portal/auth/login`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})});
    if(!r.ok){setError(await r.text());return;}
    const j=await r.json();localStorage.setItem("clawcompany_portal_token",j.access_token);setToken(j.access_token);setData(await fetchPortal(j.access_token));
  }
  if(!token||!data) return <div className="portalLogin"><div className="portalLoginCard"><div className="portalBrand"><div className="brandMark"/><div><b>ClawCompany</b><span>Customer Portal</span></div></div><h1>Đăng nhập workspace</h1><p>Trao đổi với AI team, theo dõi project, report và usage.</p><input value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email"/><input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Password"/>{error&&<div className="portalError">{error}</div>}<button onClick={login}>Đăng nhập</button></div></div>;
  return <div className="portalShell">
    <aside className="portalSide"><div className="portalBrand"><div className="brandMark"/><div><b>ClawCompany</b><span>Customer Portal</span></div></div><nav><button className="active">⌂ Overview</button><button>✦ AI Team</button><button>▣ Projects</button><button onClick={()=>location.href="/portal/chat"}>◌ Conversations</button><button>▥ Reports</button><button>▤ Files</button><button>◎ Usage</button></nav><div className="portalCustomer"><small>WORKSPACE</small><b>{data.customer.name}</b><span>{data.customer.plan}</span></div></aside>
    <main className="portalMain"><header><div><small>Good morning,</small><h1>{data.user.display_name||data.customer.name} 👋</h1></div><div className="portalTop"><span>{data.subscription?.status||"Active"}</span><button onClick={()=>{localStorage.removeItem("clawcompany_portal_token");location.reload()}}>Đăng xuất</button></div></header>
      <section className="portalHero"><div><span className="portalPill">AI TEAM ACTIVE</span><h2>Your AI workforce is working.</h2><p>Theo dõi tiến độ, chat với AI employee và duyệt các đề xuất trong cùng workspace.</p></div><div className="portalUsage"><small>Monthly usage</small><strong>{data.customer.usage_percent}%</strong><div><i style={{width:`${data.customer.usage_percent}%`}}/></div><span>AI internal cost ${data.usage.cost.toFixed(2)}</span></div></section>
      <div className="portalGrid"><section className="portalCard"><div className="portalCardHead"><b>Your AI Team</b><span>{data.agents.length} employees</span></div>{data.agents.map(a=><div className="portalAgent" key={a.name}><div className="portalAvatar">{a.name[0]}</div><div><b>{a.name}</b><span>{a.role}</span></div><em>● {a.status}</em><button onClick={()=>location.href=`/portal/chat?agent=${a.agent_id}`}>Chat</button></div>)}</section><section className="portalCard"><div className="portalCardHead"><b>Plan & Usage</b><span>{data.subscription?.plan}</span></div><div className="portalKV"><span>Monthly plan</span><b>${data.subscription?.mrr||0}/mo</b></div><div className="portalKV"><span>Usage events</span><b>{data.usage.events}</b></div><div className="portalKV"><span>Renewal</span><b>{data.subscription?.renewal_date||"—"}</b></div><div className="portalKV"><span>Status</span><b>{data.subscription?.status||"active"}</b></div></section></div>
      <section className="portalCard portalProjects"><div className="portalCardHead"><b>Active Projects</b><span>Customer-visible projects only</span></div>{data.projects.length===0?<div className="portalEmpty">Chưa có project được chia sẻ.</div>:data.projects.map(p=><div className="portalProject" key={p.id}><div><b>{p.name}</b><span>{p.status}</span></div><div className="portalProgress"><i style={{width:`${p.progress}%`}}/></div><strong>{p.progress}%</strong><button>Open</button></div>)}</section>
    </main>
  </div>
}
