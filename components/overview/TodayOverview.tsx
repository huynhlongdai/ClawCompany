"use client";
import {riskLabel} from "@/lib/risk";
import {kindLabel, deadlineText} from "@/lib/approvalText";
import Link from "next/link";
import {useCallback, useEffect, useMemo, useState} from "react";
import {Icon} from "../Icon";
import {BeCang} from "../BeCang";
import {StatusPill} from "../ui/StatusPill";
import {ErrorBanner, EmptyState, Notice} from "../ui/EmptyState";
import {Skeleton} from "../ui/Skeleton";
import {ButtonLink} from "../ui/Button";
import {apiCosts, apiInboxHub, apiWork} from "../../lib/api";
import {useCounts} from "../shell/Shell";
import {useOrg} from "../../lib/counts";
import {t as tr, intlLocale} from "../../lib/i18n";

/* M7 (sớm) — Tổng quan "Hôm nay công ty làm gì".

   Bốn câu trả lời trên một màn: agent nào đang làm gì · cái gì đang chờ anh ·
   hôm nay đã chi bao nhiêu so với ngân sách · việc nào vừa chạy xong/lỗi.
   Bốn nguồn gọi SONG SONG một lần (Promise.allSettled) — nguồn nào lỗi thì chỉ
   khối đó báo lỗi, các khối khác vẫn hiện (trước v2: trang này gọi 7 API rồi
   mới gọi tiếp 2 API nối đuôi, và vẽ dashboard kiểu mockup với doanh thu).

   Giới hạn nói thẳng: chưa có API "lượt chạy gần đây" toàn công ty, nên khối
   "Vừa chạy" đọc lượt cuối của từng việc từ /api/work (cập nhật gần nhất trước). */

type Work = any; type Load<T> = {data?: T; error?: unknown};
const money = (v?: number | null) => { const n = Number(v || 0); return n === 0 ? "$0" : "$" + (n < 1 ? n.toFixed(3) : n.toFixed(2)); };
const when = (iso?: string | null) => {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z"), s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return tr("overview.vua_xong"); if (s < 3600) return tr("overview.phut_truoc", {p0: Math.floor(s / 60)}); if (s < 86400) return tr("overview.gio_truoc", {p0: Math.floor(s / 3600)});
  return new Intl.DateTimeFormat(intlLocale(), {day: "2-digit", month: "2-digit"}).format(d);
};

function useToday() {
  const [work, setWork] = useState<Load<any>>({}), [inbox, setInbox] = useState<Load<any>>({});
  const [costs, setCosts] = useState<Load<any>>({}), [budgets, setBudgets] = useState<Load<any>>({});
  const load = useCallback(async () => {
    const [w, i, c, b] = await Promise.allSettled([apiWork.list({}), apiInboxHub.items(), apiCosts.overview(7), apiCosts.budgets()]);
    const pack = (r: PromiseSettledResult<any>) => r.status === "fulfilled" ? {data: r.value} : {error: r.reason};
    setWork(pack(w)); setInbox(pack(i)); setCosts(pack(c)); setBudgets(pack(b));
  }, []);
  useEffect(() => { load(); }, [load]);
  /* có lượt đang chạy → làm mới 15 giây/lần cho "đang làm" khỏi cũ */
  useEffect(() => {
    if (!work.data?.items?.some((t: Work) => t.runs?.running)) return;
    const h = setInterval(load, 15000); return () => clearInterval(h);
  }, [work.data, load]);
  return {work, inbox, costs, budgets, load};
}

