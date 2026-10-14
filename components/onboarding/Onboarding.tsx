"use client";
import Link from "next/link";
import {useEffect, useState} from "react";
import {LogoLockup} from "../Logo";
import {BeCang} from "../BeCang";
import {Button, ButtonLink} from "../ui/Button";
import {Field} from "../ui/Field";
import {StatusPill, Tone} from "../ui/StatusPill";
import {ErrorBanner} from "../ui/EmptyState";
import {SkeletonRows} from "../ui/Skeleton";
import {apiTeam, apiV19, apiV9} from "../../lib/api";
import {activeOrganizationId} from "../../lib/auth";
import {refreshCounts} from "../../lib/counts";
import {useCompanyId} from "../../lib/prefs";

/* Bốn bước: đặt tên công ty → chọn mẫu (dựng phòng ban + agent trưởng phòng)
   → kết nối OpenClaw (doctor) → giao việc đầu tiên cho Nina (mục tiêu → Nina lập kế hoạch).
   Mỗi bước gọi đúng API đã có (/api/team/companies/from-template, /api/v19/openclaw/doctor,
   /api/v9/goals); không thêm API mới. Bước 3 cho đi tiếp kể cả khi gateway chưa sẵn sàng
   — nói rõ agent sẽ chưa chạy được. */

const STEPS = ["Tên công ty", "Chọn mẫu", "Kết nối OpenClaw", "Việc đầu tiên cho Nina"];
const DOC_TONE: Record<string, Tone> = {ok: "ok", warn: "wait", fail: "risk", skip: "neutral"};
const DOC_VI: Record<string, string> = {ok: "Ổn", warn: "Cần chú ý", fail: "Lỗi", skip: "Bỏ qua"};

