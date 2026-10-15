"use client";
/* M5b việc 9: Đào tạo agent — kho tri thức (nạp văn bản / tệp / URL, tra thử có trích dẫn),
   lỗ hổng kiến thức, khoá học (học từng module → bài học chờ duyệt → thi → chứng chỉ). */
import {useState} from "react";
import {apiA2A, apiLearning, apiSharedMemory} from "../lib/api";
import {t as tr} from "../lib/i18n";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

type Sub = "library" | "gaps" | "courses" | "skills" | "evals" | "a2a";

function tokenRole(): string {
  try {
    const t = localStorage.getItem("clawcompany_token") || "";
    return JSON.parse(atob((t.split(".")[1] || "").replace(/-/g, "+").replace(/_/g, "/"))).role || "";
  } catch { return ""; }
}

const fmt = (iso?: string | null) => iso ? new Date(iso).toLocaleString() : "";
const ENR_TONE: Record<string, string> = {passed: "ok", failed: "risk", exam: "wait", stale: "wait", learning: "info"};

export function LearningHub() {
  const [sub, setSub] = useState<Sub>("library");
  const canEdit = ["owner", "admin", "manager"].includes(tokenRole());
  const opt = useLoad(async () => await apiSharedMemory.options(), null as Any);
  return <div className="lab" data-testid="learning-hub">
    <div className="ui-seg" role="tablist" style={{marginBottom: 12}}>
      {(["library", "courses", "skills", "evals", "gaps", "a2a"] as Sub[]).map(s => <button key={s} role="tab" aria-selected={sub === s} aria-pressed={sub === s}
        onClick={() => setSub(s)} data-testid={`learning-tab-${s}`}>{tr(`learning.tab_${s}` as any)}</button>)}
    </div>
    {sub === "library" && <Library canEdit={canEdit} o={opt.data}/>}
    {sub === "courses" && <Courses canEdit={canEdit} o={opt.data}/>}
    {sub === "skills" && <Skills canEdit={canEdit} o={opt.data}/>}
    {sub === "evals" && <Evals canEdit={canEdit}/>}
    {sub === "gaps" && <Gaps canEdit={canEdit}/>}
    {sub === "a2a" && <A2A canEdit={canEdit} o={opt.data}/>}
  </div>;
}