export function TodayOverview() {
  const {work, inbox, costs, budgets, load} = useToday();
  const counts = useCounts();
  const org = useOrg();
  const [today, setToday] = useState("");
  useEffect(() => { setToday(new Intl.DateTimeFormat(intlLocale(), {weekday: "long", day: "numeric", month: "long"}).format(new Date())); }, []);

  const items: Work[] = work.data?.items || [];
  const running = useMemo(() => items.filter(t => t.runs?.running), [items]);
  const workingAgents = useMemo(() => {
    const m = new Map<number, {who: any; tasks: Work[]; cost: number}>();
    for (const t of items) {
      if (!(t.runs?.running || (t.status === "in_progress" && t.assignee?.type === "agent"))) continue;
      const k = t.assignee?.id ?? -t.id;
      const e = m.get(k) || {who: t.assignee, tasks: [], cost: 0};
      e.tasks.push(t); e.cost += t.runs?.cost_usd || 0; m.set(k, e);
    }
    return Array.from(m.values()).sort((a, b) => Number(b.tasks.some(t => t.runs?.running)) - Number(a.tasks.some(t => t.runs?.running)));
  }, [items]);
  const recent = useMemo(() => items.filter(t => t.runs?.count > 0).sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || ""))).slice(0, 6), [items]);
  const approvals: any[] = useMemo(() => (inbox.data?.groups || []).find((g: any) => g.key === "approvals")?.items || [], [inbox.data]);
  const c = work.data?.counts || {};
  const pending = inbox.data?.counts?.by_group?.approvals ?? approvals.length;
  const review = inbox.data?.counts?.by_group?.review ?? 0;
  const spentToday = costs.data?.totals?.today ?? null;
  const allBudgets: any[] = budgets.data?.budgets || [];
  const main = allBudgets.find(b => b.scope_type === "company") || [...allBudgets].sort((a, b) => b.pct - a.pct)[0];
  const lit = Math.min(6, workingAgents.length);
  const loading = !work.data && !work.error;

  const sentence = loading ? tr("overview.dang_xem_cong_ty_lam")
    : workingAgents.length ? tr("overview.agent_dang_lam_viec", {p0: workingAgents.length, p1: workingAgents.reduce((n, a) => n + a.tasks.length, 0)})
    : tr("overview.chua_agent_nao_dang_lam");
  const ask = loading ? "" : pending ? tr("overview.viec_cho_anh_duyet", {p0: pending, p1: review ? `, ${review} kết quả chờ xem` : ""}) : review ? tr("overview.ket_qua_cho_anh_xem", {p0: review}) : tr("overview.khong_co_gi_cho_anh");

  return <div className="ov" data-testid="overview">
    {org.companies.length === 0 && counts.companies === 0 && <Notice tone="wait" testId="ov-onboarding">
      <b>{tr("overview.chua_co_cong_ty_nao")}</b> {tr("overview.dung_cong_ty_trong_4")}{" "}
      <Link href="/onboarding" className="ui-link">{tr("overview.bat_dau")}</Link>
    </Notice>}

    <section className="ov-hero" aria-labelledby="ov-h">
      <div className="ov-hero-copy">
        <p className="ov-date">{today || "\u00a0"}</p>
        <h2 id="ov-h">{sentence}<br/><span>{ask}</span></h2>
        <div className="ui-confirm-actions">
          <ButtonLink href={pending ? "/app/inbox?group=approvals" : "/app/inbox"} variant={pending ? "primary" : "secondary"} icon="inbox">
            {pending ? tr("overview.duyet_viec", {p0: pending}) : tr("overview.mo_hop_viec")}</ButtonLink>
          <ButtonLink href="/app/work?new=1" icon="plus">{tr("overview.giao_viec_moi")}</ButtonLink>
        </div>
      </div>
      <figure className="ov-mascot" aria-label={tr("overview.be_cang_cua_so_sang", {p0: lit})}>
        <BeCang mood={workingAgents.length ? "working" : pending ? "hello" : "sleep"} size={168} lit={lit}/>
        <figcaption>{lit ? tr("overview.cua_so_sang_agent_dang", {p0: lit, p1: lit}) : tr("overview.cua_so_tat_doi_dang")}</figcaption>
      </figure>
    </section>

    <div className="ov-strip" role="list" aria-label={tr("overview.so_lieu_hom_nay")}>
      <Link role="listitem" href="/app/work" className="ov-stat"><small>{tr("overview.dang_chay")}</small><b className="ui-num">{loading ? "–" : running.length}</b>
        <span>{c.in_progress || 0} {tr("overview.viec_dang_lam")}</span></Link>
      <Link role="listitem" href="/app/inbox?group=approvals" className={"ov-stat" + (pending ? " is-wait" : "")}><small>{tr("overview.cho_anh_duyet")}</small>
        <b className="ui-num">{inbox.data ? pending : "–"}</b><span>{inbox.data?.counts?.overdue ? tr("overview.qua_han", {p0: inbox.data.counts.overdue}) : tr("overview.mot_cham_tren_dien_thoai")}</span></Link>
      <Link role="listitem" href="/app/work?view=board" className={"ov-stat" + (c.blocked ? " is-risk" : "")}><small>{tr("overview.bi_chan")}</small>
        <b className="ui-num">{loading ? "–" : c.blocked || 0}</b><span>{c.review || 0} {tr("overview.cho_review")}</span></Link>
      <Link role="listitem" href="/app/costs" className="ov-stat is-wide"><small>{tr("overview.chi_hom_nay")}</small>
        <b className="ui-num">{spentToday === null ? "–" : money(spentToday)}</b>
        {main ? <><div className={"ui-meter" + (main.pct >= 90 ? " is-risk" : main.pct >= main.warn_pct ? " is-wait" : "")} aria-hidden="true">
          <i style={{width: `${Math.min(100, main.pct)}%`}}/></div>
          <span>{main.scope_name || main.name}: {money(main.amount_spent)} / {money(main.amount_limit)} ({main.pct}%)</span></>
          : <span>{budgets.data ? tr("overview.chua_dat_ngan_sach_dat") : tr("overview.k7_ngay") + money(costs.data?.totals?.d7)}</span>}
      </Link>
    </div>

    <div className="ov-grid">
      <section className="ui-panel" aria-labelledby="ov-agents">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-agents">{tr("overview.agent_dang_lam")}</h2><p>{tr("overview.theo_viec_dang_chay_hoac")}</p></div>
          <Link className="ui-link" href="/app/team?tab=ai">{tr("overview.ca_doi")} <Icon name="chevron-right" size={12}/></Link></header>
        {work.error ? <div className="ui-panel-body"><ErrorBanner error={work.error} onRetry={load} context={tr("overview.tai_viec")}/></div>
          : loading ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={36}/><Skeleton h={36}/><Skeleton h={36}/></div>
          : workingAgents.length === 0 ? <EmptyState compact mood="ngu" title={tr("overview.doi_dang_nghi")}>{tr("overview.giao_mot_viec_cho_agent")}</EmptyState>
          : <div className="ui-list">{workingAgents.slice(0, 6).map(a => { const live = a.tasks.some(t => t.runs?.running); const t = a.tasks[0];
            return <Link key={a.who?.id ?? t.id} href={`/app/work?peek=${t.id}`} className="ui-row" data-testid="ov-agent">
              <span className={"ui-ava " + (a.who?.type === "agent" ? "is-agent" : "is-human")}>{a.who?.type === "agent" ? <Icon name="sparkle" size={11} strokeWidth={2}/> : (a.who?.name || "?").slice(0, 1)}</span>
              <span className="ui-row-main"><span className="ui-row-title">{a.who?.name || tr("overview.chua_giao")}</span>
                <span className="ui-row-meta">{t.title}{a.tasks.length > 1 ? tr("overview.viec", {p0: a.tasks.length - 1}) : ""}</span></span>
              <span className="ui-row-end">{live ? <StatusPill tone="ok" live>{tr("overview.dang_chay")}</StatusPill> : <StatusPill tone="neutral">{tr("overview.dang_lam")}</StatusPill>}
                <span className="ui-num ov-cost">{money(a.cost)}</span></span>
            </Link>; })}</div>}
      </section>

      <section className="ui-panel" aria-labelledby="ov-wait">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-wait">{tr("overview.cho_anh_duyet")}</h2><p>{tr("overview.duyet_hoac_tu_choi_trong")}</p></div>
          <Link className="ui-link" href="/app/inbox?group=approvals">{tr("overview.hop_viec")} <Icon name="chevron-right" size={12}/></Link></header>
        {inbox.error ? <div className="ui-panel-body"><ErrorBanner error={inbox.error} onRetry={load} context={tr("overview.tai_hop_viec")}/></div>
          : !inbox.data ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={36}/><Skeleton h={36}/></div>
          : approvals.length === 0 ? <EmptyState compact mood="duyet-xong" title={tr("overview.khong_co_gi_cho_duyet")}>{tr("overview.phe_duyet_moi_se_hien")}</EmptyState>
          : <div className="ui-list">{approvals.slice(0, 5).map((it: any) => { const a = it.approval || {};
            return <Link key={it.key} href="/app/inbox?group=approvals" className="ui-row" data-testid="ov-approval">
              <span className="ui-sdot is-pending" aria-hidden="true"/>
              <span className="ui-row-main"><span className="ui-row-title">{a.action || it.title}</span>
                <span className="ui-row-meta">{[kindLabel(a.kind), a.requester && tr("inbox.xin_short", {p0: a.requester}), deadlineText(a)].filter(Boolean).join(" · ")}</span></span>
              <span className="ui-row-end">{a.overdue ? <StatusPill tone="risk">{tr("overview.qua_han_2")}</StatusPill> : <StatusPill tone={a.risk === "high" || a.risk === "critical" ? "risk" : "wait"}>{riskLabel(a.risk)}</StatusPill>}</span>
            </Link>; })}</div>}
      </section>

      <section className="ui-panel ov-span" aria-labelledby="ov-recent">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-recent">{tr("overview.vua_chay")}</h2><p>{tr("overview.luot_cuoi_cua_tung_viec")}</p></div>
          <Link className="ui-link" href="/app/work">{tr("overview.cong_viec")} <Icon name="chevron-right" size={12}/></Link></header>
        {work.error ? null : loading ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={32}/><Skeleton h={32}/><Skeleton h={32}/></div>
          : recent.length === 0 ? <EmptyState compact mood="chao" title={tr("overview.chua_co_luot_chay_nao")}>{tr("overview.khi_agent_lam_viec_qua")}</EmptyState>
          : <div className="ui-table-wrap"><table className="ui-table">
            <thead><tr><th>{tr("overview.viec_2")}</th><th className="ov-sm-hide">{tr("overview.ai_lam")}</th><th>{tr("overview.luot_cuoi")}</th><th className="is-num ov-sm-hide">{tr("overview.luot")}</th><th className="is-num">{tr("overview.chi_phi")}</th><th className="is-num ov-sm-hide">{tr("overview.cap_nhat")}</th></tr></thead>
            <tbody>{recent.map(t => <tr key={t.id}>
              <td><Link href={`/app/work?peek=${t.id}`} className="ov-task"><span className="ui-mono">#{t.id}</span> {t.title}</Link></td>
              <td className="ov-sm-hide"><span className="ui-who">{t.assignee?.name || "—"}</span></td>
              <td>{t.runs.running ? <StatusPill tone="ok" live>{tr("overview.dang_chay")}</StatusPill> : t.runs.last_status === "failed" ? <StatusPill tone="risk">{tr("overview.loi")}</StatusPill>
                : <StatusPill tone="ok">Xong</StatusPill>}</td>
              <td className="is-num ov-sm-hide">{t.runs.count}{t.runs.failed ? <small> · {t.runs.failed} {tr("overview.loi_2")}</small> : null}</td>
              <td className="is-num">{money(t.runs.cost_usd)}</td>
              <td className="is-num ov-sm-hide"><small>{when(t.updated_at)}</small></td>
            </tr>)}</tbody></table></div>}
      </section>

      <section className="ui-panel" aria-labelledby="ov-budget">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-budget">{tr("overview.ngan_sach")}</h2><p>{tr("overview.canh_bao_dung_mem_dung")}</p></div>
          <Link className="ui-link" href="/app/costs?tab=budgets">{tr("overview.chi_phi")} <Icon name="chevron-right" size={12}/></Link></header>
        {budgets.error ? <div className="ui-panel-body"><ErrorBanner error={budgets.error} onRetry={load} context={tr("overview.tai_ngan_sach")}/></div>
          : !budgets.data ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={30}/><Skeleton h={30}/></div>
          : allBudgets.length === 0 ? <EmptyState compact mood="chao" title={tr("overview.chua_dat_ngan_sach")}>{tr("overview.dat_han_muc_cho_cong")}</EmptyState>
          : <div className="ui-list">{[...allBudgets].sort((a, b) => b.pct - a.pct).slice(0, 4).map(b => <Link key={b.id} href="/app/costs?tab=budgets" className="ui-row ov-budget">
              <span className="ui-row-main"><span className="ui-row-title">{b.scope_name || b.name}</span>
                <span className={"ui-meter" + (b.threshold_state === "exhausted" ? " is-risk" : b.threshold_state !== "ok" ? " is-wait" : "")}><i style={{width: `${Math.min(100, b.pct)}%`}}/></span></span>
              <span className="ui-row-end"><span className="ui-num">{b.pct}%</span></span>
            </Link>)}</div>}
      </section>
    </div>
  </div>;
}
