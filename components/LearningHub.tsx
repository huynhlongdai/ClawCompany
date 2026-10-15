"use client";
/* M5b việc 9: Đào tạo agent — kho tri thức (nạp văn bản / tệp / URL, tra thử có trích dẫn),
   lỗ hổng kiến thức, khoá học (học từng module → bài học chờ duyệt → thi → chứng chỉ). */
import {useState} from "react";
import {apiLearning, apiSharedMemory} from "../lib/api";
import {t as tr} from "../lib/i18n";
import {Button} from "./ui/Button";
import {ErrorBanner} from "./ui/EmptyState";
import {Field} from "./ui/Field";
import {Any, LabBody, Panel, Pill, Table, useAction, useLoad} from "./lab/kit";

type Sub = "library" | "gaps" | "courses";

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
      {(["library", "courses", "gaps"] as Sub[]).map(s => <button key={s} role="tab" aria-selected={sub === s} aria-pressed={sub === s}
        onClick={() => setSub(s)} data-testid={`learning-tab-${s}`}>{tr(`learning.tab_${s}` as any)}</button>)}
    </div>
    {sub === "library" && <Library canEdit={canEdit} o={opt.data}/>}
    {sub === "courses" && <Courses canEdit={canEdit} o={opt.data}/>}
    {sub === "gaps" && <Gaps canEdit={canEdit}/>}
  </div>;
}

function ScopePicker({o, v, set}: {o: Any; v: Any; set: (x: Any) => void}) {
  const kinds = [["org", tr("learning.pv_to_chuc")], ["department", tr("learning.pv_phong")], ["project", tr("learning.pv_du_an")], ["agent", tr("learning.pv_agent")]];
  const list = !o ? [] : v.kind === "department" ? o.departments : v.kind === "project" ? o.projects : v.kind === "agent" ? o.agents : [];
  return <div className="ui-form-row">
    <Field label={tr("learning.pham_vi")}><select className="ui-select" value={v.kind} onChange={e => set({kind: e.target.value, id: ""})}>
      {kinds.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
    {v.kind !== "org" && <Field label={tr("learning.thuoc")}><select className="ui-select" value={v.id} onChange={e => set({...v, id: e.target.value})}>
      <option value="">{tr("learning.chon")}</option>{list.map((x: Any) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>}
  </div>;
}

const scopeBody = (v: Any) => v.kind === "org" || !v.id ? {} : {[`${v.kind}_id`]: Number(v.id)};

function Library({canEdit, o}: {canEdit: boolean; o: Any}) {
  const q = useLoad(async () => (await apiLearning.docs()).items as Any[], []);
  const act = useAction();
  const [mode, setMode] = useState<"text" | "url" | "file">("text");
  const [f, setF] = useState<Any>({title: "", content: "", url: ""});
  const [file, setFile] = useState<File | null>(null);
  const [scope, setScope] = useState<Any>({kind: "org", id: ""});
  const [s, setS] = useState(""), [res, setRes] = useState<Any>(null);
  const add = () => act.run("add", async () => {
    const r = mode === "file" && file ? await apiLearning.upload(file, {title: f.title, ...scopeBody(scope)})
      : await apiLearning.addDoc(mode === "url" ? {url: f.url, title: f.title, ...scopeBody(scope)} : {title: f.title, content: f.content, ...scopeBody(scope)});
    setF({title: "", content: "", url: ""}); setFile(null); await q.reload();
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
        {label: tr("learning.pham_vi"), render: d => <Pill s="info" label={d.scope}/>},
        {label: tr("learning.nguon"), render: d => d.source_url ? <a href={d.source_url} target="_blank" rel="noreferrer">{tr(`learning.src_${d.source_type}` as any)}</a> : tr(`learning.src_${d.source_type}` as any), hideSm: true},
        {label: tr("learning.dong_bo"), render: d => <small>{fmt(d.synced_at)}</small>, hideSm: true},
        ...(canEdit ? [{label: "", render: (d: Any) => <div className="ui-toolbar">
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
