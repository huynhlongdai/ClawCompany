"use client";
import {useCallback, useEffect, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiV8} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {Panel} from "./ui/Panel";
import {StatusPill} from "./ui/StatusPill";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {useToast} from "./ui/Toast";
import {t, lazy} from "../lib/i18n";

/* Việc định kỳ › Quy trình (v8 workflow graph): đồ thị bước có phiên bản bất biến.
   UI v2: tiếng Việt, primitive; API giữ nguyên (lưu nháp / phát hành một phiên bản). */
type WF = {id: number; name: string; trigger_type: string; status: string};
const TYPE_VI: Record<string, string> = lazy(() => ({trigger: t("workflows.kich_hoat"), agent: t("workflows.agent_lam"), approval: t("workflows.duyet"), tool: t("workflows.cong_cu"), human: t("workflows.nguoi_lam")}));
const STATUS_VI: Record<string, string> = lazy(() => ({active: t("workflows.dang_dung"), draft: t("workflows.nhap"), paused: t("workflows.tam_dung"), archived: t("workflows.luu_tru")}));
const starter = lazy(() => ({nodes: [{id: "trigger", type: "trigger", label: t("workflows.co_viec_moi")}, {id: "research", type: "agent", label: t("workflows.agent_tim_hieu")},
  {id: "draft", type: "agent", label: t("workflows.viet_ban_nhap")}, {id: "approval", type: "approval", label: t("workflows.quan_ly_duyet")}, {id: "publish", type: "tool", label: t("workflows.dang_ket_qua")}],
  edges: [{source: "trigger", target: "research"}, {source: "research", target: "draft"}, {source: "draft", target: "approval"}, {source: "approval", target: "publish"}]}));

export function WorkflowBuilderConsole() {
  const org = activeOrganizationId();
  const toast = useToast();
  const [flows, setFlows] = useState<WF[] | null>(null), [selected, setSelected] = useState<number | undefined>();
  const [graph, setGraph] = useState<any>(starter), [versions, setVersions] = useState<any[]>([]);
  const [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const f = await api.workflows(org) as WF[]; setFlows(f || []); setSelected(s => s ?? f?.[0]?.id); }
    catch (e) { setError(e); setFlows([]); }
  }, [org]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!selected) return;
    apiV8.workflowGraphVersions(selected).then((v: any) => { setVersions(v || []); if (v?.[0]) try { setGraph(JSON.parse(v[0].graph_json)); } catch { /* đồ thị hỏng: giữ mẫu */ } })
      .catch(setError);
  }, [selected]);

  async function save(publish: boolean) {
    if (!selected) return; setError(null); setBusy(true);
    try { const v: any = await apiV8.saveWorkflowGraph(selected, graph, publish); toast(t("workflows.da_luu_phien_ban", {p0: v.version, p1: publish ? " và phát hành" : " (nháp)"}));
      setVersions(await apiV8.workflowGraphVersions(selected) as any[]); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const addNode = () => setGraph({...graph, nodes: [...graph.nodes, {id: `buoc-${graph.nodes.length + 1}`, type: "agent", label: t("workflows.buoc_moi")}]});

  return <PageFrame actions={selected ? <><Button onClick={() => save(false)} busy={busy}>{t("workflows.luu_nhap")}</Button><Button variant="primary" onClick={() => save(true)} disabled={busy}>{t("workflows.phat_hanh")}</Button></> : undefined}>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} context={t("workflows.quy_trinh")}/> : null}
    {flows && flows.length === 0 ? <EmptyState mood="chao" title={t("workflows.chua_co_quy_trinh")}>
      {t("workflows.quy_trinh_la_chuoi_buoc")}</EmptyState> :
    <div className="wf">
      <Panel title={t("workflows.quy_trinh")} desc={flows ? t("workflows.quy_trinh_2", {p0: flows.length}) : t("workflows.dang_tai")} flush>
        <div className="ui-list">{(flows || []).map(f => <button key={f.id} className="ui-row" aria-pressed={selected === f.id} onClick={() => setSelected(f.id)}
          style={selected === f.id ? {background: "var(--selected)"} : undefined}>
          <span className="ui-row-main"><span className="ui-row-title">{f.name}</span><span className="ui-row-meta">{f.trigger_type}</span></span>
          <StatusPill tone={f.status === "active" ? "ok" : "neutral"}>{STATUS_VI[f.status] || f.status}</StatusPill></button>)}</div>
      </Panel>
      <Panel title={t("workflows.cac_buoc")} desc={t("workflows.do_thi_duoc_kiem_tra")} actions={<Button size="sm" icon="plus" onClick={addNode}>{t("workflows.them_buoc")}</Button>}>
        <ol className="wf-steps">{graph.nodes.map((n: any, i: number) => <li key={n.id} className={"wf-node is-" + n.type}>
          <span className="wf-type">{TYPE_VI[n.type] || n.type}</span>
          <input value={n.label} aria-label={t("workflows.ten_buoc", {p0: i + 1})} onChange={e => { const nodes = [...graph.nodes]; nodes[i] = {...n, label: e.target.value}; setGraph({...graph, nodes}); }}/>
          <code translate="no">{n.id}</code>
        </li>)}</ol>
        <details style={{marginTop: 12}}><summary>{t("workflows.noi_giua_cac_buoc")}{graph.edges.length})</summary>
          <ul className="wf-edges">{graph.edges.map((e: any, i: number) => <li key={i}><code>{e.source}</code> → <code>{e.target}</code></li>)}</ul></details>
      </Panel>
      <Panel title={t("workflows.phien_ban")} desc={t("workflows.anh_chup_bat_bien")} flush>
        <div className="ui-list">{versions.map(v => <div key={v.id} className="ui-row"><span className="ui-row-main"><span className="ui-row-title">{t("workflows.ban")} {v.version}</span></span>
          <StatusPill tone={v.published ? "ok" : "neutral"}>{v.published ? t("workflows.da_phat_hanh") : t("workflows.nhap")}</StatusPill></div>)}
          {!versions.length && <p className="ui-row ui-row-meta">{t("workflows.chua_luu_phien_ban_nao")}</p>}</div>
      </Panel>
    </div>}
  </PageFrame>;
}
