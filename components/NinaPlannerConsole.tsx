"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {PageFrame} from "./shell/PageFrame";
import {api, apiV8} from "../lib/api";
import {activeOrganizationId} from "../lib/auth";
import {Button} from "./ui/Button";
import {Field, FormRow} from "./ui/Field";
import {Panel} from "./ui/Panel";
import {StatusPill, toneOf} from "./ui/StatusPill";
import {EmptyState, ErrorBanner} from "./ui/EmptyState";
import {useToast} from "./ui/Toast";

/* Mục tiêu & Kế hoạch › Nina lập nhanh (v8 planner): đưa một kết quả, Nina chia
   thành các bước có người phụ trách và tạo việc ngay — không qua vòng duyệt.
   Muốn có duyệt theo phòng ban thì dùng tab "Kế hoạch chờ duyệt". */

type Plan = {id: number; objective: string; status: string; summary: string; created_at: string};
type Detail = {plan: Plan; steps: {id: number; step_index: number; title: string; description: string; owner_member_id: number | null; task_id: number | null; status: string}[]};
const ST_VI: Record<string, string> = {planned: "Đã lập", delegated: "Đã giao", draft: "Nháp", completed: "Xong", pending: "Chờ", in_progress: "Đang làm", todo: "Cần làm", done: "Xong"};

export function NinaPlannerConsole() {
  const org = activeOrganizationId();
  const toast = useToast();
  const [objective, setObjective] = useState(""), [companyId, setCompanyId] = useState(""), [projectId, setProjectId] = useState("");
  const [companies, setCompanies] = useState<any[]>([]), [projects, setProjects] = useState<any[]>([]), [plans, setPlans] = useState<Plan[]>([]);
  const [members, setMembers] = useState<Record<number, string>>({});
  const [detail, setDetail] = useState<Detail | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    const [c, p, pl, m] = await Promise.allSettled([api.companies(org), api.projects(), apiV8.ninaPlans(), api.members()]);
    if (c.status === "fulfilled") setCompanies((c.value as any[]) || []);
    if (p.status === "fulfilled") setProjects((p.value as any[]) || []);
    if (pl.status === "fulfilled") setPlans((pl.value as Plan[]) || []); else setError(pl.reason);
    if (m.status === "fulfilled") setMembers(Object.fromEntries(((m.value as any[]) || []).map(x => [x.id, x.name])));
  }, [org]);
  useEffect(() => { load(); }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const j = await apiV8.createNinaPlan({organization_id: org, objective, company_id: companyId ? Number(companyId) : null,
        project_id: projectId ? Number(projectId) : null, auto_create_tasks: true, max_steps: 5}) as Detail;
      setDetail(j); toast(`Nina đã lập kế hoạch #${j.plan.id} với ${j.steps.length} bước`); setObjective(""); await load();
    } catch (e2) { setError(e2); } finally { setBusy(false); }
  }
  async function delegate() {
    if (!detail) return; setBusy(true); setError(null);
    try { await apiV8.delegateNinaPlan(detail.plan.id); setDetail({...detail, plan: {...detail.plan, status: "delegated"}}); toast("Đã giao kế hoạch cho đội agent"); await load(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function openPlan(id: number) {
    setError(null);
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api"}/nina/plans/${id}`, {headers: {Authorization: `Bearer ${localStorage.getItem("clawcompany_token")}`}});
      if (!r.ok) throw Object.assign(new Error(await r.text()), {status: r.status});
      setDetail(await r.json());
    } catch (e) { setError(e); }
  }

  return <PageFrame>
    <section className="nina-hero"><span className="nina-orb" aria-hidden="true">N</span>
      <div><h2>Đưa Nina kết quả, không cần danh sách việc</h2>
        <p>Nina chia mục tiêu thành tối đa 5 bước, chọn agent hợp vai và tạo việc ngay. Cần duyệt trước khi giao? Dùng tab <Link className="ui-link" href="/app/strategy">Kế hoạch chờ duyệt</Link>.</p></div></section>
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} context="Lập kế hoạch"/> : null}
    <div className="ui-grid is-2">
      <Panel title="Mục tiêu cho Nina">
        <form className="ui-form" onSubmit={create}>
          <Field label="Công ty cần đạt điều gì?"><textarea rows={4} value={objective} onChange={e => setObjective(e.target.value)} placeholder="VD: Chạy chiến dịch TikTok có lãi cho bộ sưu tập hè trong 14 ngày…"/></Field>
          <FormRow>
            <Field label="Công ty"><select value={companyId} onChange={e => { setCompanyId(e.target.value); setProjectId(""); }}>
              <option value="">Không giới hạn</option>{companies.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <Field label="Dự án"><select value={projectId} onChange={e => setProjectId(e.target.value)}>
              <option value="">Nina tạo dự án mới</option>{projects.filter(p => !companyId || String(p.company_id) === companyId).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          </FormRow>
          <Button type="submit" variant="primary" busy={busy} disabled={objective.trim().length < 4}>{busy ? "Nina đang lập…" : "Lập kế hoạch"}</Button>
        </form>
      </Panel>
      <Panel title={detail ? `Kế hoạch #${detail.plan.id}` : "Kế hoạch gần đây"} desc={detail ? detail.plan.objective : `${plans.length} kế hoạch`}
        actions={detail ? <>{detail.plan.status !== "delegated" && <Button size="sm" variant="primary" busy={busy} onClick={delegate}>Giao cho đội</Button>}
          <Button size="sm" variant="ghost" onClick={() => setDetail(null)}>Danh sách</Button></> : undefined} flush={!detail}>
        {detail ? <ol className="gl-steps">{detail.steps.map(s => <li key={s.id}>
            <div><b>{s.title}</b><small>{s.description}</small></div>
            <div style={{textAlign: "right"}}><StatusPill tone={toneOf(s.status)}>{ST_VI[s.status] || s.status}</StatusPill>
              <small>{s.owner_member_id ? members[s.owner_member_id] || `#${s.owner_member_id}` : "chưa có người"}{s.task_id ? <> · <Link href={`/app/work?peek=${s.task_id}`}>việc #{s.task_id}</Link></> : null}</small></div>
          </li>)}</ol>
          : plans.length === 0 ? <EmptyState compact mood="chao" title="Chưa có kế hoạch nào">Viết mục tiêu bên trái rồi bấm Lập kế hoạch.</EmptyState>
          : <div className="ui-list">{plans.slice(0, 12).map(p => <button key={p.id} className="ui-row" onClick={() => openPlan(p.id)}>
              <span className="ui-row-main"><span className="ui-row-title">#{p.id} {p.objective}</span><span className="ui-row-meta">{p.summary}</span></span>
              <StatusPill tone={toneOf(p.status)}>{ST_VI[p.status] || p.status}</StatusPill></button>)}</div>}
      </Panel>
    </div>
  </PageFrame>;
}
