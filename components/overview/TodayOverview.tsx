"use client";
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
import {getOrg} from "../../lib/counts";

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
  if (s < 60) return "vừa xong"; if (s < 3600) return `${Math.floor(s / 60)} phút trước`; if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  return new Intl.DateTimeFormat("vi-VN", {day: "2-digit", month: "2-digit"}).format(d);
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
  const org = getOrg();
  const [today, setToday] = useState("");
  useEffect(() => { setToday(new Intl.DateTimeFormat("vi-VN", {weekday: "long", day: "numeric", month: "long"}).format(new Date())); }, []);

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

  const sentence = loading ? "Đang xem công ty làm gì…"
    : workingAgents.length ? `${workingAgents.length} agent đang làm ${workingAgents.reduce((n, a) => n + a.tasks.length, 0)} việc.`
    : "Chưa agent nào đang làm.";
  const ask = loading ? "" : pending ? `${pending} việc chờ anh duyệt${review ? `, ${review} kết quả chờ xem` : ""}.` : review ? `${review} kết quả chờ anh xem.` : "Không có gì chờ anh.";

  return <div className="ov" data-testid="overview">
    {org.companies.length === 0 && counts.companies === 0 && <Notice tone="wait" testId="ov-onboarding">
      <b>Chưa có công ty nào.</b> Dựng công ty trong 4 bước — đặt tên, chọn mẫu, kết nối OpenClaw, giao việc đầu tiên cho Nina.{" "}
      <Link href="/onboarding" className="ui-link">Bắt đầu</Link>
    </Notice>}

    <section className="ov-hero" aria-labelledby="ov-h">
      <div className="ov-hero-copy">
        <p className="ov-date">{today || "\u00a0"}</p>
        <h2 id="ov-h">{sentence}<br/><span>{ask}</span></h2>
        <div className="ui-confirm-actions">
          <ButtonLink href={pending ? "/app/inbox?group=approvals" : "/app/inbox"} variant={pending ? "primary" : "secondary"} icon="inbox">
            {pending ? `Duyệt ${pending} việc` : "Mở Hộp việc"}</ButtonLink>
          <ButtonLink href="/app/work?new=1" icon="plus">Giao việc mới</ButtonLink>
        </div>
      </div>
      <figure className="ov-mascot" aria-label={`Bé Càng: ${lit} cửa sổ sáng, mỗi cửa sổ là một agent đang làm`}>
        <BeCang mood={workingAgents.length ? "working" : pending ? "hello" : "sleep"} size={168} lit={lit}/>
        <figcaption>{lit ? `${lit} cửa sổ sáng = ${lit} agent đang làm` : "Cửa sổ tắt — đội đang nghỉ"}</figcaption>
      </figure>
    </section>

    <div className="ov-strip" role="list" aria-label="Số liệu hôm nay">
      <Link role="listitem" href="/app/work" className="ov-stat"><small>Đang chạy</small><b className="ui-num">{loading ? "–" : running.length}</b>
        <span>{c.in_progress || 0} việc đang làm</span></Link>
      <Link role="listitem" href="/app/inbox?group=approvals" className={"ov-stat" + (pending ? " is-wait" : "")}><small>Chờ anh duyệt</small>
        <b className="ui-num">{inbox.data ? pending : "–"}</b><span>{inbox.data?.counts?.overdue ? `${inbox.data.counts.overdue} quá hạn` : "một chạm trên điện thoại"}</span></Link>
      <Link role="listitem" href="/app/work?view=board" className={"ov-stat" + (c.blocked ? " is-risk" : "")}><small>Bị chặn</small>
        <b className="ui-num">{loading ? "–" : c.blocked || 0}</b><span>{c.review || 0} chờ review</span></Link>
      <Link role="listitem" href="/app/costs" className="ov-stat is-wide"><small>Chi hôm nay</small>
        <b className="ui-num">{spentToday === null ? "–" : money(spentToday)}</b>
        {main ? <><div className={"ui-meter" + (main.pct >= 90 ? " is-risk" : main.pct >= main.warn_pct ? " is-wait" : "")} aria-hidden="true">
          <i style={{width: `${Math.min(100, main.pct)}%`}}/></div>
          <span>{main.scope_name || main.name}: {money(main.amount_spent)} / {money(main.amount_limit)} ({main.pct}%)</span></>
          : <span>{budgets.data ? "Chưa đặt ngân sách — đặt ở Chi phí" : "7 ngày: " + money(costs.data?.totals?.d7)}</span>}
      </Link>
    </div>

    <div className="ov-grid">
      <section className="ui-panel" aria-labelledby="ov-agents">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-agents">Agent đang làm</h2><p>Theo việc đang chạy hoặc đang làm</p></div>
          <Link className="ui-link" href="/app/team?tab=ai">Cả đội <Icon name="chevron-right" size={12}/></Link></header>
        {work.error ? <div className="ui-panel-body"><ErrorBanner error={work.error} onRetry={load} context="Tải việc"/></div>
          : loading ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={36}/><Skeleton h={36}/><Skeleton h={36}/></div>
          : workingAgents.length === 0 ? <EmptyState compact mood="ngu" title="Đội đang nghỉ">Giao một việc cho agent — agent nhận ngay, tiến độ hiện ở đây.</EmptyState>
          : <div className="ui-list">{workingAgents.slice(0, 6).map(a => { const live = a.tasks.some(t => t.runs?.running); const t = a.tasks[0];
            return <Link key={a.who?.id ?? t.id} href={`/app/work?peek=${t.id}`} className="ui-row" data-testid="ov-agent">
              <span className={"ui-ava " + (a.who?.type === "agent" ? "is-agent" : "is-human")}>{a.who?.type === "agent" ? <Icon name="sparkle" size={11} strokeWidth={2}/> : (a.who?.name || "?").slice(0, 1)}</span>
              <span className="ui-row-main"><span className="ui-row-title">{a.who?.name || "Chưa giao"}</span>
                <span className="ui-row-meta">{t.title}{a.tasks.length > 1 ? ` · +${a.tasks.length - 1} việc` : ""}</span></span>
              <span className="ui-row-end">{live ? <StatusPill tone="ok" live>Đang chạy</StatusPill> : <StatusPill tone="neutral">Đang làm</StatusPill>}
                <span className="ui-num ov-cost">{money(a.cost)}</span></span>
            </Link>; })}</div>}
      </section>

      <section className="ui-panel" aria-labelledby="ov-wait">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-wait">Chờ anh duyệt</h2><p>Duyệt hoặc từ chối trong Hộp việc</p></div>
          <Link className="ui-link" href="/app/inbox?group=approvals">Hộp việc <Icon name="chevron-right" size={12}/></Link></header>
        {inbox.error ? <div className="ui-panel-body"><ErrorBanner error={inbox.error} onRetry={load} context="Tải hộp việc"/></div>
          : !inbox.data ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={36}/><Skeleton h={36}/></div>
          : approvals.length === 0 ? <EmptyState compact mood="duyet-xong" title="Không có gì chờ duyệt">Phê duyệt mới sẽ hiện ở đây và trên chuông.</EmptyState>
          : <div className="ui-list">{approvals.slice(0, 5).map((it: any) => { const a = it.approval || {};
            return <Link key={it.key} href="/app/inbox?group=approvals" className="ui-row" data-testid="ov-approval">
              <span className="ui-sdot is-pending" aria-hidden="true"/>
              <span className="ui-row-main"><span className="ui-row-title">{a.action || it.title}</span>
                <span className="ui-row-meta">{[a.kind_vi, a.requester && `${a.requester} xin`, a.deadline_vi].filter(Boolean).join(" · ")}</span></span>
              <span className="ui-row-end">{a.overdue ? <StatusPill tone="risk">Quá hạn</StatusPill> : <StatusPill tone={a.risk === "high" || a.risk === "critical" ? "risk" : "wait"}>Rủi ro {String(a.risk_vi || "").toLowerCase()}</StatusPill>}</span>
            </Link>; })}</div>}
      </section>

      <section className="ui-panel ov-span" aria-labelledby="ov-recent">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-recent">Vừa chạy</h2><p>Lượt cuối của từng việc, mới nhất trước</p></div>
          <Link className="ui-link" href="/app/work">Công việc <Icon name="chevron-right" size={12}/></Link></header>
        {work.error ? null : loading ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={32}/><Skeleton h={32}/><Skeleton h={32}/></div>
          : recent.length === 0 ? <EmptyState compact mood="chao" title="Chưa có lượt chạy nào">Khi agent làm việc qua OpenClaw, mỗi lượt kèm chi phí hiện ở đây.</EmptyState>
          : <div className="ui-table-wrap"><table className="ui-table">
            <thead><tr><th>Việc</th><th className="ov-sm-hide">Ai làm</th><th>Lượt cuối</th><th className="is-num ov-sm-hide">Lượt</th><th className="is-num">Chi phí</th><th className="is-num ov-sm-hide">Cập nhật</th></tr></thead>
            <tbody>{recent.map(t => <tr key={t.id}>
              <td><Link href={`/app/work?peek=${t.id}`} className="ov-task"><span className="ui-mono">#{t.id}</span> {t.title}</Link></td>
              <td className="ov-sm-hide"><span className="ui-who">{t.assignee?.name || "—"}</span></td>
              <td>{t.runs.running ? <StatusPill tone="ok" live>Đang chạy</StatusPill> : t.runs.last_status === "failed" ? <StatusPill tone="risk">Lỗi</StatusPill>
                : <StatusPill tone="ok">Xong</StatusPill>}</td>
              <td className="is-num ov-sm-hide">{t.runs.count}{t.runs.failed ? <small> · {t.runs.failed} lỗi</small> : null}</td>
              <td className="is-num">{money(t.runs.cost_usd)}</td>
              <td className="is-num ov-sm-hide"><small>{when(t.updated_at)}</small></td>
            </tr>)}</tbody></table></div>}
      </section>

      <section className="ui-panel" aria-labelledby="ov-budget">
        <header className="ui-panel-head"><div className="ui-grow"><h2 id="ov-budget">Ngân sách</h2><p>Cảnh báo → dừng mềm → dừng cứng</p></div>
          <Link className="ui-link" href="/app/costs?tab=budgets">Chi phí <Icon name="chevron-right" size={12}/></Link></header>
        {budgets.error ? <div className="ui-panel-body"><ErrorBanner error={budgets.error} onRetry={load} context="Tải ngân sách"/></div>
          : !budgets.data ? <div className="ui-panel-body ui-skel-stack"><Skeleton h={30}/><Skeleton h={30}/></div>
          : allBudgets.length === 0 ? <EmptyState compact mood="chao" title="Chưa đặt ngân sách">Đặt hạn mức cho công ty, phòng hoặc agent để chi phí không vượt ý anh.</EmptyState>
          : <div className="ui-list">{[...allBudgets].sort((a, b) => b.pct - a.pct).slice(0, 4).map(b => <Link key={b.id} href="/app/costs?tab=budgets" className="ui-row ov-budget">
              <span className="ui-row-main"><span className="ui-row-title">{b.scope_name || b.name}</span>
                <span className={"ui-meter" + (b.threshold_state === "exhausted" ? " is-risk" : b.threshold_state !== "ok" ? " is-wait" : "")}><i style={{width: `${Math.min(100, b.pct)}%`}}/></span></span>
              <span className="ui-row-end"><span className="ui-num">{b.pct}%</span></span>
            </Link>)}</div>}
      </section>
    </div>
  </div>;
}