function ScopePicker({o, v, set}: {o: Any; v: Any; set: (x: Any) => void}) {
  const kinds = [["org", tr("learning.pv_to_chuc")], ["role", tr("learning.pv_nghe")], ["department", tr("learning.pv_phong")], ["project", tr("learning.pv_du_an")], ["agent", tr("learning.pv_agent")]];
  const list = !o ? [] : v.kind === "department" ? o.departments : v.kind === "project" ? o.projects : v.kind === "agent" ? o.agents : [];
  return <div className="ui-form-row">
    <Field label={tr("learning.pham_vi")}><select className="ui-select" value={v.kind} onChange={e => set({kind: e.target.value, id: ""})}>
      {kinds.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
    {v.kind === "role" && <Field label={tr("learning.chuc_danh_chua")} hint={tr("learning.chuc_danh_hint")}><input className="ui-input"
      value={v.id} onChange={e => set({...v, id: e.target.value})} placeholder={tr("learning.chuc_danh_ph")}/></Field>}
    {v.kind !== "org" && v.kind !== "role" && <Field label={tr("learning.thuoc")}><select className="ui-select" value={v.id} onChange={e => set({...v, id: e.target.value})}>
      <option value="">{tr("learning.chon")}</option>{list.map((x: Any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>}
  </div>;
}

const scopeBody = (v: Any) => v.kind === "org" || !v.id ? {} : v.kind === "role" ? {role_keyword: String(v.id).trim()}
  : {[`${v.kind}_id`]: Number(v.id)};

function Library({canEdit, o}: {canEdit: boolean; o: Any}) {
  const q = useLoad(async () => (await apiLearning.docs()).items as Any[], []);
  const act = useAction();
  const [mode, setMode] = useState<"text" | "url" | "file">("text");
  const [f, setF] = useState<Any>({title: "", content: "", url: "", core: false});
  const [file, setFile] = useState<File | null>(null);
  const [scope, setScope] = useState<Any>({kind: "org", id: ""});
  const [s, setS] = useState(""), [res, setRes] = useState<Any>(null);
  const add = () => act.run("add", async () => {
    const extra = {...scopeBody(scope), is_core: f.core};
    const r = mode === "file" && file ? await apiLearning.upload(file, {title: f.title, ...extra})
      : await apiLearning.addDoc(mode === "url" ? {url: f.url, title: f.title, ...extra} : {title: f.title, content: f.content, ...extra});
    setF({title: "", content: "", url: "", core: false}); setFile(null); await q.reload();
    return r;
  }, tr("learning.da_nap"));
  const ready = mode === "text" ? f.content.trim().length >= 20 && f.title.trim() : mode === "url" ? /^https?:\/\//.test(f.url) : !!file;
  return <LabBody q={q}>
    {act.error ? <ErrorBanner error={act.error} context={tr("learning.kho")} onClose={() => act.setError(null)}/> : null}
    {canEdit && <Panel title={tr("learning.nap_tai_lieu")} desc={tr("learning.nap_desc")}>
      <div className="ui-form" data-testid="kb-add">
        <div className="ui-seg">{(["text", "file", "url"] as const).map(m => <button key={m} type="button" aria-pressed={mode === m}
          onClick={() => setMode(m)}>{tr(`learning.nap_${m}` as any)}</button>)}</div>
        <Field label={tr("learning.tieu_de")}><input className="ui-input" value={f.title} onChange={e => setF({...f, title: e.target.value})}
          placeholder={mode === "text" ? tr("learning.tieu_de_ph") : tr("learning.tieu_de_tu_dong")}/></Field>
        {mode === "text" && <Field label={tr("learning.noi_dung")}><textarea className="ui-textarea" rows={6} value={f.content}
          onChange={e => setF({...f, content: e.target.value})} data-testid="kb-content"/></Field>}
        {mode === "url" && <Field label="URL"><input className="ui-input" value={f.url} placeholder="https://"
          onChange={e => setF({...f, url: e.target.value})}/></Field>}
        {mode === "file" && <Field label={tr("learning.tep")} hint={tr("learning.tep_hint")}><input type="file"
          accept=".pdf,.docx,.md,.markdown,.txt,.csv,.html,.htm" onChange={e => setFile(e.target.files?.[0] || null)}/></Field>}
        <ScopePicker o={o} v={scope} set={setScope}/>
        <label style={{display: "flex", gap: 6, alignItems: "flex-start"}}><input type="checkbox" checked={f.core}
          onChange={e => setF({...f, core: e.target.checked})} data-testid="kb-core"/>
          <span><b>{tr("learning.cot_loi")}</b><br/><small>{tr("learning.cot_loi_hint")}</small></span></label>
        <div className="ui-toolbar"><Button variant="primary" busy={act.busy === "add"} disabled={!ready} onClick={add}>{tr("learning.nap")}</Button></div>
      </div>
    </Panel>}
    <Panel title={tr("learning.tra_thu")} desc={tr("learning.tra_thu_desc")}>
      <form className="ui-toolbar" onSubmit={e => { e.preventDefault(); if (s.trim()) act.run("search", async () => setRes(await apiLearning.search(s))); }}>
        <input className="ui-input" style={{flex: "1 1 260px", width: "auto"}} value={s} onChange={e => setS(e.target.value)} placeholder={tr("learning.tra_thu_ph")}/>
        <Button type="submit" icon="search" busy={act.busy === "search"}>{tr("learning.tim")}</Button>
      </form>
      {res && (res.hits.length ? <div className="ui-list" style={{marginTop: 10}}>{res.hits.map((h: Any) => <div className="ui-row" key={h.chunk_id}
        style={{display: "block"}}><b>{h.cite}</b> <small>· {h.scope} · {tr("learning.diem")} {h.score}</small>
        <p className="ibx-pre" style={{margin: "4px 0 0"}}>{h.content.slice(0, 500)}{h.content.length > 500 ? "…" : ""}</p></div>)}
        {!res.found && <small className="tmGuide">{tr("learning.khong_du_tot")}</small>}</div>
        : <p className="ui-empty-line">{tr("learning.khong_thay")}</p>)}
    </Panel>
    <Panel title={tr("learning.kho")} desc={tr("learning.so_tai_lieu", {p0: q.data.length})}>
      <Table rows={q.data} empty={tr("learning.kho_trong")} testId="kb-list" cols={[
        {label: tr("learning.tai_lieu"), render: d => <><b>{d.title}</b><br/><small>#{d.id} · {d.chunks} {tr("learning.doan")} · {Math.round(d.chars / 1000)}k {tr("learning.ky_tu")}</small></>},
        {label: tr("learning.pham_vi"), render: d => <><Pill s="info" label={d.scope}/>{d.is_core ? <> <Pill s="ok" label={tr("learning.cot_loi_ngan")}/></> : null}</>},
        {label: tr("learning.nguon"), render: d => d.source_url ? <a href={d.source_url} target="_blank" rel="noreferrer">{tr(`learning.src_${d.source_type}` as any)}</a> : tr(`learning.src_${d.source_type}` as any), hideSm: true},
        {label: tr("learning.dong_bo"), render: d => <small>{fmt(d.synced_at)}</small>, hideSm: true},
        ...(canEdit ? [{label: "", render: (d: Any) => <div className="ui-toolbar">
          <Button size="sm" busy={act.busy === `core${d.id}`} onClick={() => act.run(`core${d.id}`, async () => {
            await apiLearning.patchDoc(d.id, {is_core: !d.is_core}); await q.reload(); }, d.is_core ? tr("learning.da_bo_cot_loi") : tr("learning.da_dat_cot_loi"))}>
            {d.is_core ? tr("learning.bo_cot_loi") : tr("learning.dat_cot_loi")}</Button>
          {d.source_url && <Button size="sm" busy={act.busy === `rs${d.id}`} onClick={() => act.run(`rs${d.id}`, async () => {
            const r = await apiLearning.resync(d.id); await q.reload(); return r; }, tr("learning.da_dong_bo"))}>{tr("learning.dong_bo_lai")}</Button>}
          <Button size="sm" onClick={() => { if (window.confirm(tr("learning.xac_nhan_xoa"))) act.run(`rm${d.id}`, async () => { await apiLearning.removeDoc(d.id); await q.reload(); }, tr("learning.da_xoa")); }}>{tr("learning.xoa")}</Button>
        </div>}] : []),
      ]}/>
    </Panel>
  </LabBody>;
}

function Gaps({canEdit}: {canEdit: boolean}) {
  const [status, setStatus] = useState("open");
  const q = useLoad(async () => (await apiLearning.gaps(status)).items as Any[], [], [status]);
  const act = useAction();
  return <LabBody q={q}>
    {act.error ? <ErrorBanner error={act.error} context={tr("learning.lo_hong")} onClose={() => act.setError(null)}/> : null}
    <Panel title={tr("learning.lo_hong")} desc={tr("learning.lo_hong_desc")}>
      <div className="ui-seg" style={{marginBottom: 10}}>{["open", "resolved", "all"].map(s => <button key={s} aria-pressed={status === s}
        onClick={() => setStatus(s)}>{tr(`learning.gap_${s}` as any)}</button>)}</div>
      <Table rows={q.data} empty={tr("learning.chua_co_lo_hong")} testId="kb-gaps" cols={[
        {label: tr("learning.cau_hoi"), render: g => <><b>{g.question}</b><br/><small>{g.source_vi}{g.who ? ` · ${g.who}` : ""}{g.task_id ? ` · #${g.task_id}` : ""}</small></>},
        {label: tr("learning.so_lan"), render: g => g.count, num: true},
        {label: tr("learning.cap_nhat"), render: g => <small>{fmt(g.updated_at)}</small>, hideSm: true},
        ...(canEdit ? [{label: "", render: (g: Any) => g.status === "open" ? <div className="ui-toolbar">
          <Button size="sm" onClick={() => {
            const v = window.prompt(tr("learning.nhap_id_tai_lieu")); if (v === null) return;
            act.run(`g${g.id}`, async () => { await apiLearning.resolveGap(g.id, {document_id: Number(v) || null}); await q.reload(); }, tr("learning.da_xu_ly"));
          }}>{tr("learning.da_bo_sung")}</Button>
          <Button size="sm" onClick={() => act.run(`d${g.id}`, async () => { await apiLearning.resolveGap(g.id, {dismiss: true}); await q.reload(); }, tr("learning.da_bo_qua"))}>{tr("learning.bo_qua")}</Button>
        </div> : <Pill s={g.status === "resolved" ? "ok" : "info"} label={tr(`learning.gap_${g.status}` as any)}/>}] : []),
      ]}/>
    </Panel>
  </LabBody>;
}

function Courses({canEdit, o}: {canEdit: boolean; o: Any}) {
  const q = useLoad(async () => (await apiLearning.courses()).items as Any[], []);
  const docs = useLoad(async () => (await apiLearning.docs()).items as Any[], []);
  const act = useAction();
  const [open, setOpen] = useState<number | null>(null);
  const [f, setF] = useState<Any>({title: "", goal: "", docs: [] as number[], agents: [] as number[], hour: "22", pass: 80});
  const toggle = (k: "docs" | "agents", id: number) => setF((x: Any) => ({...x, [k]: x[k].includes(id) ? x[k].filter((i: number) => i !== id) : [...x[k], id]}));
  const create = () => act.run("create", async () => {
    const c = await apiLearning.createCourse({title: f.title, goal: f.goal, document_ids: f.docs, agent_ids: f.agents,
      study_hour: f.hour === "" ? null : Number(f.hour), pass_score: Number(f.pass)});
    setF({title: "", goal: "", docs: [], agents: [], hour: "22", pass: 80}); await q.reload(); setOpen(c.id);
  }, tr("learning.da_tao_khoa"));
  return <LabBody q={q}>
    {act.error ? <ErrorBanner error={act.error} context={tr("learning.khoa_hoc")} onClose={() => act.setError(null)}/> : null}
    {open !== null && <CourseDetail id={open} canEdit={canEdit} onClose={() => { setOpen(null); q.reload(); }}/>}
    <Panel title={tr("learning.khoa_hoc")} desc={tr("learning.khoa_hoc_desc")}>
      <Table rows={q.data} empty={tr("learning.chua_co_khoa")} testId="course-list" cols={[
        {label: tr("learning.ten_khoa"), render: c => <button type="button" className="ibx-title-btn" onClick={() => setOpen(c.id)}><b>{c.title}</b></button>},
        {label: tr("learning.module"), render: c => c.modules, num: true},
        {label: tr("learning.hoc_vien"), render: c => `${c.passed}/${c.enrolled} ${tr("learning.dat")}`},
        {label: tr("learning.de_thi"), render: c => c.quiz_questions ? tr("learning.so_cau", {p0: c.quiz_questions}) : <Pill s="wait" label={tr("learning.chua_co_de")}/>},
        {label: tr("learning.gio_hoc"), render: c => c.study_hour === null ? tr("learning.thu_cong") : `${c.study_hour}:00`, hideSm: true},
      ]}/>
    </Panel>
    {canEdit && <Panel title={tr("learning.tao_khoa")} desc={tr("learning.tao_khoa_desc")}>
      <div className="ui-form" data-testid="course-form">
        <Field label={tr("learning.ten_khoa")}><input className="ui-input" value={f.title} onChange={e => setF({...f, title: e.target.value})}/></Field>
        <Field label={tr("learning.muc_tieu")}><input className="ui-input" value={f.goal} onChange={e => setF({...f, goal: e.target.value})}/></Field>
        <Field label={tr("learning.chon_module")}><div className="ui-chips">{docs.data.map((d: Any) => <button key={d.id} type="button" className="ui-chip"
          aria-pressed={f.docs.includes(d.id)} onClick={() => toggle("docs", d.id)}>{f.docs.includes(d.id) ? `${f.docs.indexOf(d.id) + 1}. ` : ""}{d.title}</button>)}</div></Field>
        <Field label={tr("learning.hoc_vien")}><div className="ui-chips">{(o?.agents || []).map((a: Any) => <button key={a.id} type="button" className="ui-chip"
          aria-pressed={f.agents.includes(a.id)} onClick={() => toggle("agents", a.id)}>{a.name}</button>)}</div></Field>
        <div className="ui-form-row">
          <Field label={tr("learning.gio_hoc_moi_ngay")} hint={tr("learning.gio_hoc_hint")}><select className="ui-select" value={f.hour} onChange={e => setF({...f, hour: e.target.value})}>
            <option value="">{tr("learning.thu_cong")}</option>{Array.from({length: 24}, (_, h) => <option key={h} value={h}>{h}:00</option>)}</select></Field>
          <Field label={tr("learning.diem_dat")}><input className="ui-input" type="number" min={50} max={100} value={f.pass} onChange={e => setF({...f, pass: e.target.value})}/></Field>
        </div>
        <div className="ui-toolbar"><Button variant="primary" busy={act.busy === "create"} disabled={f.title.trim().length < 3 || !f.docs.length} onClick={create}>{tr("learning.tao_khoa")}</Button></div>
      </div>
    </Panel>}
  </LabBody>;
}

function CourseDetail({id, canEdit, onClose}: {id: number; canEdit: boolean; onClose: () => void}) {
  const q = useLoad(async () => await apiLearning.course(id), null as Any, [id]);
  const act = useAction();
  const c = q.data;
  const run = (key: string, fn: () => Promise<Any>) => act.run(key, async () => { const r = await fn(); await q.reload(); return r; });
  const step = async (e: Any) => { const r: Any = await run(`s${e.id}`, () => apiLearning.step(e.id)); if (r?.message) window.alert(r.message); };
  return <Panel title={c ? c.title : tr("learning.dang_tai")} desc={c ? `${c.modules.length} module · ${tr("learning.diem_dat")} ${c.pass_score}` : ""}>
    {act.error ? <ErrorBanner error={act.error} context={tr("learning.khoa_hoc")} onClose={() => act.setError(null)}/> : null}
    {c && <div className="ui-form" data-testid={`course-${id}`}>
      {c.goal && <p>{c.goal}</p>}
      <ol style={{margin: 0, paddingLeft: 18}}>{c.modules.map((m: Any) => <li key={m.index}>{m.title} <small>#{m.document_id}</small></li>)}</ol>
      <b className="ibx-sub">{tr("learning.hoc_vien")}</b>
      <Table rows={c.enrollments} empty={tr("learning.chua_ghi_danh")} cols={[
        {label: "Agent", render: e => <b>{e.agent_name}</b>},
        {label: tr("learning.tien_do"), render: e => <>{Math.min(e.module_index, e.modules)}/{e.modules} <Pill s={ENR_TONE[e.status]} label={e.status_vi}/>
          {e.note ? <><br/><small>{e.note}</small></> : null}</>},
        {label: tr("learning.diem"), render: e => e.score === null ? "—" : `${e.score}${e.certified_at ? " 🎓" : ""}`, num: true},
        ...(canEdit ? [{label: "", render: (e: Any) => <div className="ui-toolbar">
          {e.status !== "passed" && <Button size="sm" variant="primary" busy={act.busy === `s${e.id}`} onClick={() => step(e)}>
            {e.status === "exam" ? tr("learning.thi_ngay") : tr("learning.hoc_buoi_tiep")}</Button>}
          {e.status === "failed" && <Button size="sm" onClick={() => run(`r${e.id}`, () => apiLearning.retake(e.id))}>{tr("learning.cho_thi_lai")}</Button>}
        </div>}] : []),
      ]}/>
      <b className="ibx-sub">{tr("learning.de_thi")} {c.quiz.length ? `(${c.quiz.length})` : ""}</b>
      {c.quiz.length ? <ol style={{margin: 0, paddingLeft: 18}}>{c.quiz.map((x: Any, i: number) => <li key={i}>{x.question}
        <ul>{x.options.map((op: string, j: number) => <li key={j} style={{fontWeight: j === x.answer ? 600 : 400}}>{op}{j === x.answer ? " ✓" : ""}</li>)}</ul></li>)}</ol>
        : <small className="tmGuide">{tr("learning.chua_co_de_giai_thich")}</small>}
      <div className="ui-toolbar">
        {canEdit && <Button busy={act.busy === "quiz"} onClick={() => run("quiz", () => apiLearning.genQuiz(id, {questions: 6}))}>
          {c.quiz.length ? tr("learning.soan_lai_de") : tr("learning.soan_de")}</Button>}
        <Button onClick={onClose}>{tr("learning.dong")}</Button>
      </div>
    </div>}
  </Panel>;
}


/* M5b việc 10: Skill Studio — đề xuất (agent qua Workshop hoặc quản lý soạn) → eval → duyệt → cài → rollback. */
// Ca kiểm nhập mỗi dòng: câu hỏi || phải có: a, b || không được có: c
function parseCases(text: string): Any[] {
  return text.split("\n").map(l => l.trim()).filter(Boolean).map(l => {
    const [prompt, ...rest] = l.split("||").map(x => x.trim());
    const pick = (re: RegExp) => (rest.find(r => re.test(r)) || "").replace(re, "").split(",").map(x => x.trim()).filter(Boolean);
    return {prompt, must_include: pick(/^(phải có|must)\s*:\s*/i), must_not_include: pick(/^(không được có|must not)\s*:\s*/i)};
  });
}
const casesText = (cs: Any[]) => (cs || []).map(c => [c.prompt, c.must_include?.length ? `phải có: ${c.must_include.join(", ")}` : "",
  c.must_not_include?.length ? `không được có: ${c.must_not_include.join(", ")}` : ""].filter(Boolean).join(" || ")).join("\n");
const V_TONE: Record<string, string> = {approved: "ok", in_review: "wait", draft: "info", rejected: "risk", superseded: "info"};

function Skills({canEdit, o}: {canEdit: boolean; o: Any}) {
  const q = useLoad(async () => (await apiLearning.skills()).items as Any[], []);
  const gov = useLoad(async () => { try { return await apiLearning.skillGovernance(); } catch { return null; } }, null as Any);
  const act = useAction();
  const [open, setOpen] = useState<number | null>(null);
  const [f, setF] = useState<Any>({slug: "", title: "", description: "", content: "", cases: ""});
  const create = () => act.run("create", async () => {
    const r = await apiLearning.skillCreate({slug: f.slug, title: f.title, description: f.description, content: f.content, eval_cases: parseCases(f.cases)});
    setF({slug: "", title: "", description: "", content: "", cases: ""}); await q.reload(); setOpen(r.id);
  }, tr("learning.sk_da_tao"));
  const g = gov.data;
  return <LabBody q={q}>
    {act.error ? <ErrorBanner error={act.error} context="Skill Studio" onClose={() => act.setError(null)}/> : null}
    {g && !g.governed && <div className="ui-banner is-error" data-testid="skill-governance">
      {tr("learning.sk_chua_kiem_soat", {p0: g.autonomous_mode})}
      {canEdit && <> <Button size="sm" variant="primary" busy={act.busy === "gov"} onClick={() => act.run("gov", async () => { await apiLearning.skillEnforce(); await gov.reload(); }, tr("learning.sk_da_bat"))}>{tr("learning.sk_bat_duyet")}</Button></>}
    </div>}
    {g && g.governed && <p className="tmGuide">{tr("learning.sk_da_kiem_soat")}</p>}
    {open !== null && <SkillDetail id={open} canEdit={canEdit} o={o} onClose={() => { setOpen(null); q.reload(); }}/>}
    <Panel title={tr("learning.sk_thu_vien")} desc={tr("learning.sk_thu_vien_desc")}>
      {canEdit && <div className="ui-toolbar" style={{marginBottom: 10}}><Button busy={act.busy === "sync"} onClick={() => act.run("sync", async () => {
        const r = await apiLearning.skillSync(); await q.reload(); return r; }, tr("learning.sk_da_dong_bo"))}>{tr("learning.sk_dong_bo")}</Button></div>}
      <Table rows={q.data} empty={tr("learning.sk_trong")} testId="skill-list" cols={[
        {label: tr("learning.sk_ky_nang"), render: s => <button type="button" className="ibx-title-btn" onClick={() => setOpen(s.id)}><b>{s.title}</b><br/><small>{s.slug} · {s.description}</small></button>},
        {label: tr("learning.sk_hien_hanh"), render: s => s.current_version ? `v${s.current_version}` : "—"},
        {label: tr("learning.sk_cho"), render: s => s.pending ? <Pill s="wait" label={String(s.pending)}/> : "0", num: true},
        {label: tr("learning.sk_da_cai"), render: s => s.installed, num: true},
      ]}/>
    </Panel>
    {canEdit && <Panel title={tr("learning.sk_soan")} desc={tr("learning.sk_soan_desc")}>
      <div className="ui-form" data-testid="skill-form">
        <div className="ui-form-row">
          <Field label={tr("learning.sk_ma")} hint={tr("learning.sk_ma_hint")}><input className="ui-input" value={f.slug} onChange={e => setF({...f, slug: e.target.value})}/></Field>
          <Field label={tr("learning.tieu_de")}><input className="ui-input" value={f.title} onChange={e => setF({...f, title: e.target.value})}/></Field>
        </div>
        <Field label={tr("learning.sk_mo_ta")} hint={tr("learning.sk_mo_ta_hint")}><input className="ui-input" maxLength={160} value={f.description} onChange={e => setF({...f, description: e.target.value})}/></Field>
        <Field label={tr("learning.noi_dung")}><textarea className="ui-textarea" rows={8} value={f.content} onChange={e => setF({...f, content: e.target.value})} placeholder={tr("learning.sk_noi_dung_ph")}/></Field>
        <Field label={tr("learning.sk_ca_kiem")} hint={tr("learning.sk_ca_kiem_hint")}><textarea className="ui-textarea" rows={3} value={f.cases} onChange={e => setF({...f, cases: e.target.value})}/></Field>
        <div className="ui-toolbar"><Button variant="primary" busy={act.busy === "create"} disabled={!f.slug || !f.description || f.content.trim().length < 40} onClick={create}>{tr("learning.sk_luu_nhap")}</Button></div>
      </div>
    </Panel>}
  </LabBody>;
}

function SkillDetail({id, canEdit, o, onClose}: {id: number; canEdit: boolean; o: Any; onClose: () => void}) {
  const q = useLoad(async () => await apiLearning.skill(id), null as Any, [id]);
  const act = useAction();
  const [agent, setAgent] = useState(""), [targets, setTargets] = useState<number[]>([]);
  const [cases, setCases] = useState<Record<number, string>>({});
  const s = q.data;
  const run = (key: string, fn: () => Promise<Any>, ok?: string) => act.run(key, async () => { const r = await fn(); await q.reload(); return r; }, ok);
  return <Panel title={s ? `${s.title} (${s.slug})` : tr("learning.dang_tai")} desc={s ? (s.current_version ? tr("learning.sk_dang_dung", {p0: s.current_version}) : tr("learning.sk_chua_duyet")) : ""}>
    {act.error ? <ErrorBanner error={act.error} context="Skill Studio" onClose={() => act.setError(null)}/> : null}
    {s && <div className="ui-form" data-testid={`skill-${id}`}>
      {s.versions.map((v: Any) => <details key={v.id} className="ui-row" style={{display: "block"}} open={v.status === "draft" || v.status === "in_review"}>
        <summary><b>v{v.version}</b> <Pill s={V_TONE[v.status]} label={v.status_vi}/> <small>{v.source_vi}{v.origin_agent ? ` · ${v.origin_agent}` : ""} · {v.description}</small></summary>
        <pre className="ibx-pre" style={{maxHeight: 260, overflow: "auto"}}>{v.content}</pre>
        {v.scan && <small>{tr("learning.sk_quet")}: {v.scan.state} ({v.scan.critical || 0}/{v.scan.warn || 0})</small>}
        {v.eval_report && <div><b className="ibx-sub">Eval</b> <span>{tr("learning.sk_eval_ket_qua", {p0: v.eval_report.with_skill, p1: v.eval_report.total, p2: v.eval_report.baseline, p3: v.eval_report.agent})}</span>
          <ul>{v.eval_report.cases.map((c: Any, i: number) => <li key={i}>{c.prompt} — {c.with_skill.passed ? "✓" : "✗"} / {c.baseline.passed ? "✓" : "✗"}
            {c.with_skill.missing?.length ? <small> · {tr("learning.sk_thieu")}: {c.with_skill.missing.join(", ")}</small> : null}</li>)}</ul></div>}
        {canEdit && (v.status === "draft" || v.status === "rejected") && <>
          <Field label={tr("learning.sk_ca_kiem")} hint={tr("learning.sk_ca_kiem_hint")}><textarea className="ui-textarea" rows={3}
            value={cases[v.id] ?? casesText(v.eval_cases)} onChange={e => setCases({...cases, [v.id]: e.target.value})}/></Field>
          <div className="ui-toolbar">
            {cases[v.id] !== undefined && <Button size="sm" onClick={() => run(`c${v.id}`, () => apiLearning.versionUpdate(v.id, {eval_cases: parseCases(cases[v.id])}), tr("learning.sk_da_luu_ca"))}>{tr("learning.sk_luu_ca")}</Button>}
            <select className="ui-select" style={{width: "auto"}} value={agent} onChange={e => setAgent(e.target.value)}>
              <option value="">{tr("learning.sk_chon_agent_eval")}</option>{(o?.agents || []).map((a: Any) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
            <Button size="sm" disabled={!agent || !v.eval_cases.length} busy={act.busy === `e${v.id}`} onClick={() => run(`e${v.id}`, () => apiLearning.versionEval(v.id, Number(agent)), tr("learning.sk_da_eval"))}>{tr("learning.sk_chay_eval")}</Button>
            <Button size="sm" variant="primary" busy={act.busy === `s${v.id}`} onClick={() => run(`s${v.id}`, () => apiLearning.versionSubmit(v.id), tr("learning.sk_da_gui"))}>{tr("learning.sk_gui_duyet")}</Button>
          </div></>}
        {canEdit && v.status === "superseded" && <Button size="sm" busy={act.busy === `r${v.id}`} onClick={() => { if (window.confirm(tr("learning.sk_xac_nhan_rollback"))) run(`r${v.id}`, () => apiLearning.skillRollback(id, v.id), tr("learning.sk_da_rollback")); }}>{tr("learning.sk_rollback")}</Button>}
      </details>)}
      <b className="ibx-sub">{tr("learning.sk_noi_cai")}</b>
      <Table rows={s.installs} empty={tr("learning.sk_chua_cai")} rowKey={(r: Any) => r.agent_id} cols={[
        {label: "Agent", render: (i: Any) => i.agent}, {label: tr("learning.sk_phien_ban"), render: (i: Any) => `v${i.version}`},
        {label: tr("learning.sk_trang_thai"), render: (i: Any) => <>{i.status === "installed" ? <Pill s="ok" label={tr("learning.sk_da_cai_1")}/> : <Pill s="risk" label={tr("learning.sk_loi")}/>}{i.error ? <><br/><small>{i.error}</small></> : null}</>},
      ]}/>
      {canEdit && s.current_version_id && <><Field label={tr("learning.sk_cai_cho")}><div className="ui-chips">{(o?.agents || []).map((a: Any) => <button key={a.id} type="button" className="ui-chip"
          aria-pressed={targets.includes(a.id)} onClick={() => setTargets(t => t.includes(a.id) ? t.filter(x => x !== a.id) : [...t, a.id])}>{a.name}</button>)}</div></Field>
        <div className="ui-toolbar"><Button variant="primary" disabled={!targets.length} busy={act.busy === "inst"} onClick={() => run("inst", () => apiLearning.skillInstall(id, targets), tr("learning.sk_da_cai_xong"))}>{tr("learning.sk_cai", {p0: s.current_version})}</Button></div></>}
      <div className="ui-toolbar"><Button onClick={onClose}>{tr("learning.dong")}</Button></div>
    </div>}
  </Panel>;
}


/* M6 việc 11: bộ đánh giá theo vai — mỗi ca chạy k lần, agent phải đúng cả k lần. */
function Evals({canEdit}: {canEdit: boolean}) {
  const q = useLoad(async () => (await apiLearning.suites()).items as Any[], []);
  const act = useAction();
  const [f, setF] = useState<Any>({id: null, title: "", role_keyword: "", k: 3, cases: ""});
  const save = () => act.run("save", async () => {
    const body = {title: f.title, role_keyword: f.role_keyword, k: Number(f.k), cases: parseCases(f.cases)};
    if (f.id) await apiLearning.suiteUpdate(f.id, body); else await apiLearning.suiteCreate(body);
    setF({id: null, title: "", role_keyword: "", k: 3, cases: ""}); await q.reload();
  }, tr("learning.ev_da_luu"));
  return <LabBody q={q}>
    {act.error ? <ErrorBanner error={act.error} context={tr("learning.tab_evals")} onClose={() => act.setError(null)}/> : null}
    <Panel title={tr("learning.ev_bo")} desc={tr("learning.ev_bo_desc")}>
      <Table rows={q.data} empty={tr("learning.ev_trong")} testId="suite-list" cols={[
        {label: tr("learning.ev_ten"), render: s => <b>{s.title}</b>},
        {label: tr("learning.ev_vai"), render: s => s.role_keyword || tr("learning.ev_moi_vai")},
        {label: tr("learning.ev_so_ca"), render: s => `${s.cases.length} × ${s.k}`},
        ...(canEdit ? [{label: "", render: (s: Any) => <Button size="sm" onClick={() => setF({id: s.id, title: s.title, role_keyword: s.role_keyword, k: s.k, cases: casesText(s.cases)})}>{tr("learning.ev_sua")}</Button>}] : []),
      ]}/>
      <small className="tmGuide">{tr("learning.ev_chay_o_dau")}</small>
    </Panel>
    {canEdit && <Panel title={f.id ? tr("learning.ev_sua_bo") : tr("learning.ev_tao")} desc={tr("learning.ev_tao_desc")}>
      <div className="ui-form" data-testid="suite-form">
        <div className="ui-form-row">
          <Field label={tr("learning.ev_ten")}><input className="ui-input" value={f.title} onChange={e => setF({...f, title: e.target.value})}/></Field>
          <Field label={tr("learning.ev_vai")} hint={tr("learning.ev_vai_hint")}><input className="ui-input" value={f.role_keyword} onChange={e => setF({...f, role_keyword: e.target.value})}/></Field>
          <Field label={tr("learning.ev_k")} hint={tr("learning.ev_k_hint")}><input className="ui-input" type="number" min={1} max={5} value={f.k} onChange={e => setF({...f, k: e.target.value})}/></Field>
        </div>
        <Field label={tr("learning.sk_ca_kiem")} hint={tr("learning.sk_ca_kiem_hint")}><textarea className="ui-textarea" rows={5} value={f.cases} onChange={e => setF({...f, cases: e.target.value})}/></Field>
        <div className="ui-toolbar"><Button variant="primary" busy={act.busy === "save"} disabled={f.title.trim().length < 3 || !f.cases.trim()} onClick={save}>{tr("learning.ev_luu")}</Button>
          {f.id && <Button onClick={() => setF({id: null, title: "", role_keyword: "", k: 3, cases: ""})}>{tr("learning.dong")}</Button>}</div>
      </div>
    </Panel>}
  </LabBody>;
}


/* M6 việc 12b: A2A — thuê agent bên ngoài (dán Agent Card) + mở seat của công ty cho bên ngoài gọi. */
function A2A({canEdit, o}: {canEdit: boolean; o: Any}) {
  const q = useLoad(async () => (await apiA2A.external()).items as Any[], []);
  const act = useAction();
  const [f, setF] = useState<Any>({card_url: "", auth_header: ""});
  const [test, setTest] = useState<Any>({});
  const [reply, setReply] = useState<Any>({});
  const [seat, setSeat] = useState("");
  const [exp, setExp] = useState<Any>(null);
  const loadExp = async (id: string) => { setSeat(id); setExp(id ? await apiA2A.exposure(Number(id)) : null); };
  return <LabBody q={q}>
    {act.error ? <ErrorBanner error={act.error} context="A2A" onClose={() => act.setError(null)}/> : null}
    <Panel title={tr("learning.a2a_thue")} desc={tr("learning.a2a_thue_desc")}>
      {canEdit && <form className="ui-form-row" onSubmit={e => { e.preventDefault(); act.run("add", async () => {
        await apiA2A.addExternal({card_url: f.card_url.trim(), auth_header: f.auth_header.trim()}); setF({card_url: "", auth_header: ""}); await q.reload();
      }, tr("learning.a2a_da_them")); }}>
        <Field label={tr("learning.a2a_card_url")}><input className="ui-input" value={f.card_url} required
          placeholder="https://…/.well-known/agent-card.json" onChange={e => setF({...f, card_url: e.target.value})} data-testid="a2a-card-url"/></Field>
        <Field label={tr("learning.a2a_auth")} hint={tr("learning.a2a_auth_hint")}><input className="ui-input" value={f.auth_header} type="password"
          placeholder="Bearer …" onChange={e => setF({...f, auth_header: e.target.value})}/></Field>
        <div className="ui-toolbar"><Button variant="primary" busy={act.busy === "add"} type="submit">{tr("learning.a2a_them")}</Button></div>
      </form>}
      <Table rows={q.data} empty={tr("learning.a2a_chua_co")} testId="a2a-list" cols={[
        {label: tr("learning.a2a_agent"), render: e => <><b>{e.name}</b><br/><small>{e.description}</small>
          {e.skills?.length ? <><br/><small>{e.skills.map((s: Any) => s.name || s.id).join(" · ")}</small></> : null}</>},
        {label: tr("learning.a2a_trang_thai"), render: e => <><Pill s={e.enabled ? "ok" : "info"} label={e.enabled ? tr("learning.a2a_bat") : tr("learning.a2a_tat")}/>
          <br/><small>{tr("learning.a2a_so_lan", {p0: e.calls})}</small>{e.last_error ? <><br/><small className="is-risk">{e.last_error}</small></> : null}</>},
        {label: "", render: e => canEdit ? <div style={{display: "grid", gap: 6}}>
          <div className="ui-toolbar">
            <Button size="sm" onClick={() => act.run(`t${e.id}`, async () => { await apiA2A.patchExternal(e.id, {enabled: !e.enabled}); await q.reload(); })}>
              {e.enabled ? tr("learning.a2a_tat_di") : tr("learning.a2a_bat_len")}</Button>
            <Button size="sm" onClick={() => { if (window.confirm(tr("learning.xac_nhan_xoa"))) act.run(`rm${e.id}`, async () => { await apiA2A.removeExternal(e.id); await q.reload(); }); }}>{tr("learning.xoa")}</Button>
          </div>
          <form className="ui-toolbar" onSubmit={ev => { ev.preventDefault(); act.run(`s${e.id}`, async () => {
            // gửi lỗi vẫn tải lại danh sách: số lần gọi + lỗi gần nhất của agent ngoài đã được ghi (smoke M2d.4)
            try { const r = await apiA2A.send(e.id, test[e.id] || ""); setReply({...reply, [e.id]: r.reply}); } finally { await q.reload(); } }); }}>
            <input className="ui-input" placeholder={tr("learning.a2a_gui_thu_ph")} value={test[e.id] || ""} onChange={ev => setTest({...test, [e.id]: ev.target.value})}/>
            <Button size="sm" busy={act.busy === `s${e.id}`} type="submit" disabled={!e.enabled || !(test[e.id] || "").trim()}>{tr("learning.a2a_gui_thu")}</Button>
          </form>
          {reply[e.id] ? <div className="tmGuide" style={{whiteSpace: "pre-wrap"}}>{reply[e.id]}</div> : null}
        </div> : null},
      ]}/>
    </Panel>
    <Panel title={tr("learning.a2a_mo")} desc={tr("learning.a2a_mo_desc")}>
      <Field label={tr("learning.pv_agent")}><select className="ui-select" value={seat} onChange={e => act.run("ld", () => loadExp(e.target.value))} data-testid="a2a-seat">
        <option value="">{tr("learning.chon")}</option>{(o?.agents || []).map((x: Any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
      {exp && <div style={{display: "grid", gap: 8, marginTop: 8}}>
        <div><Pill s={exp.enabled ? "ok" : "info"} label={exp.enabled ? tr("learning.a2a_dang_mo") : tr("learning.a2a_dang_dong")}/>
          {" "}<small>{tr("learning.a2a_so_lan", {p0: exp.calls})}</small></div>
        {exp.enabled && <small>{tr("learning.a2a_card_url")}: <code>{exp.card_url}</code></small>}
        {exp.token && <div className="ui-banner" data-testid="a2a-token">{tr("learning.a2a_khoa_mot_lan")}<br/><code style={{wordBreak: "break-all"}}>{exp.token}</code></div>}
        {canEdit && <div className="ui-toolbar">
          <Button size="sm" variant={exp.enabled ? undefined : "primary"} busy={act.busy === "ex"} onClick={() => act.run("ex", async () =>
            setExp(await apiA2A.expose(Number(seat), {enabled: !exp.enabled})))}>{exp.enabled ? tr("learning.a2a_dong") : tr("learning.a2a_mo_ngay")}</Button>
          {exp.enabled && <Button size="sm" busy={act.busy === "rot"} onClick={() => { if (window.confirm(tr("learning.a2a_xac_nhan_doi"))) act.run("rot", async () =>
            setExp(await apiA2A.expose(Number(seat), {enabled: true, rotate: true}))); }}>{tr("learning.a2a_doi_khoa")}</Button>}
        </div>}
      </div>}
    </Panel>
  </LabBody>;
}
