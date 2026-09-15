const API_BASE=process.env.NEXT_PUBLIC_API_BASE||"http://localhost:8000/api";
export type Session={token:string;organizationId:number|null;role:string};

export async function login(email:string,password:string,organizationId?:number):Promise<Session>{
  const res=await fetch(`${API_BASE}/auth/login`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password,organization_id:organizationId})});
  if(!res.ok) throw new Error(await res.text());
  const data=await res.json();
  if(typeof window!=="undefined") localStorage.setItem("clawcompany_token",data.access_token);
  return {token:data.access_token,organizationId:data.organization_id,role:data.role};
}

export function token(){return typeof window==="undefined"?null:localStorage.getItem("clawcompany_token");}
export function logout(){if(typeof window!=="undefined") localStorage.removeItem("clawcompany_token");}

export async function apiFetch(path:string,init:RequestInit={}){
  const t=token();
  const res=await fetch(`${API_BASE}${path}`,{...init,headers:{"Content-Type":"application/json",...(t?{Authorization:`Bearer ${t}`}:{ }),...(init.headers||{})}});
  if(!res.ok) throw new Error(await res.text());
  return res.json();
}

export function activeOrganizationId(fallback=1){
  const t=token();
  if(!t) return fallback;
  try{
    const payload=JSON.parse(atob(t.split(".")[1].replace(/-/g,"+").replace(/_/g,"/")));
    return Number(payload.org_id)||fallback;
  }catch{return fallback;}
}
