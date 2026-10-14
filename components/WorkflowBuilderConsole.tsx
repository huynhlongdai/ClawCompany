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

/* Việc định kỳ › Quy trình (v8 workflow graph): đồ thị bước có phiên bản bất biến.
   UI v2: tiếng Việt, primitive; API giữ nguyên (lưu nháp / phát hành một phiên bản). */
type WF = {id: number; name: string; trigger_type: string; status: string};
const TYPE_VI: Record<string, string> = {trigger: "Kích hoạt", agent: "Agent làm", approval: "Duyệt", tool: "Công cụ", human: "Người làm"};
const STATUS_VI: Record<string, string> = {active: "Đang dùng", draft: "Nháp", paused: "Tạm dừng", archived: "Lưu trữ"};
const starter = {nodes: [{id: "trigger", type: "trigger", label: "Có việc mới"}, {id: "research", type: "agent", label: "Agent tìm hiểu"},
  {id: "draft", type: "agent", label: "Viết bản nháp"}, {id: "approval", type: "approval", label: "Quản lý duyệt"}, {id: "publish", type: "tool", label: "Đăng kết quả"}],
  edges: [{source: "trigger", target: "research"}, {source: "research", target: "draft"}, {source: "draft", target: "approval"}, {source: "approval", target: "publish"}]};

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
    try { const v: any = await apiV8.saveWorkflowGraph(selected, graph, publish); toast(`Đã lưu phiên bản ${v.version}${publish ? " và phát hành" : " (nháp)"}`);
      setVersions(await apiV8.workflowGraphVersions(selected) as any[]); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  const addNode = () => setGraph({...graph, nodes: [...graph.nodes, {id: `buoc-${graph.nodes.length + 1}`, type: "agent", label: "Bước mới"}]});

  return <PageFrame actions={selected ? <><Button onClick={() => save(false)} busy={busy}>Lưu nháp</Button><Button variant="primary" onClick={() => save(true)} disabled={busy}>Phát hành</Button></> : undefined}>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} context="Quy trình"/> : null}
    {flows && flows.length === 0 ? <EmptyState mood="chao" title="Chưa có quy trình">
      Quy trình là chuỗi bước cố định (agent làm → người duyệt → công cụ đăng). Việc lặp đơn giản thì dùng tab Việc định kỳ.</EmptyState> :
    <div className="wf">
      <Panel title="Quy trình" desc={flows ? `${flows.length} quy trình` : "Đang tải…"} flush>
        <div className="ui-list">{(flows || []).map(f => <button key={f.id} className="ui-row" aria-pressed={selected === f.id} onClick={() => setSelected(f.id)}
          style={selected === f.id ? {background: "var(--selected)"} : undefined}>
          <span className="ui-row-main"><span className="ui-row-title">{f.name}</span><span className="ui-row-meta">{f.trigger_type}</span></span>
          <StatusPill tone={f.status === "active" ? "ok" : "neutral"}>{STATUS_VI[f.status] || f.status}</StatusPill></button>)}</div>
      </Panel>
      <Panel title="Các bước" desc="Đồ thị được kiểm tra không có vòng lặp khi lưu" actions={<Button size="sm" icon="plus" onClick={addNode}>Thêm bước</Button>}>
        <ol className="wf-steps">{graph.nodes.map((n: any, i: number) => <li key={n.id} className={"wf-node is-" + n.type}>
          <span className="wf-type">{TYPE_VI[n.type] || n.type}</span>
          <input value={n.label} aria-label={`Tên bước ${i + 1}`} onChange={e => { const nodes = [...graph.nodes]; nodes[i] = {...n, label: e.target.value}; setGraph({...graph, nodes}); }}/>
          <code translate="no">{n.id}</code>
        </li>)}</ol>
        <details style={{marginTop: 12}}><summary>Nối giữa các bước ({graph.edges.length})</summary>
          <ul className="wf-edges">{graph.edges.map((e: any, i: number) => <li key={i}><code>{e.source}</code> → <code>{e.target}</code></li>)}</ul></details>
      </Panel>
      <Panel title="Phiên bản" desc="Ảnh chụp bất biến" flush>
        <div className="ui-list">{versions.map(v => <div key={v.id} className="ui-row"><span className="ui-row-main"><span className="ui-row-title">Bản {v.version}</span></span>
          <StatusPill tone={v.published ? "ok" : "neutral"}>{v.published ? "Đã phát hành" : "Nháp"}</StatusPill></div>)}
          {!versions.length && <p className="ui-row ui-row-meta">Chưa lưu phiên bản nào.</p>}</div>
      </Panel>
    </div>}
  </PageFrame>;
}
