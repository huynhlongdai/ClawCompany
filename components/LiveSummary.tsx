"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export function LiveSummary(){
  const [data,setData]=useState<any>(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    api.dashboard(1).then(setData).catch(e=>setError(String(e)));
  },[]);
  if(error) return <div style={{fontSize:11,color:"#b42318"}}>API offline — using UI mock data.</div>;
  if(!data) return <div style={{fontSize:11,color:"#667085"}}>Loading API summary…</div>;
  return <div style={{display:"flex",gap:12,fontSize:11,color:"#667085"}}>
    <span>Companies: <b>{data.companies}</b></span>
    <span>Agents: <b>{data.ai_agents}</b></span>
    <span>Projects: <b>{data.projects_active}</b></span>
    <span>Approvals: <b>{data.approvals_pending}</b></span>
  </div>;
}