export function Onboarding() {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [templates, setTemplates] = useState<any[] | null>(null), [tpl, setTpl] = useState("");
  const [company, setCompany] = useState<any>(null);
  const [doc, setDoc] = useState<any>(null), [docBusy, setDocBusy] = useState(false);
  const [goal, setGoal] = useState({title: "", objective: "", budget: "10"}), [goalDone, setGoalDone] = useState<any>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const [, setCompanyPref] = useCompanyId();

  useEffect(() => { apiTeam.templates().then((t: any) => { setTemplates(t || []); setTpl(t?.[0]?.key || ""); }).catch(e => { setTemplates([]); setError(e); }); }, []);
  const runDoctor = async () => { setDocBusy(true); try { setDoc(await apiV19.doctor()); } catch (e) { setDoc({status: "fail", checks: [{id: "api", label: "Gọi kiểm tra", status: "fail", detail: String((e as any)?.message || e), fix: "Kiểm tra dịch vụ API đang chạy."}]}); } finally { setDocBusy(false); } };
  useEffect(() => { if (step === 2 && !doc) runDoctor(); }, [step, doc]);

  async function build() {
    setBusy(true); setError(null);
    try {
      const r = await apiTeam.fromTemplate(tpl, name.trim());
      setCompany(r); setCompanyPref(r.company_id); refreshCounts(); setStep(2);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function assign() {
    setBusy(true); setError(null);
    try {
      const g = await apiV9.createGoal({organization_id: activeOrganizationId(), company_id: company?.company_id ?? null, title: goal.title.trim(),
        objective: goal.objective.trim(), budget_limit: goal.budget ? Number(goal.budget) : null, currency: "USD"});
      setGoalDone(g); try { localStorage.setItem("cc_onboarded", "1"); } catch { /* bỏ qua */ }
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const t = templates?.find(x => x.key === tpl);

  return <div className="ob">
    <header className="ob-top"><LogoLockup/><Link href="/app/os" className="ui-link">Bỏ qua, vào app</Link></header>
    <div className="ob-body">
      <ol className="ob-steps" aria-label="Các bước">
        {STEPS.map((s, i) => <li key={s} className={i === step ? "is-on" : i < step ? "is-done" : ""} aria-current={i === step ? "step" : undefined}><span>{i + 1}</span>{s}</li>)}
      </ol>
      <section className="ob-card" aria-live="polite">
        {error ? <ErrorBanner error={error} onClose={() => setError(null)} context="Dựng công ty"/> : null}

        {step === 0 && <form className="ui-form" onSubmit={e => { e.preventDefault(); if (name.trim().length >= 2) setStep(1); }}>
          <div><h1>Công ty của anh tên gì?</h1><p>Tên hiện trên menu, sơ đồ tổ chức và báo cáo. Đổi được sau.</p></div>
          <Field label="Tên công ty"><input value={name} onChange={e => setName(e.target.value)} placeholder="VD: Tiệm Gốm Mộc…" autoComplete="organization" autoFocus data-testid="ob-name"/></Field>
          <div className="ob-actions"><Button type="submit" variant="primary" disabled={name.trim().length < 2} data-testid="ob-next-0">Tiếp tục</Button></div>
        </form>}

        {step === 1 && <div className="ui-form">
          <div><h1>Chọn mẫu công ty</h1><p>Mỗi mẫu dựng sẵn phòng ban, trưởng phòng là agent và sơ đồ báo cáo. Thêm/bớt người sau ở Đội ngũ.</p></div>
          {!templates ? <SkeletonRows n={3} h={72}/> : <div className="ob-tpls" role="radiogroup" aria-label="Mẫu công ty">
            {templates.map(x => <button key={x.key} type="button" role="radio" aria-checked={tpl === x.key} className="ob-tpl" onClick={() => setTpl(x.key)} data-testid={`ob-tpl-${x.key}`}>
              <b>{x.name}</b><span>{x.description}</span>
              <small>{x.departments.length} phòng · {x.agents} agent — {x.departments.map((d: any) => d.name).join(", ")}</small>
            </button>)}</div>}
          <div className="ob-actions"><Button onClick={() => setStep(0)}>Quay lại</Button>
            <Button variant="primary" busy={busy} disabled={!tpl} onClick={build} data-testid="ob-build">{busy ? "Đang dựng…" : `Dựng “${name.trim()}”${t ? ` · ${t.agents} agent` : ""}`}</Button></div>
        </div>}

        {step === 2 && <div className="ui-form">
          <div><h1>Kết nối OpenClaw</h1><p>{company ? `Đã dựng “${company.company_name}”: ${company.departments} phòng, ${company.agents_bound}/${company.agents} agent có trên gateway. ` : ""}
            Kiểm tra gateway, model và agent để đội làm việc được.</p></div>
          {!doc ? <SkeletonRows n={4} h={40}/> : <ol className="oc-checks ob-checks">{(doc.checks || []).map((c: any) => <li key={c.id} className={"oc-check is-" + c.status}>
            <StatusPill tone={DOC_TONE[c.status] || "neutral"}>{DOC_VI[c.status] || c.status}</StatusPill>
            <div className="oc-check-body"><b>{c.label}</b><span>{c.detail}</span>{c.fix && <span className="oc-fix">→ {c.fix}</span>}</div></li>)}</ol>}
          {doc && doc.status !== "ok" && <p className="ob-note">Có thể đi tiếp: công ty và mục tiêu vẫn được tạo, nhưng agent chỉ chạy khi gateway ổn. Sửa sau ở Cài đặt › OpenClaw.</p>}
          <div className="ob-actions"><Button icon="pulse" busy={docBusy} onClick={runDoctor}>Kiểm tra lại</Button>
            <Button variant="primary" onClick={() => setStep(3)} data-testid="ob-next-2">Tiếp tục</Button></div>
        </div>}

        {step === 3 && !goalDone && <form className="ui-form" onSubmit={e => { e.preventDefault(); assign(); }}>
          <div><h1>Giao việc đầu tiên cho Nina</h1><p>Nina là trợ lý điều hành: anh đưa kết quả muốn đạt, Nina chia thành kế hoạch theo phòng và gửi anh duyệt.</p></div>
          <Field label="Mục tiêu"><input value={goal.title} onChange={e => setGoal({...goal, title: e.target.value})} placeholder="VD: Ra mắt bộ sưu tập hè…" autoComplete="off" data-testid="ob-goal"/></Field>
          <Field label="Kết quả mong đợi"><textarea rows={3} value={goal.objective} onChange={e => setGoal({...goal, objective: e.target.value})} placeholder="VD: 50 đơn đầu tiên trong 2 tuần, có bài đăng mỗi ngày…"/></Field>
          <Field label="Ngân sách cho mục tiêu (USD)" hint="Chi phí model tối đa — chạm nấc sẽ hỏi anh trước"><input type="number" min={0} inputMode="decimal" value={goal.budget} onChange={e => setGoal({...goal, budget: e.target.value})}/></Field>
          <div className="ob-actions"><Button onClick={() => setStep(2)}>Quay lại</Button>
            <Button type="submit" variant="primary" busy={busy} disabled={goal.title.trim().length < 2 || goal.objective.trim().length < 4} data-testid="ob-assign">Giao cho Nina</Button></div>
        </form>}

        {step === 3 && goalDone && <div className="ob-done">
          <BeCang mood="done" size={120}/>
          <h1>Xong — Nina đã nhận mục tiêu #{goalDone.id}</h1>
          <p>Kế hoạch sẽ hiện ở Mục tiêu &amp; Kế hoạch để anh duyệt. Phê duyệt cũng báo ở Hộp việc.</p>
          <div className="ob-actions"><ButtonLink href="/app/strategy" variant="primary">Xem kế hoạch</ButtonLink><ButtonLink href="/app/os">Vào Tổng quan</ButtonLink></div>
        </div>}
      </section>
    </div>
  </div>;
}
