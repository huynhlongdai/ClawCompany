"use client";
import Link from "next/link";
import {useCallback, useEffect, useState} from "react";
import {useSearchParams} from "next/navigation";
import {Icon} from "./Icon";
import {EmptyState, ErrorState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {useToast} from "./ui/Toast";
import {apiCosts, errorText} from "../lib/api";

/* M4b — Chi phí: tổng chi model (usage_events từ gateway) + ngân sách 3 nấc
   theo công ty / phòng ban / nhóm / agent. Nấc: cảnh báo → dừng mềm (lượt chạy
   mới cần duyệt trong Hộp việc) → dừng cứng (100%, seat tạm dừng). */

const money = (v: number) => `$${Number(v || 0).toFixed(Number(v) >= 1 ? 2 : 4)}`;
const LEVEL_CLS: Record<string, string> = {ok: "is-ok", warned: "is-warn", soft_stopped: "is-soft", exhausted: "is-hard"};

function Bars({rows, empty}: {rows: {name: string; cost_usd: number}[]; empty: string}) {
  if (!rows.length) return <p className="ui-empty-line">{empty}</p>;
  const max = Math.max(...rows.map(r => r.cost_usd), 1e-9);
  return <ul className="cst-bars">{rows.slice(0, 8).map(r => <li key={r.name}>
    <span className="cst-bar-name">{r.name}</span>
    <span className="cst-bar"><i style={{width: `${Math.max(2, r.cost_usd / max * 100)}%`}}/></span>
    <b className="ui-num">{money(r.cost_usd)}</b>
  </li>)}</ul>;
}

function Overview() {
  const [d, setD] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  const load = useCallback(() => { setErr(null); apiCosts.overview(30).then(setD).catch(setErr); }, []);
  useEffect(() => { load(); }, [load]);
  if (err) return <ErrorState error={err} onRetry={load} context="Đọc sổ chi phí"/>;
  if (!d) return <SkeletonRows n={2} h={76}/>;
  const t = d.totals;
  return <div className="cst-overview">
    <div className="cst-tiles">
      <div><small>Hôm nay</small><b>{money(t.today)}</b></div>
      <div><small>7 ngày</small><b>{money(t.d7)}</b></div>
      <div><small>{d.days} ngày</small><b>{money(t.window)}</b></div>
      <div><small>Lượt gọi model</small><b>{t.model_calls.toLocaleString("vi-VN")}</b><em>{t.tokens.toLocaleString("vi-VN")} token</em></div>
    </div>
    {d.alerts > 0 && <Link className="cst-alert" href="?tab=budgets"><Icon name="alert" size={16}/>
      {d.alerts} ngân sách đang ở nấc cảnh báo trở lên — xem tab Ngân sách</Link>}
    {t.model_calls === 0 && <EmptyState mood="ngu" title="Chưa có chi phí model nào trong kỳ">
      Chi phí được ghi khi agent chạy việc qua gateway OpenClaw (mỗi câu trả lời của model mang số tiền của nó).
    </EmptyState>}
    {t.model_calls > 0 && <div className="cst-cols">
      <section><h3>Theo agent</h3><Bars rows={d.by_agent} empty="—"/></section>
      <section><h3>Theo phòng ban</h3><Bars rows={d.by_department} empty="—"/></section>
      <section><h3>Theo công ty</h3><Bars rows={d.by_company} empty="—"/></section>
    </div>}
    <p className="cst-source">Nguồn: {d.source}.</p>
  </div>;
}

function Meter({b}: {b: any}) {
  return <div className="cst-meter" aria-label={`Đã dùng ${b.pct}% hạn mức`}>
    <i className={LEVEL_CLS[b.threshold_state] || ""} style={{width: `${Math.min(100, b.pct)}%`}}/>
    {b.levels.filter((l: any) => l.pct < 100).map((l: any) =>
      <span key={l.key} className="cst-mark" style={{left: `${l.pct}%`}} title={`${l.label} ${l.pct}%`}/>)}
  </div>;
}

function BudgetCard({b, manage, onChanged}: {b: any; manage: boolean; onChanged: (msg: string) => void}) {
  const [mode, setMode] = useState<"" | "edit" | "raise">("");
  const [limit, setLimit] = useState(String(b.amount_limit)), [warn, setWarn] = useState(String(b.warn_pct));
  const [soft, setSoft] = useState(b.soft_stop_pct ? String(b.soft_stop_pct) : "");
  const [add, setAdd] = useState(""), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  async function run(fn: () => Promise<any>, msg: string) {
    setBusy(true); setErr("");
    try { await fn(); setMode(""); onChanged(msg); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }
  const hard = b.threshold_state === "exhausted";
  return <article className={"cst-budget " + (LEVEL_CLS[b.threshold_state] || "")} data-testid={`budget-${b.id}`}>
    <header>
      <div><b>{b.name}</b><small>{b.scope_vi} · {b.scope_name}</small></div>
      <span className={"cst-level " + (LEVEL_CLS[b.threshold_state] || "")}>{b.level_vi}</span>
    </header>
    <Meter b={b}/>
    <div className="cst-figures">
      <span><b className="ui-num">{money(b.amount_spent)}</b> / {money(b.amount_limit)} ({b.pct}%)</span>
      {b.amount_reserved > 0 && <span>đang giữ chỗ {money(b.amount_reserved)}</span>}
      <span>Nấc: cảnh báo {b.warn_pct}%{b.soft_stop_pct ? ` · dừng mềm ${b.soft_stop_pct}%` : ""} · dừng cứng 100%</span>
    </div>
    {b.pending_approvals > 0 && <Link className="cst-alert" href="/app/inbox?group=approvals">
      <Icon name="check" size={14}/>{b.pending_approvals} yêu cầu chi tiếp đang chờ duyệt</Link>}
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    {manage && mode === "edit" && <div className="cst-form">
      <label>Hạn mức (USD)<input inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value)} disabled={hard}/></label>
      <label>Cảnh báo (%)<input inputMode="numeric" value={warn} onChange={e => setWarn(e.target.value)}/></label>
      <label>Dừng mềm (%)<input inputMode="numeric" value={soft} placeholder="tắt" onChange={e => setSoft(e.target.value)}/></label>
      {hard && <small>Ngân sách đã dừng cứng — đổi hạn mức bằng "Nâng hạn mức".</small>}
      <div className="cst-form-actions">
        <button className="ui-btn is-ghost" onClick={() => setMode("")}>Huỷ</button>
        <button className="ui-btn is-primary" disabled={busy} onClick={() => run(() => apiCosts.update(b.id, {
          ...(hard ? {} : {amount_limit: Number(limit)}), warn_pct: Number(warn), soft_stop_pct: soft ? Number(soft) : null,
        }), "Đã lưu ngân sách")}>Lưu</button>
      </div>
    </div>}
    {manage && mode === "raise" && <div className="cst-form">
      <label>Cộng thêm (USD)<input inputMode="decimal" value={add} onChange={e => setAdd(e.target.value)}/></label>
      <label className="is-wide">Lý do (lưu vào nhật ký)<input value={reason} onChange={e => setReason(e.target.value)}
        placeholder="VD: chạy chiến dịch hè"/></label>
      <div className="cst-form-actions">
        <button className="ui-btn is-ghost" onClick={() => setMode("")}>Huỷ</button>
        <button className="ui-btn is-primary" disabled={busy || !Number(add)} onClick={() => run(() =>
          apiCosts.override(b.id, {add_usd: Number(add), reason}), "Đã nâng hạn mức — seat và việc bị chặn được mở lại")}>Nâng hạn mức</button>
      </div>
    </div>}
    {manage && !mode && <div className="cst-actions">
      <button className="ui-btn is-ghost is-sm" onClick={() => setMode("edit")}>Sửa nấc</button>
      <button className={"ui-btn is-sm " + (hard ? "is-primary" : "is-ghost")} onClick={() => setMode("raise")}>Nâng hạn mức</button>
      {!hard && <button className="ui-btn is-ghost is-sm" disabled={busy}
        onClick={() => window.confirm(`Lưu trữ ngân sách "${b.name}"? Phạm vi này sẽ không còn hạn mức.`)
          && run(() => apiCosts.archive(b.id), "Đã lưu trữ ngân sách")}>Lưu trữ</button>}
    </div>}
  </article>;
}

