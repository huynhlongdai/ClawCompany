"use client";
import {useEffect,useState} from "react";
import {apiV16} from "../lib/api";
type Any=Record<string,any>;

export function KnowledgeMeshConsole(){
  const [spaces,setSpaces]=useState<Any[]>([]);
  const [spaceId,setSpaceId]=useState<number|null>(null);
  const [grants,setGrants]=useState<Any[]>([]);
  const [logs,setLogs]=useState<Any[]>([]);
  const [memberId,setMemberId]=useState("");
  const [permission,setPermission]=useState<Any|null>(null);
  const [query,setQuery]=useState("");
  const [hits,setHits]=useState<Any[]>([]);
  const [error,setError]=useState("");

  async function load(){
    setError("");
    try{
      const s:any = await apiV16.spaces();
      const list = Array.isArray(s)?s:(s?.spaces||[]);
      setSpaces(list);
      if(list.length && spaceId===null) setSpaceId(list[0].id);
      const l:any = await apiV16.accessLogs();
      setLogs(Array.isArray(l)?l:(l?.logs||[]));
    }catch(e:any){ setError(e?.message||"Không tải được knowledge mesh"); }
  }
  useEffect(()=>{ load(); },[]);
  useEffect(()=>{ if(spaceId==null) return;
    apiV16.grants(spaceId).then((g:any)=>setGrants(Array.isArray(g)?g:(g?.grants||[]))).catch(()=>setGrants([]));
  },[spaceId]);

  async function checkPermission(){
    if(spaceId==null||!memberId) return;
    try{ setPermission(await apiV16.permission(spaceId, Number(memberId)) as Any); }
    catch(e:any){ setError(e?.message||"Không kiểm tra được quyền"); }
  }
  async function runSearch(){
    if(!memberId) { setError("Nhập member_id để tìm theo đúng quyền của agent đó"); return; }
    try{
      const r:any = await apiV16.search({query, member_id:Number(memberId), space_id:spaceId||undefined});
      setHits(Array.isArray(r)?r:(r?.results||[]));
    }catch(e:any){ setError(e?.message||"Tìm kiếm thất bại"); }
  }

  const space = spaces.find(s=>s.id===spaceId);
  return <div>
    {error && <div className="v8Card" style={{borderColor:"#b4453f"}}>{error}</div>}
    <section className="v14Hero">
      <div>
        <h2>Shared Knowledge Mesh</h2>
        <p>Tri thức dùng chung deny-by-default: mọi lượt đọc/đóng góp đều đi qua quyền hiệu lực và được ghi nhật ký.</p>
      </div>
      <button className="v8Ghost" onClick={load}>Làm mới</button>
    </section>

    <section className="v13Split">
      <div className="v8Card">
        <h3>Không gian tri thức</h3>
        <table className="v14Table"><thead><tr><th>Tên</th><th>Phân loại</th><th>Mặc định</th><th></th></tr></thead>
          <tbody>{spaces.map(s=><tr key={s.id} style={s.id===spaceId?{fontWeight:600}:undefined}>
            <td>{s.name}</td><td>{s.classification}</td><td>{s.default_permission}</td>
            <td><button className="v8Ghost" onClick={()=>setSpaceId(s.id)}>Chọn</button></td></tr>)}
            {!spaces.length && <tr><td colSpan={4}>Chưa có không gian nào.</td></tr>}</tbody></table>
      </div>
      <div className="v8Card">
        <h3>Grants {space?`· ${space.name}`:""}</h3>
        <table className="v14Table"><thead><tr><th>Đối tượng</th><th>ID</th><th>Quyền</th><th>Hết hạn</th></tr></thead>
          <tbody>{grants.map(g=><tr key={g.id}><td>{g.grantee_type}</td><td>{g.grantee_id}</td><td>{g.permission}</td><td>{g.expires_at||"—"}</td></tr>)}
            {!grants.length && <tr><td colSpan={4}>Chưa cấp quyền nào — mặc định là từ chối.</td></tr>}</tbody></table>
      </div>
    </section>

    <section className="v8Card">
      <h3>Kiểm tra quyền & tìm kiếm theo danh tính agent</h3>
      <div style={{display:"flex",gap:8,flexWrap:"wrap",alignItems:"center"}}>
        <input placeholder="member_id" value={memberId} onChange={e=>setMemberId(e.target.value)}/>
        <button className="v8Ghost" onClick={checkPermission}>Quyền hiệu lực</button>
        <input placeholder="từ khoá" value={query} onChange={e=>setQuery(e.target.value)}/>
        <button className="v8Ghost" onClick={runSearch}>Tìm trong mesh</button>
        {permission && <span className="tag blueTag">{permission.permission||permission.effective_permission||"none"}</span>}
      </div>
      <table className="v14Table"><thead><tr><th>Tiêu đề</th><th>Không gian</th><th>Phiên bản</th><th>Nguồn</th></tr></thead>
        <tbody>{hits.map((h,i)=><tr key={h.id||i}><td>{h.title}</td><td>{h.space_id}</td><td>v{h.version||1}</td><td>{h.source_type||"—"}</td></tr>)}
          {!hits.length && <tr><td colSpan={4}>Chưa có kết quả.</td></tr>}</tbody></table>
    </section>

    <section className="v8Card">
      <h3>Nhật ký truy cập</h3>
      <table className="v14Table"><thead><tr><th>Thời điểm</th><th>Member</th><th>Không gian</th><th>Hành động</th><th>Kết quả</th></tr></thead>
        <tbody>{logs.slice(0,25).map((l,i)=><tr key={l.id||i}><td>{l.created_at||"—"}</td><td>{l.member_id}</td><td>{l.space_id}</td><td>{l.action}</td><td>{l.allowed===false?"Từ chối":"Cho phép"}</td></tr>)}
          {!logs.length && <tr><td colSpan={5}>Chưa có lượt truy cập nào.</td></tr>}</tbody></table>
    </section>
  </div>;
}
