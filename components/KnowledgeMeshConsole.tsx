"use client";
import {useEffect, useState} from "react";
import {apiV16} from "../lib/api";
import {viTime} from "../lib/labels";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, Intro, LabBody, Panel, Pill, Rows, Table, useAction, useLoad} from "./lab/kit";

const arr = (x: any, key: string) => Array.isArray(x) ? x : (x?.[key] || []);

/* Lưới tri thức (v16): không gian tri thức từ chối mặc định, cấp quyền có hạn, nhật ký truy cập. */
export function KnowledgeMeshConsole() {
  const q = useLoad(async () => {
    const [s, l] = await Promise.all([apiV16.spaces(), apiV16.accessLogs()]);
    return {spaces: arr(s, "spaces") as Any[], logs: arr(l, "logs") as Any[]};
  }, {spaces: [], logs: []});
  const {data} = q;
  const [spaceId, setSpaceId] = useState<number | null>(null);
  const [grants, setGrants] = useState<Any[]>([]);
  const [memberId, setMemberId] = useState("");
  const [permission, setPermission] = useState<Any | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Any[] | null>(null);
  const act = useAction();
  useEffect(() => { if (spaceId == null && data.spaces.length) setSpaceId(data.spaces[0].id); }, [data.spaces, spaceId]);
  useEffect(() => { if (spaceId == null) return; apiV16.grants(spaceId).then((g: any) => setGrants(arr(g, "grants"))).catch(() => setGrants([])); }, [spaceId]);
  const space = data.spaces.find(s => s.id === spaceId);
  const needMember = () => { if (!memberId) { act.setError(new Error("Nhập mã thành viên (member_id) của agent để kiểm tra đúng quyền của agent đó.")); return true; } return false; };
  const check = () => { if (needMember() || spaceId == null) return; act.run("perm", async () => setPermission(await apiV16.permission(spaceId, Number(memberId)) as Any)); };
  const search = () => { if (needMember()) return; act.run("search", async () => { const r: any = await apiV16.search({query, member_id: Number(memberId), space_id: spaceId || undefined}); setHits(arr(r, "results")); }); };
  return <LabBody q={q}>
    <Intro>Tri thức dùng chung theo nguyên tắc từ chối mặc định: mọi lượt đọc hay đóng góp đều đi qua quyền hiệu lực và được ghi nhật ký.</Intro>
    <div className="ui-grid is-2">
      <Panel title="Không gian tri thức" desc="Chọn một không gian để xem quyền đã cấp">
        <Rows rows={data.spaces} empty="Chưa có không gian nào." onPick={s => setSpaceId(s.id)} picked={s => s.id === spaceId}
          title={s => s.name} meta={s => `Phân loại: ${s.classification} · mặc định: ${s.default_permission}`}/>
      </Panel>
      <Panel title={`Quyền đã cấp${space ? ` · ${space.name}` : ""}`}>
        <Table rows={grants} empty="Chưa cấp quyền nào — mặc định là từ chối." cols={[
          {label: "Đối tượng", render: g => <>{g.grantee_type} #{g.grantee_id}</>},
          {label: "Quyền", render: g => <code>{g.permission}</code>},
          {label: "Hết hạn", render: g => viTime(g.expires_at), nowrap: true},
        ]}/>
      </Panel>
    </div>
    <Panel title="Kiểm tra quyền và tìm theo danh tính agent">
      {act.error ? <ErrorBanner error={act.error} context="Tra lưới tri thức" onClose={() => act.setError(null)}/> : null}
      <div className="ui-form-row" style={{alignItems: "end", marginTop: act.error ? 12 : 0}}>
        <Field label="Mã thành viên (member_id)"><input className="ui-input" inputMode="numeric" value={memberId} onChange={e => setMemberId(e.target.value)} placeholder="vd. 4"/></Field>
        <Field label="Từ khoá"><input className="ui-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="vd. quy trình đóng gói"/></Field>
        <div className="ui-toolbar">
          <Button busy={act.busy === "perm"} onClick={check}>Xem quyền hiệu lực</Button>
          <Button variant="primary" icon="search" busy={act.busy === "search"} onClick={search}>Tìm</Button>
        </div>
      </div>
      {permission && <p style={{margin: "12px 0 0"}}>Quyền hiệu lực: <Pill s="info" label={permission.permission || permission.effective_permission || "không có"}/></p>}
      {hits && <div style={{marginTop: 12}}><Table rows={hits} empty="Không có kết quả trong phạm vi quyền của agent này." cols={[
        {label: "Tiêu đề", render: h => <b>{h.title}</b>},
        {label: "Không gian", render: h => <>#{h.space_id}</>},
        {label: "Phiên bản", render: h => `v${h.version || 1}`},
        {label: "Nguồn", render: h => h.source_type || "—", hideSm: true},
      ]}/></div>}
    </Panel>
    <Panel title="Nhật ký truy cập">
      <Table rows={data.logs.slice(0, 25)} empty="Chưa có lượt truy cập nào." cols={[
        {label: "Lúc", render: l => viTime(l.created_at), nowrap: true},
        {label: "Thành viên", render: l => <>#{l.member_id}</>},
        {label: "Không gian", render: l => <>#{l.space_id}</>, hideSm: true},
        {label: "Hành động", render: l => <code>{l.action}</code>},
        {label: "Kết quả", render: l => <Pill s={l.allowed === false ? "rejected" : "approved"} label={l.allowed === false ? "Từ chối" : "Cho phép"}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
