"use client";

import { useEffect, useMemo, useState } from "react";
import { menuGroups, specs, ModuleSpec } from "./data";
import { api } from "../lib/api";

type Row = (string|number)[];

function Status({value}:{value:string}) {
  const v=value.toLowerCase();
  const cls = v.includes("healthy") || v.includes("active") || v.includes("online") || v.includes("ready") || v.includes("approved") || v.includes("success") || v.includes("on track") || v.includes("good")
    ? "tag greenTag"
    : v.includes("attention") || v.includes("pending") || v.includes("review") || v.includes("busy") || v.includes("planning") || v.includes("trial") || v.includes("near")
    ? "tag orangeTag"
    : v.includes("high") || v.includes("denied") || v.includes("failed") || v.includes("risk")
    ? "tag redTag"
    : "tag blueTag";
  return <span className={cls}>{value}</span>;
}

function Dashboard() {
  const [ninaInput,setNinaInput]=useState("");
  const [ninaReply,setNinaReply]=useState("Chào Long! 👋 Hôm nay tôi có thể giúp gì cho bạn?");
  const [ninaBusy,setNinaBusy]=useState(false);
  async function askNina(message?:string){
    const text=(message||ninaInput).trim();
    if(!text) return;
    setNinaBusy(true);
    try{const result:any=await api.ninaCommand(text,1);setNinaReply(result.message||"Đã xử lý.");setNinaInput("");}
    catch{setNinaReply("Nina API đang offline — dashboard vẫn dùng dữ liệu mẫu.");}
    finally{setNinaBusy(false);}
  }
  return (
    <div className="pageGrid">
      <div>
        <div className="panel hero">
          <div className="heroCopy">
            <div className="eyebrow">Chào mừng trở lại,</div>
            <h1>Long 👋</h1>
            <p>Cùng AI xây dựng những điều lớn lao hơn.</p>
            <div className="quote">“A great company is a group of great minds, human and AI, working toward a meaningful future.”</div>
            <div className="heroActions"><button className="darkBtn" onClick={()=>window.location.href="/app/nina"}>Nói chuyện với Nina →</button><button className="ghost" onClick={()=>window.location.href="/app/control-center"}>Xem báo cáo hôm nay</button></div>
          </div>
          <div className="heroArt">
            <div className="ninaNote">“ Biến ý tưởng thành hành động, cùng nhau. ”</div>
            <div className="portrait"></div>
            <div className="signature"><b>Nina</b><small>Your AI Chief of Staff<br/>Always by your side.</small></div>
          </div>
        </div>
        <div className="metric5">
          {[
            ["Doanh thu (tháng)","$42,380","+12%","▥"],
            ["Dự án đang chạy","27","+3","▣"],
            ["AI Agents","86","+6","✦"],
            ["Nhân sự (Human)","12","+2","◫"],
            ["Khách hàng","38","+5","♧"],
          ].map(([l,v,d,i])=><div className="metric" key={l}><div className="metricIcon">{i}</div><label>{l}</label><strong>{v}</strong><span>{d}</span></div>)}
        </div>
        <div className="panel pad orgPanel">
          <div className="panelHead">
            <div><b>Tổ chức của bạn</b><span className="muted">Nova Holding › Tổng quan tổ chức và các công ty con</span></div>
            <div className="actions"><button className="ghost">⌘ Xem sơ đồ đầy đủ</button><button className="ghost">Quản lý</button><button className="darkBtn">＋ Thêm công ty</button></div>
          </div>
          <div className="holdingTree">
            <div className="rootNode"><div className="crown">♛</div><b>NOVA HOLDING</b><small>Long (Founder & CEO)<br/>4 công ty con · 243 thành viên</small></div>
            <div className="hLine"/><div className="vLine"/>
            <div className="companyGrid">
              {[
                ["👗","Nova Fashion","Thời trang nữ","42 members","pink"],
                ["▶","Nova Media","Nội dung & Truyền thông","36 members","blue"],
                ["⚗","Nova Labs","AI Products","27 members","violet"],
                ["🛒","Nova Commerce","E-commerce","31 members","green"],
              ].map(([ic,n,k,m,c])=><div className="companyCard" key={n}><div className="companyTop"><div className={`companyLogo ${c}`}>{ic}</div><div><b>{n}</b><small>{k}</small></div></div><div className="companyMeta"><div className="faces"><i/><i/><i/></div><span>{m}</span></div></div>)}
            </div>
          </div>
        </div>
        <div className="lowerGrid">
          <div className="panel pad">
            <div className="panelHead"><b>Dự án gần đây</b><a>Xem tất cả →</a></div>
            <table className="dataTable"><thead><tr><th>Tên dự án</th><th>Công ty</th><th>Tiến độ</th><th>Trạng thái</th><th>Hạn chót</th></tr></thead>
            <tbody>
              {[
                ["Launch Gen Z Beauty Brand","Nova Fashion","78%","On track","30/09/2026"],
                ["AI Video Content Factory","Nova Media","45%","On track","15/09/2026"],
                ["E-commerce Growth Q4","Nova Commerce","60%","Pending","10/10/2026"],
                ["OpenClaw Tools Marketplace","Nova Labs","20%","Planning","31/12/2026"],
              ].map(r=><tr key={r[0]}><td><b>{r[0]}</b></td><td>{r[1]}</td><td><div className="progress"><span style={{width:r[2]}}/></div></td><td><Status value={r[3]}/></td><td>{r[4]}</td></tr>)}
            </tbody></table>
          </div>
          <div className="panel pad">
            <div className="panelHead"><b>AI Agents</b><a>Xem tất cả →</a></div>
            <div className="agentList">
              {[
                ["N","Nina","Chief of Staff","Online"],["A","Alex","CTO","Working"],["S","Sophia","CMO","Online"],
                ["M","Mia","Content Lead","Busy"],["L","Leo","Market Researcher","Online"],["K","Ken","AI Engineer","Working"],
              ].map(([i,n,r,s])=><div className="agentRow" key={n}><div className="person"><div className="avatarSm">{i}</div><div><b>{n}</b><small>{r}</small></div></div><Status value={s}/></div>)}
            </div>
          </div>
        </div>
      </div>
      <aside className="rightRail">
        <div className="panel pad">
          <div className="panelHead"><b>Nhiệm vụ của bạn</b><a>Xem tất cả →</a></div>
          <div className="tabsCompact"><span className="active">Cần duyệt (5)</span><span>Quan trọng (3)</span><span>Hôm nay (12)</span></div>
          {[
            ["Phê duyệt ngân sách quảng cáo Q4","Nova Fashion · 2 giờ trước","High"],
            ["Duyệt chiến dịch TikTok mới","Nova Media · 5 giờ trước","High"],
            ["Xem báo cáo tài chính tháng 8","Nova Holding · 1 ngày trước","Medium"],
            ["Phê duyệt tuyển dụng AI Engineer","Nova Labs · 1 ngày trước","Medium"],
            ["Xem proposal hợp tác với đối tác","Nova Commerce · 2 ngày trước","Low"],
          ].map(([t,s,p])=><div className="railItem" key={t}><div><b>{t}</b><small>{s}</small></div><Status value={p}/></div>)}
        </div>
        <div className="panel pad">
          <div className="panelHead"><b>Lịch hôm nay</b><a>Xem lịch →</a></div>
          <div className="timeline">
            {[
              ["09:00","Họp chiến lược cùng Nina"],["10:30","Review báo cáo Nova Fashion"],["13:00","Demo AI Video Project"],["15:00","Gặp đối tác"],["17:00","Tổng kết ngày"]
            ].map(([time,t])=><div className="timeRow" key={time}><span>{time}</span><div><i/><b>{t}</b></div></div>)}
          </div>
        </div>
        <div className="panel pad">
          <div className="ninaHead"><div className="person"><div className="avatarSm">N</div><div><b>Nina</b><small className="online">● Online</small></div></div><span>↗︎ ⋮</span></div>
          <div className="chatBubble">{ninaReply}</div>
          <div className="quickButtons">{["Báo cáo hôm nay","Tình hình các công ty","Dự án đang chạy","Các phê duyệt","Tìm nhân sự AI"].map(x=><button onClick={()=>askNina(x)} key={x}>{x}</button>)}</div>
          <div className="composer"><input value={ninaInput} onChange={e=>setNinaInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter")askNina()}} placeholder="Hỏi Nina bất cứ điều gì..."/><button onClick={()=>askNina()}>{ninaBusy?"…":"➜"}</button></div>
        </div>
      </aside>
    </div>
  );
}

function OrgMapPage(){
  return <div>
    <PageHeader title="Org Map" description="Visualize toàn bộ quan hệ human + AI và reporting line." action="Chỉnh sơ đồ"/>
    <div className="panel pad">
      <div className="orgTree">
        <div className="orgNode"><b>Long</b><small>CEO · Human</small></div>
        <div className="orgLine"/>
        <div className="orgNode"><b>Nina</b><small>Chief of Staff · AI</small></div>
        <div className="orgBranches">
          {[
            ["Sophia","CMO","Mia · Content Lead","Leo · Researcher"],
            ["Alex","CTO","Ken · AI Engineer","Tom · Designer"],
            ["Emma","COO","David · Ops","Riko · Data Analyst"],
          ].map(x=><div className="orgBranch" key={x[0]}><div className="orgNode"><b>{x[0]}</b><small>{x[1]} · AI</small></div><div className="orgSub"><div className="orgNode miniNode">{x[2]}</div><div className="orgNode miniNode">{x[3]}</div></div></div>)}
        </div>
      </div>
    </div>
  </div>
}

function TasksPage(){
  return <div>
    <PageHeader title="Nhiệm vụ" description="Business task board, review, dependencies và OpenClaw execution mapping." action="New Task"/>
    <div className="kanban">
      {[
        ["Backlog · 6",[["Research Gen Z trends","Leo · Strategy"],["Create mood board","Mia · Brand"]]],
        ["Running · 4",[["Create 20 TikTok hooks","Mia · OpenClaw #182"],["Generate image variations","Creative Agent"]]],
        ["Review · 3",[["Review final videos","Sophia · CMO"],["Check brand compliance","QA Agent"]]],
        ["Done · 8",[["Trend research","Leo"],["Competitor analysis","Research Team"]]],
      ].map(([title,items]:any)=><div className="kanCol" key={title}><h4>{title}</h4>{items.map((it:any)=><div className="taskCard" key={it[0]}><b>{it[0]}</b><small>{it[1]}</small><div className="taskMeta"><span>Task</span><span>⋯</span></div></div>)}</div>)}
    </div>
  </div>
}

function PageHeader({title,description,action}:{title:string;description:string;action:string}){
  return <div className="pageHeader"><div><h2>{title}</h2><p>{description}</p></div><div className="headerActions"><button className="ghost">Filter</button><button className="primary">＋ {action}</button></div></div>
}

function GenericModule({spec}:{spec:ModuleSpec}){
  const [tab,setTab]=useState(spec.tabs[0]);
  const [query,setQuery]=useState("");
  const [selected,setSelected]=useState(0);
  const rows=spec.rows.filter(r=>r.join(" ").toLowerCase().includes(query.toLowerCase()));
  return <div>
    <PageHeader title={spec.title} description={spec.description} action={spec.action}/>
    <div className="moduleTabs">{spec.tabs.map(t=><button className={tab===t?"active":""} onClick={()=>setTab(t)} key={t}>{t}</button>)}</div>
    <div className="kpi4">{spec.kpis.map(k=><div className="kpiCard" key={k.label}><small>{k.label}</small><strong>{k.value}</strong>{k.delta&&<span>{k.delta}</span>}</div>)}</div>
    <div className="moduleShell">
      <div>
        <div className="panel pad tablePanel">
          <div className="tableToolbar"><div><b>{tab}</b><span>{rows.length} records</span></div><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Tìm trong module..."/></div>
          <div className="tableWrap"><table className="dataTable"><thead><tr>{spec.columns.map(c=><th key={c}>{c}</th>)}</tr></thead>
          <tbody>{rows.map((r,ri)=><tr className={selected===ri?"selected":""} onClick={()=>setSelected(ri)} key={ri}>{r.map((cell,ci)=><td key={ci}>{ci===0?<b>{cell}</b>:(ci===r.length-1?<Status value={String(cell)}/>:cell)}</td>)}</tr>)}</tbody>
          </table></div>
        </div>
        {spec.features && <div className="panel pad featuresPanel"><div className="panelHead"><b>Chức năng module</b><span className="muted">Functional scope</span></div><div className="featureGrid">{spec.features.map(f=><div className="featureItem" key={f}><i>✓</i><span>{f}</span></div>)}</div></div>}
      </div>
      <aside className="panel pad inspector">
        <div className="inspectorTop"><div className="avatarLg">{spec.inspectorTitle?.[0] || spec.title[0]}</div><div><b>{spec.inspectorTitle || "Inspector"}</b><small>Detail & actions</small></div></div>
        <div className="divider"/>
        {(spec.inspector||[]).map(([k,v])=><div className="kv" key={k}><span>{k}</span><b>{v}</b></div>)}
        <div className="divider"/>
        <div className="inspectorActions"><button className="primary">Open detail</button><button className="ghost">⋯</button></div>
      </aside>
    </div>
  </div>
}

export function ClawCompanyApp(){
  const [page,setPage]=useState("dashboard");
  const [cmdOpen,setCmdOpen]=useState(false);
  const [createOpen,setCreateOpen]=useState(false);

  useEffect(()=>{
    const fn=(e:KeyboardEvent)=>{
      if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="k"){e.preventDefault();setCmdOpen(v=>!v)}
      if(e.key==="Escape"){setCmdOpen(false);setCreateOpen(false)}
    };
    window.addEventListener("keydown",fn); return()=>window.removeEventListener("keydown",fn);
  },[]);

  const flat=useMemo(()=>menuGroups.flatMap(g=>g.items),[]);

  let view:React.ReactNode;
  if(page==="dashboard") view=<Dashboard/>;
  else if(page==="org") view=<OrgMapPage/>;
  else if(page==="tasks") view=<TasksPage/>;
  else view=<GenericModule spec={specs[page] || specs.companies}/>;

  return <div className="appShell">
    <aside className="sidebar">
      <div className="brand"><div className="brandMark"/><div><div className="brandName">ClawCompany</div><small>AI Organization OS</small></div></div>
      {menuGroups.map(g=><div className="menuGroup" key={g.label}><div className="menuLabel">{g.label}</div>{g.items.map(i=><button key={i.key} className={`navItem ${page===i.key?"active":""}`} onClick={()=>setPage(i.key)}><span className="navIcon">{i.icon}</span><span>{i.label}</span>{i.badge&&<em>{i.badge}</em>}</button>)}</div>)}
      <div className="sidebarBottom">
        <div className="companySwitcher"><div className="crown">♛</div><div><b>NOVA HOLDING</b><small>4 công ty con · 243 thành viên</small></div></div>
        <button className="switchBtn">◌ Chuyển công ty</button>
        <div className="profile"><div className="avatarSm">L</div><div><b>Long</b><small>Founder & CEO</small></div></div>
      </div>
    </aside>
    <main className="main">
      <header className="topbar">
        <button className="searchBox" onClick={()=>setCmdOpen(true)}>⌕ <span>Tìm kiếm anything... (agents, projects, tài liệu, người...)</span><kbd>⌘ K</kbd></button>
        <div className="topActions"><button className="primary" onClick={()=>setCreateOpen(v=>!v)}>＋ Tạo mới</button><button className="iconBtn">◔</button><span>Thứ Tư, 9 Tháng 9, 2026</span><b>11:22</b><span>☼</span></div>
        {createOpen&&<div className="createMenu">
          {["Công ty","Phòng ban","AI Employee","Project","Task","Document","Customer","Workflow"].map(x=><button key={x}>＋ {x}</button>)}
        </div>}
      </header>
      <div className="content">{view}</div>
    </main>

    {cmdOpen&&<div className="overlay" onClick={()=>setCmdOpen(false)}>
      <div className="command" onClick={e=>e.stopPropagation()}>
        <div className="commandSearch">⌕ <input autoFocus placeholder="Đi tới module hoặc hỏi Nina..."/></div>
        <div className="commandHint">NAVIGATE</div>
        {flat.slice(0,16).map(i=><button onClick={()=>{setPage(i.key);setCmdOpen(false)}} key={i.key}><span>{i.icon}</span><span>{i.label}</span><kbd>↵</kbd></button>)}
      </div>
    </div>}
  </div>
}