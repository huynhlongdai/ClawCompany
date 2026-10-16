"use client";
// M3e — Công ty › Tài liệu & tri thức › Vòng học: nguồn (cờ agent, cụm lỗ hổng, bài học, agent đề xuất) → đề xuất (bản
// NHÁP trên tài liệu) → duyệt theo đường M3a → ban hành → đóng nguồn → chạy lại eval (trước / sau). Nhãn lấy từ mã + số
// liệu (kind, source_refs), không hiện câu tiếng Việt do backend ghép; câu hỏi khách / ghi chú agent là dữ liệu, hiện nguyên.
import {useState} from "react";
import {apiDocLearning} from "../lib/api";
import {ErrorBanner, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {StatusPill} from "./ui/StatusPill";
import {useToast} from "./ui/Toast";
import {getLocale, t as tr, type Key} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

const P_TONE: Record<string, any> = {open: "wait", published: "ok", rejected: "risk", dismissed: "neutral"};
const pct = (x?: number | null) => x == null ? "—" : `${Math.round(x * 1000) / 10}%`;
const when = (s?: string | null) => s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleString(getLocale() === "en" ? "en-GB" : "vi-VN") : "—";

function Delta({b, a}: {b?: number | null; a?: number | null}) {
  if (b == null || a == null) return null;
  const d = Math.round((a - b) * 1000) / 10;
  return <small className={d > 0 ? "ui-text-ok" : d < 0 ? "ui-text-risk" : ""}> ({d > 0 ? "+" : ""}{d} {tr("learn.points")})</small>;
}

export function DocLearningTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => companyId ? apiDocLearning.get(companyId) : Promise.resolve(null), [companyId]);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const can = !!caps?.invite || !!caps?.manage_roles;
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={error} onRetry={reload} testId="learning-error"/>;
  if (!data) return <SkeletonRows n={5} h={40}/>;
  const d: any = data;
  async function run(fn: () => Promise<any>, ok: (r: any) => string) {
    setBusy(true); setError(null);
    try { const r = await fn(); toast(ok(r)); await reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const latest = d.eval?.latest;
  const items: any[] = d.proposals?.items || [];
  const stage = (st: string[]) => items.filter(p => st.includes(p.status));
  return <section className="ui-section" data-testid="doc-learning">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)} testId="learning-save-error"/> : null}
    <p className="tmGuide">{tr("learn.explain", {p0: d.gap_cluster_min})}</p>

    <div className="learn-kpis" data-testid="learning-kpis">
      <div className="ui-panel learn-kpi"><small>{tr("learn.k_fresh")}</small><b>{pct(d.kpi.doc_freshness_rate)}</b>
        <small>{tr("learn.k_fresh_of", {p0: d.kpi.fresh_docs, p1: d.kpi.published_docs})}</small></div>
      <div className="ui-panel learn-kpi"><small>{tr("learn.k_flags")}</small><b>{d.flags.open}</b>
        <small>{tr("learn.k_flags_closed", {p0: d.flags.resolved})}</small></div>
      <div className="ui-panel learn-kpi"><small>{tr("learn.k_gaps")}</small><b>{d.gaps.open}</b>
        <small>{tr("learn.k_gaps_closed", {p0: d.gaps.closed_by_docs, p1: d.gaps.closed_last_30d})}</small></div>
      <div className="ui-panel learn-kpi" data-testid="learning-eval-latest"><small>{tr("learn.k_eval")}</small>
        <b>{latest ? pct(latest.recall) : "—"}</b>
        <small>{latest ? tr("learn.k_eval_sub", {p0: pct(latest.top1), p1: latest.misses}) : tr("learn.k_eval_none")}</small></div>
    </div>
    <p><small>{tr("learn.gap_rate_na")}</small></p>

    {can && <div className="tmRow">
      <button className="ui-btn is-primary is-sm" disabled={busy} data-testid="learning-propose"
        onClick={() => run(() => apiDocLearning.propose(companyId), r => tr("learn.proposed", {p0: (r.created_or_updated || []).length}))}>{tr("learn.propose")}</button>
      <button className="ui-btn is-ghost is-sm" disabled={busy} data-testid="learning-eval"
        onClick={() => run(() => apiDocLearning.evalRun(companyId), r => r.status === "ok" ? tr("learn.eval_done", {p0: pct(r.recall), p1: pct(r.top1)})
          : tr(`learn.eval_${r.status}` as Key))}>{tr("learn.eval_run")}</button>
    </div>}

    <h3>{tr("learn.h_sources")}</h3>
    <div className="ui-panel" data-testid="learning-clusters">
      {d.gaps.clusters.length === 0 ? <small>{tr("learn.no_clusters")}</small>
        : <table className="ui-table"><thead><tr><th>{tr("learn.c_sample")}</th><th>{tr("learn.c_size")}</th><th>{tr("learn.c_state")}</th></tr></thead>
          <tbody>{d.gaps.clusters.map((c: any, i: number) => <tr key={i}>
            <td>{c.sample}</td><td>{tr("learn.c_asks", {p0: c.size, p1: c.asks})}</td>
            <td><StatusPill tone={c.ready ? "wait" : "neutral"}>{c.ready ? tr("learn.c_ready") : tr("learn.c_below", {p0: d.gap_cluster_min})}</StatusPill></td>
          </tr>)}</tbody></table>}
    </div>

    {[["open", ["open"]], ["published", ["published"]], ["closed", ["rejected", "dismissed"]]].map(([key, st]: any) => {
      const list = stage(st);
      return <div key={key} data-testid={`learning-stage-${key}`}>
        <h3>{tr(`learn.h_${key}` as Key)} <small>({list.length})</small></h3>
        {list.length === 0 ? <p><small>{tr(`learn.empty_${key}` as Key)}</small></p>
          : list.map(p => <Proposal key={p.id} p={p} can={can} busy={busy}
              onDismiss={() => run(() => apiDocLearning.dismiss(p.id), () => tr("learn.dismissed"))}/>)}
      </div>;
    })}

    <h3>{tr("learn.h_eval")}</h3>
    <div className="ui-panel" data-testid="learning-eval-history">
      {d.eval.history.length === 0 ? <small>{tr("learn.k_eval_none")}</small>
        : <table className="ui-table"><thead><tr><th>{tr("learn.e_at")}</th><th>{tr("learn.e_trigger")}</th><th>{tr("learn.e_recall")}</th>
          <th>{tr("learn.e_top1")}</th><th className="learn-hide-sm">{tr("learn.e_misses")}</th></tr></thead>
          <tbody>{d.eval.history.map((r: any) => <tr key={r.id}>
            <td><small>{when(r.at)}</small></td><td>{tr(`learn.trig_${r.trigger}` as Key)}</td><td>{pct(r.recall)}</td><td>{pct(r.top1)}</td>
            <td className="learn-hide-sm"><small>{(r.misses || []).length === 0 ? "0" : (r.misses || []).slice(0, 3).join(" · ")}</small></td>
          </tr>)}</tbody></table>}
    </div>

    {d.unused_180d.length > 0 && <>
      <h3>{tr("learn.h_unused")}</h3>
      <p><small>{d.unused_180d.map((x: any) => `${x.doc_code} ${x.title}`).join(" · ")}</small></p>
    </>}
  </section>;
}

