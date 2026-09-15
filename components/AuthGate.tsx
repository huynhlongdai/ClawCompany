"use client";
import {useEffect,useState} from "react";
import {login,token} from "../lib/auth";

export function AuthGate({children}:{children:React.ReactNode}){
  const required=process.env.NEXT_PUBLIC_AUTH_REQUIRED==="true";
  const [authed,setAuthed]=useState(!required);
  useEffect(()=>{if(required && token()) setAuthed(true)},[required]);
  const [email,setEmail]=useState("admin@clawcompany.local");
  const [password,setPassword]=useState("ChangeMe123!");
  const [error,setError]=useState("");
  if(authed) return <>{children}</>;
  return <div style={{minHeight:"100vh",display:"grid",placeItems:"center",background:"#f6f8fc"}}>
    <div style={{width:360,background:"#fff",border:"1px solid #e8edf5",borderRadius:18,padding:24,boxShadow:"0 20px 50px rgba(15,23,42,.08)"}}>
      <div style={{fontWeight:800,fontSize:20}}>ClawCompany</div>
      <div style={{color:"#667085",fontSize:12,marginTop:4}}>Đăng nhập vào AI Organization OS</div>
      <input value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email" style={{width:"100%",marginTop:18,height:40,border:"1px solid #e8edf5",borderRadius:10,padding:"0 12px"}}/>
      <input value={password} onChange={e=>setPassword(e.target.value)} type="password" placeholder="Password" style={{width:"100%",marginTop:10,height:40,border:"1px solid #e8edf5",borderRadius:10,padding:"0 12px"}}/>
      {error&&<div style={{fontSize:11,color:"#b42318",marginTop:8}}>{error}</div>}
      <button onClick={async()=>{try{await login(email,password);setAuthed(true)}catch(e){setError(String(e))}}} style={{width:"100%",marginTop:14,height:40,border:0,borderRadius:10,color:"#fff",background:"linear-gradient(135deg,#715cff,#8a76ff)",fontWeight:700}}>Đăng nhập</button>
    </div>
  </div>
}