function CreateBudget({scopes, onDone}: {scopes: any; onDone: (msg: string) => void}) {
  const [type, setType] = useState("department"), [sid, setSid] = useState("");
  const [limit, setLimit] = useState("20"), [warn, setWarn] = useState("80"), [soft, setSoft] = useState("90");
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const opts: any[] = scopes?.[type] || [];
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      await apiCosts.create({scope_type: type, scope_id: sid ? Number(sid) : null, amount_limit: Number(limit),
        warn_pct: Number(warn), soft_stop_pct: soft ? Number(soft) : null});
      onDone("Đã tạo ngân sách");
    } catch (e2) { setErr(errorText(e2)); } finally { setBusy(false); }
  }
  return <form className="cst-form cst-create" onSubmit={submit}>
    <label>Phạm vi<select value={type} onChange={e => { setType(e.target.value); setSid(""); }}>
      <option value="company">Công ty</option><option value="department">Phòng ban</option>
      <option value="team">Nhóm</option><option value="member">Agent</option></select></label>
    <label className="is-wide">Áp cho<select value={sid} onChange={e => setSid(e.target.value)} required>
      <option value="">— chọn —</option>{opts.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
    <label>Hạn mức (USD)<input inputMode="decimal" value={limit} onChange={e => setLimit(e.target.value)} required/></label>
    <label>Cảnh báo (%)<input inputMode="numeric" value={warn} onChange={e => setWarn(e.target.value)}/></label>
    <label>Dừng mềm (%)<input inputMode="numeric" value={soft} placeholder="tắt" onChange={e => setSoft(e.target.value)}/></label>
    {err && <p className="ui-inline-error" role="alert">{err}</p>}
    <div className="cst-form-actions"><button className="ui-btn is-primary" disabled={busy}>{busy ? "Đang tạo…" : "Tạo ngân sách"}</button></div>
  </form>;
}

