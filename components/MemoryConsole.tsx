"use client";
import {useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {apiSharedMemory} from "../lib/api";
import {t as tr} from "../lib/i18n";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

function tokenRole(): string {
  try {
    const t = localStorage.getItem("clawcompany_token") || "";
    return JSON.parse(atob((t.split(".")[1] || "").replace(/-/g, "+").replace(/_/g, "/"))).role || "";
  } catch { return ""; }
}

const empty = {scope: "org", scope_id: "" as any, kind: "policy", content: "", importance: 3};

/* Phase B việc 7: bộ nhớ chung theo phạm vi. Agent tra bằng tool company_memory_search
   và chỉ thấy phần thuộc tổ chức, công ty, phòng, dự án của mình, cùng mục ghi riêng cho mình. */
export function MemoryConsole() {
  const canEdit = ["owner", "admin", "manager"].includes(tokenRole());
  const [filter, setFilter] = useState({scope: "", q: ""});
  const opt = useLoad(async () => await apiSharedMemory.options(), null as Any);
  const q = useLoad(async () => ((await apiSharedMemory.list({scope: filter.scope || undefined, q: filter.q})).items) as Any[], [], [filter.scope]);
  const [f, setF] = useState<Any>(empty);
  const [editId, setEditId] = useState<number | null>(null);
  const act = useAction();
  const o = opt.data;
  const targets = (scope: string): Any[] => !o ? [] : scope === "company" ? o.companies : scope === "department" ? o.departments
    : scope === "project" ? o.projects : scope === "agent" ? o.agents : [];
  const save = () => act.run("save", async () => {
    const body = {...f, scope_id: f.scope === "org" ? null : Number(f.scope_id) || null, importance: Number(f.importance)};
    if (editId) await apiSharedMemory.update(editId, body); else await apiSharedMemory.create(body);
    setF(empty); setEditId(null); await q.reload();
  }, editId ? tr("memory.da_sua") : tr("memory.da_ghi"));
  const forget = (x: Any) => { if (window.confirm(tr("memory.xac_nhan_quen")))
    act.run("forget", async () => { await apiSharedMemory.forget(x.id); await q.reload(); }, tr("memory.da_quen")); };
  return <PageFrame>
    <LabBody q={q}>
      {act.error ? <ErrorBanner error={act.error} context={tr("memory.bo_nho_chung")} onClose={() => act.setError(null)}/> : null}
      {canEdit && <Panel title={editId ? tr("memory.sua_muc") : tr("memory.ghi_nho")} desc={tr("memory.ghi_nho_desc")}>
        <div className="ui-form" data-testid="shared-mem-form">
          <div className="ui-form-row">
            <Field label={tr("memory.pham_vi")}><select className="ui-select" value={f.scope} data-testid="shared-mem-scope"
              onChange={e => setF({...f, scope: e.target.value, scope_id: ""})}>
              {(o?.scopes || []).map((s: Any) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></Field>
            {f.scope !== "org" && <Field label={tr("memory.thuoc")}><select className="ui-select" value={f.scope_id}
              onChange={e => setF({...f, scope_id: e.target.value})} data-testid="shared-mem-target">
              <option value="">{tr("memory.chon")}</option>
              {targets(f.scope).map((x: Any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>}
            <Field label={tr("memory.loai")}><select className="ui-select" value={f.kind} onChange={e => setF({...f, kind: e.target.value})}>
              {(o?.kinds || []).map((k: Any) => <option key={k.key} value={k.key}>{k.label}</option>)}</select></Field>
            <Field label={tr("memory.quan_trong")}><select className="ui-select" value={f.importance} onChange={e => setF({...f, importance: e.target.value})}>
              {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}/5</option>)}</select></Field>
          </div>
          <Field label={tr("memory.noi_dung")}><textarea className="ui-textarea" rows={3} value={f.content} data-testid="shared-mem-content"
            placeholder={tr("memory.noi_dung_placeholder")} onChange={e => setF({...f, content: e.target.value})}/></Field>
          <div className="ui-toolbar">
            <Button variant="primary" busy={act.busy === "save"} disabled={!f.content.trim() || (f.scope !== "org" && !f.scope_id)}
              onClick={save}>{editId ? tr("memory.luu") : tr("memory.ghi_nho")}</Button>
            {editId && <Button onClick={() => { setEditId(null); setF(empty); }}>{tr("memory.huy")}</Button>}
          </div>
        </div>
      </Panel>}
      <Panel title={tr("memory.bo_nho_chung")} desc={tr("memory.so_muc", {p0: q.data.length})}>
        <form className="ui-toolbar" style={{marginBottom: 12}} onSubmit={e => { e.preventDefault(); q.reload(); }}>
          <select className="ui-select" style={{width: "auto"}} value={filter.scope} onChange={e => setFilter({...filter, scope: e.target.value})}>
            <option value="">{tr("memory.moi_pham_vi")}</option>
            {(o?.scopes || []).map((s: Any) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
          <input className="ui-input" style={{flex: "1 1 220px", width: "auto"}} placeholder={tr("memory.tim")}
            value={filter.q} onChange={e => setFilter({...filter, q: e.target.value})}/>
          <Button type="submit" icon="search" busy={q.loading}>{tr("memory.tim_nut")}</Button>
        </form>
        <Table rows={q.data} empty={tr("memory.trong")} testId="shared-mem-list" cols={[
          {label: tr("memory.pham_vi"), render: x => <><Pill s="info" label={x.scope_label}/><br/><small>{x.scope_name}</small></>},
          {label: tr("memory.noi_dung"), render: x => <>{x.content}<br/><small>{x.kind_label} · {tr("memory.quan_trong")} {x.importance}/5</small></>},
          ...(canEdit ? [{label: "", render: (x: Any) => <div className="ui-toolbar">
            <Button onClick={() => { setEditId(x.id); setF({scope: x.scope, scope_id: x.scope_id || "", kind: x.kind, content: x.content, importance: x.importance}); }}>{tr("memory.sua")}</Button>
            <Button onClick={() => forget(x)} busy={act.busy === "forget"}>{tr("memory.quen")}</Button></div>}] : []),
        ]}/>
      </Panel>
    </LabBody>
  </PageFrame>;
}