function Proposal({p, can, busy, onDismiss}: {p: any; can: boolean; busy: boolean; onDismiss: () => void}) {
  const refs = p.source_refs || {};
  const n = p.kind === "flag" ? (refs.flags || []).length : p.kind === "gap" ? (refs.gaps || []).length : 0;
  const docHref = p.document ? `/app/company?tab=docs&doc=${p.document.id}` : null;
  return <div className="ui-panel learn-prop" data-testid={`proposal-${p.id}`}>
    <div className="tmRow">
      <StatusPill tone={P_TONE[p.status]}>{tr(`learn.st_${p.status}` as Key)}</StatusPill>
      <b>{tr(`learn.kind_${p.kind}` as Key, {p0: n})}{refs.eval ? " · " + tr("learn.from_eval") : ""}</b>
      <span className="ui-grow"/>
      {p.document && <a className="ui-pill" href={docHref || "#"}><code>{p.document.doc_code}</code> {p.document.title}</a>}
      {p.version && <span className="ui-pill">v{p.version.version_no} · {tr(`docs.st_${p.version.status}` as Key)}</span>}
      {p.new_document && <span className="ui-pill is-wait">{tr("learn.new_doc")}</span>}
    </div>
    {p.kind === "gap" && (refs.questions || []).length > 0
      ? <ul className="learn-qs">{refs.questions.slice(0, 5).map((q: string, i: number) => <li key={i}><small>{q}</small></li>)}</ul>
      : p.rationale && p.kind !== "gap" ? <p><small>{p.rationale}</small></p> : null}
    <div className="tmRow learn-eval">
      <small>{tr("learn.before")}: <b>{p.eval_before ? pct(p.eval_before.recall) : "—"}</b></small>
      <small>{tr("learn.after")}: <b>{p.eval_after ? pct(p.eval_after.recall) : p.eval_pending ? tr("learn.after_pending") : "—"}</b>
        <Delta b={p.eval_before?.recall} a={p.eval_after?.recall}/></small>
      <small>{tr("learn.created")} {when(p.created_at)}</small>
      <span className="ui-grow"/>
      {p.status === "open" && docHref && <a className="ui-btn is-primary is-sm" href={docHref}>{tr("learn.open_draft")}</a>}
      {p.status === "open" && can && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={onDismiss}>{tr("learn.dismiss")}</button>}
    </div>
  </div>;
}