function Budgets() {
  const [d, setD] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const load = useCallback(() => { setErr(null); apiCosts.budgets().then(setD).catch(setErr); }, []);
  useEffect(() => { load(); }, [load]);
  const changed = (msg: string) => { toast(msg); setCreating(false); load(); };
  if (err) return <ErrorState error={err} onRetry={load} context="Mở sổ ngân sách"/>;
  if (!d) return <SkeletonRows n={2} h={120}/>;
  return <div className="cst-budgets">
    <p className="cst-help">Ba nấc trên mỗi ngân sách: <b>cảnh báo</b> (báo vào Hộp việc, agent chỉ làm việc critical) →
      <b> dừng mềm</b> (mỗi lượt chạy mới cần anh duyệt — duyệt cho một việc, cả seat hoặc cả phòng) →
      <b> dừng cứng</b> ở 100% (seat tạm dừng, việc bị chặn, chỉ mở lại bằng Nâng hạn mức có lý do).</p>
    {d.caps.manage && (creating ? <CreateBudget scopes={d.scopes} onDone={changed}/>
      : <button className="ui-btn is-primary" onClick={() => setCreating(true)}><Icon name="plus" size={14}/>Thêm ngân sách</button>)}
    {!d.budgets.length && !creating && <EmptyState mood="chao" title="Chưa có ngân sách nào">
      Đặt hạn mức cho công ty, phòng ban, nhóm hoặc từng agent để chi phí model không vượt ngoài ý anh.
    </EmptyState>}
    <div className="cst-list">{d.budgets.map((b: any) => <BudgetCard key={b.id} b={b} manage={d.caps.manage} onChanged={changed}/>)}</div>
  </div>;
}

export function CostsBoard() {
  /* Tab Tổng quan / Ngân sách nằm ở khung trang (lib/nav.ts) — đổi URL, chia sẻ được. */
  const tab = useSearchParams().get("tab") === "budgets" ? "budgets" : "overview";
  return <div className="cst">
    {tab === "overview" ? <Overview/> : <Budgets/>}
  </div>;
}
