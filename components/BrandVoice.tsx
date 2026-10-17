"use client";
// Công ty › Pháp nhân & quản trị › Giọng thương hiệu: văn bản có cấu trúc (phiên bản, duyệt để ban hành), theo kênh, ví dụ,
// giọng nói (TTS, nghe thử), kiểm tra (ô thử văn bản → bộ chấm tất định; cài đặt cưỡng chế; bộ eval). Nhãn là mã i18n bv.*;
// lỗi có mã từ backend → bv.err_<mã>. Quyền: soạn = quản lý (caps.invite), ban hành/cài đặt = quản trị (caps.manage_roles);
// backend kiểm lại theo vai trò công ty.
import {useEffect, useMemo, useState} from "react";
import {apiVoice} from "../lib/api";
import {ErrorBanner, EmptyState} from "./ui/EmptyState";
import {SkeletonRows} from "./ui/Skeleton";
import {StatusPill} from "./ui/StatusPill";
import {useToast} from "./ui/Toast";
import {Field, FormRow} from "./ui/Field";
import {Segmented} from "./ui/Tabs";
import {fmtDateTime, t as tr, type Key} from "../lib/i18n";
import {useLoad} from "./CompanyOperations";

const CHANNELS = ["zalo", "facebook", "email", "phone", "website", "internal"] as const;
type Sub = "text" | "channels" | "examples" | "voice" | "check";
const ch = (c: string) => tr(`bv.ch_${c}` as Key);

export function voiceErr(e: any) {
  const code = e?.code || e?.detail?.error;
  if (code && e && typeof e === "object") {
    const key = `bv.err_${code}` as Key, s = tr(key, (e.detail || {}) as any);
    if (s !== key) { try { e.message = s; } catch { /* bỏ qua */ } }
  }
  return e;
}
/** Vi phạm → câu theo ngôn ngữ người dùng (bv.v_<mã> với tham số), không có khoá thì giữ câu backend. */
export function violationText(v: any) {
  const key = `bv.v_${v.code}` as Key;
  const p: any = {...(v.params || {})};
  if (p.channel) p.channel = ch(p.channel);
  const s = tr(key, p);
  return s === key ? v.message : s;
}
const EMPTY_SPEC = {persona: "", personality: [], traits: [], address: {customer: {self: "", customer: ""}, segments: [], internal: {self: "", other: ""}, avoid: null},
  preferred_terms: [], banned_words: [], banned_claims: [], emoji: {policy: "light", max: 2}, formatting: "", signature: "", closing: "",
  channels: {}, examples: [], lexicon: []};
const lines = (a: string[] | null | undefined) => (a || []).join("\n");
const unlines = (s: string) => s.split("\n").map(x => x.trim()).filter(Boolean);
const commas = (a: string[] | null | undefined) => (a || []).join(", ");
const uncommas = (s: string) => s.split(",").map(x => x.trim()).filter(Boolean);

export function BrandVoiceTab({companyId, caps}: {companyId: number | null; caps: any}) {
  const {data, error, reload, setError} = useLoad(() => companyId ? apiVoice.get(companyId) : Promise.resolve(null), [companyId]);
  const [sub, setSub] = useState<Sub>("text");
  const [spec, setSpec] = useState<any>(null), [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false);
  const toast = useToast();
  const canEdit = !!caps?.invite || !!caps?.manage_roles, canPublish = !!caps?.manage_roles;
  const d: any = data;
  useEffect(() => { if (d) { setSpec(JSON.parse(JSON.stringify((d.draft || d.published)?.spec || EMPTY_SPEC))); setDirty(false); } }, [d]);
  if (!companyId) return <p><small>{tr("docs.pick_company")}</small></p>;
  if (error && !data) return <ErrorBanner error={voiceErr(error)} onRetry={reload} testId="bv-error"/>;
  if (!d || !spec) return <SkeletonRows n={5} h={40}/>;
  const draft = d.draft, pub = d.published;
  const editable = canEdit && (!draft || draft.status === "draft");
  const set = (patch: any) => { setSpec({...spec, ...patch}); setDirty(true); };
  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true); setError(null);
    try { await fn(); toast(ok); await reload(); } catch (e) { setError(voiceErr(e)); } finally { setBusy(false); }
  }
  const save = () => run(() => apiVoice.saveDraft({company_id: companyId, spec}), tr("bv.saved"));
  return <section className="ui-section" data-testid="brand-voice">
    {error ? <ErrorBanner error={voiceErr(error)} onClose={() => setError(null)} testId="bv-save-error"/> : null}
    <p className="tmGuide">{tr("bv.explain")}</p>
    <div className="tmRow biz-wrap" data-testid="bv-status">
      {pub ? <span className="ui-pill is-ok">{tr("bv.published_v", {p0: pub.version_no})}{pub.published_at ? " · " + fmtDateTime(pub.published_at) : ""}</span>
        : <span className="ui-pill is-wait">{tr("bv.no_published")}</span>}
      {draft && <span className={"ui-pill" + (draft.status === "in_review" ? " is-wait" : "")} data-testid="bv-draft-pill">
        {tr(draft.status === "in_review" ? "bv.in_review_v" : "bv.draft_v", {p0: draft.version_no})}</span>}
      {(draft?.is_demo || (!draft && pub?.is_demo)) && <StatusPill tone="wait">{tr("bv.demo")}</StatusPill>}
      {pub?.spec?.migrated_from_charter && !draft && <StatusPill tone="neutral">{tr("bv.migrated")}</StatusPill>}
      <span className="ui-grow"/>
      {editable && <button className="ui-btn is-primary is-sm" disabled={busy || !dirty} onClick={save} data-testid="bv-save">{tr("bv.save_draft")}</button>}
      {canEdit && draft?.status === "draft" && !dirty && <button className="ui-btn is-sm" disabled={busy} onClick={() => run(() => apiVoice.submit(draft.id), tr("bv.submitted"))} data-testid="bv-submit">{tr("bv.submit")}</button>}
      {canPublish && draft?.status === "in_review" && <>
        <button className="ui-btn is-primary is-sm" disabled={busy} onClick={() => run(() => apiVoice.decide(draft.id, "approve"), tr("bv.published_ok"))} data-testid="bv-approve">{tr("bv.approve")}</button>
        <button className="ui-btn is-sm" disabled={busy} onClick={() => run(() => apiVoice.decide(draft.id, "reject"), tr("bv.rejected_ok"))} data-testid="bv-reject">{tr("bv.reject")}</button></>}
      {canEdit && draft && <button className="ui-btn is-ghost is-sm" disabled={busy} onClick={() => run(() => apiVoice.discard(draft.id), tr("bv.discarded"))} data-testid="bv-discard">{tr("bv.discard")}</button>}
    </div>
    {draft?.status === "in_review" && !canPublish && <p><small>{tr("bv.wait_admin")}</small></p>}
    {!canEdit && <p><small>{tr("bv.read_only")}</small></p>}
    <Segmented<Sub> label={tr("bv.title")} value={sub} onChange={setSub} options={[
      {value: "text", label: tr("bv.t_text"), testId: "bv-t-text"}, {value: "channels", label: tr("bv.t_channels"), testId: "bv-t-channels"},
      {value: "examples", label: tr("bv.t_examples"), testId: "bv-t-examples"}, {value: "voice", label: tr("bv.t_voice"), testId: "bv-t-voice"},
      {value: "check", label: tr("bv.t_check"), testId: "bv-t-check"}]}/>
    <div style={{marginTop: 12}}>
      {sub === "text" && <TextTab spec={spec} set={set} editable={editable} d={d}/>}
      {sub === "channels" && <ChannelsTab spec={spec} set={set} editable={editable} d={d}/>}
      {sub === "examples" && <ExamplesTab spec={spec} set={set} editable={editable} companyId={companyId}/>}
      {sub === "voice" && <VoiceTab companyId={companyId} canEdit={canEdit}/>}
      {sub === "check" && <CheckTab companyId={companyId} d={d} canEdit={canEdit} canPublish={canPublish} onChanged={reload}/>}
    </div>
    {dirty && editable && <div className="tmRow biz-wrap bv-sticky"><small>{tr("bv.unsaved")}</small><span className="ui-grow"/>
      <button className="ui-btn is-primary is-sm" disabled={busy} onClick={save}>{tr("bv.save_draft")}</button></div>}
  </section>;
}

function Rows({items, cols, onChange, editable, addLabel, testId}: {items: any[]; cols: {key: string; label: string; wide?: boolean; list?: boolean}[];
  onChange: (v: any[]) => void; editable: boolean; addLabel: string; testId: string}) {
  const blank = Object.fromEntries(cols.map(c => [c.key, c.list ? [] : ""]));
  return <div className="bv-rows" data-testid={testId}>
    {items.map((it, i) => <div key={i} className="bv-row">
      {cols.map(c => <label key={c.key} className={"bv-cell" + (c.wide ? " is-wide" : "")}><small>{c.label}</small>
        <input className="ui-input" disabled={!editable} value={c.list ? commas(it[c.key]) : (it[c.key] || "")}
          onChange={e => { const n = [...items]; n[i] = {...it, [c.key]: c.list ? uncommas(e.target.value) : e.target.value}; onChange(n); }}/></label>)}
      {editable && <button className="ui-btn is-ghost is-sm" aria-label={tr("bv.remove")} onClick={() => onChange(items.filter((_, j) => j !== i))}>✕</button>}
    </div>)}
    {editable && <button className="ui-btn is-sm" onClick={() => onChange([...items, blank])}>{addLabel}</button>}
  </div>;
}

function TextTab({spec, set, editable, d}: any) {
  const a = spec.address || EMPTY_SPEC.address;
  const setA = (patch: any) => set({address: {...a, ...patch}});
  return <fieldset className="ui-form bv-form" disabled={!editable} data-testid="bv-text">
    <section className="ui-panel tm-card"><h3>{tr("bv.persona")}</h3>
      <Field label={tr("bv.persona")} hint={tr("bv.persona_hint")}><textarea className="ui-input" rows={3} value={spec.persona} onChange={e => set({persona: e.target.value})} data-testid="bv-persona"/></Field>
      <Field label={tr("bv.personality")} hint={tr("bv.commas")}><input className="ui-input" value={commas(spec.personality)} onChange={e => set({personality: uncommas(e.target.value)})}/></Field>
      <h4>{tr("bv.traits")}</h4><p><small>{tr("bv.traits_hint")}</small></p>
      <Rows testId="bv-traits" items={spec.traits || []} editable={editable} addLabel={tr("bv.add_trait")} onChange={v => set({traits: v})}
        cols={[{key: "is", label: tr("bv.is")}, {key: "is_not", label: tr("bv.is_not")}]}/>
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.address")}</h3>
      <FormRow>
        <Field label={tr("bv.addr_self")}><input className="ui-input" value={a.customer?.self || ""} onChange={e => setA({customer: {...a.customer, self: e.target.value}})} data-testid="bv-addr-self"/></Field>
        <Field label={tr("bv.addr_customer")} hint={tr("bv.slash_hint")}><input className="ui-input" value={a.customer?.customer || ""} onChange={e => setA({customer: {...a.customer, customer: e.target.value}})}/></Field>
      </FormRow>
      <h4>{tr("bv.segments")}</h4>
      <Rows testId="bv-segments" items={a.segments || []} editable={editable} addLabel={tr("bv.add_segment")} onChange={v => setA({segments: v})}
        cols={[{key: "label", label: tr("bv.seg_label")}, {key: "self", label: tr("bv.addr_self")}, {key: "customer", label: tr("bv.addr_customer")}]}/>
      <FormRow>
        <Field label={tr("bv.int_self")}><input className="ui-input" value={a.internal?.self || ""} onChange={e => setA({internal: {...a.internal, self: e.target.value}})}/></Field>
        <Field label={tr("bv.int_other")}><input className="ui-input" value={a.internal?.other || ""} onChange={e => setA({internal: {...a.internal, other: e.target.value}})}/></Field>
      </FormRow>
      <Field label={tr("bv.avoid")} hint={tr("bv.avoid_hint")}><input className="ui-input" value={a.avoid == null ? "" : commas(a.avoid)} placeholder="tao, mày, tớ, cậu, bạn, tôi"
        onChange={e => setA({avoid: e.target.value.trim() ? uncommas(e.target.value) : null})}/></Field>
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.words")}</h3>
      <h4>{tr("bv.preferred")}</h4>
      <Rows testId="bv-preferred" items={spec.preferred_terms || []} editable={editable} addLabel={tr("bv.add_term")} onChange={v => set({preferred_terms: v})}
        cols={[{key: "use", label: tr("bv.use")}, {key: "instead_of", label: tr("bv.instead_of"), list: true, wide: true}]}/>
      <FormRow>
        <Field label={tr("bv.banned_words")} hint={tr("bv.one_per_line")}><textarea className="ui-input" rows={4} value={lines(spec.banned_words)} onChange={e => set({banned_words: unlines(e.target.value)})} data-testid="bv-banned"/></Field>
        <Field label={tr("bv.banned_claims")} hint={tr("bv.one_per_line")}><textarea className="ui-input" rows={4} value={lines(spec.banned_claims)} onChange={e => set({banned_claims: unlines(e.target.value)})}/></Field>
      </FormRow>
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.format")}</h3>
      <FormRow>
        <Field label={tr("bv.emoji")}><select className="ui-input" value={spec.emoji?.policy || "light"} onChange={e => set({emoji: {...spec.emoji, policy: e.target.value}})}>
          {["none", "light", "free"].map(p => <option key={p} value={p}>{tr(`bv.emoji_${p}` as Key)}</option>)}</select></Field>
        <Field label={tr("bv.emoji_max")}><input className="ui-input" type="number" min={0} max={10} value={spec.emoji?.max ?? 2} onChange={e => set({emoji: {...spec.emoji, max: Number(e.target.value)}})}/></Field>
      </FormRow>
      <Field label={tr("bv.formatting")}><textarea className="ui-input" rows={2} value={spec.formatting} onChange={e => set({formatting: e.target.value})}/></Field>
      <FormRow>
        <Field label={tr("bv.signature")}><textarea className="ui-input" rows={2} value={spec.signature} onChange={e => set({signature: e.target.value})}/></Field>
        <Field label={tr("bv.closing")}><input className="ui-input" value={spec.closing} onChange={e => set({closing: e.target.value})}/></Field>
      </FormRow>
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.lexicon")}</h3><p><small>{tr("bv.lexicon_hint")}</small></p>
      <Rows testId="bv-lexicon" items={spec.lexicon || []} editable={editable} addLabel={tr("bv.add_lex")} onChange={v => set({lexicon: v})}
        cols={[{key: "term", label: tr("bv.lex_term")}, {key: "say", label: tr("bv.lex_say"), wide: true}]}/>
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.core_preview")}</h3>
      <p><small>{tr("bv.core_hint", {p0: d.core_chars, p1: d.core_budget})}</small></p>
      {d.core_preview ? <pre className="biz-minutes" data-testid="bv-core">{d.core_preview}</pre> : <small>{tr("bv.core_empty")}</small>}
    </section>
  </fieldset>;
}

function ChannelsTab({spec, set, editable, d}: any) {
  const defs: Record<string, any> = Object.fromEntries((d.channels || []).map((c: any) => [c.key, c]));
  const chs = spec.channels || {};
  const setC = (c: string, patch: any) => set({channels: {...chs, [c]: {...(chs[c] || {}), ...patch}}});
  return <fieldset className="ui-form bv-form" disabled={!editable} data-testid="bv-channels">
    <p className="tmGuide">{tr("bv.channels_explain")}</p>
    <div className="bv-grid">{CHANNELS.map(c => { const v = chs[c] || {}; return <section key={c} className="ui-panel tm-card" data-testid={`bv-ch-${c}`}>
      <h3>{ch(c)}</h3>
      <Field label={tr("bv.ch_tone")}><textarea className="ui-input" rows={2} value={v.tone || ""} onChange={e => setC(c, {tone: e.target.value})}/></Field>
      <FormRow>
        <Field label={tr("bv.ch_greeting")}><input className="ui-input" value={v.greeting || ""} onChange={e => setC(c, {greeting: e.target.value})}/></Field>
        <Field label={tr("bv.ch_closing")}><input className="ui-input" value={v.closing || ""} onChange={e => setC(c, {closing: e.target.value})}/></Field>
      </FormRow>
      <FormRow>
        <Field label={tr("bv.ch_max")}><input className="ui-input" type="number" min={40} placeholder={String(defs[c]?.max_chars || "")} value={v.max_chars ?? ""}
          onChange={e => setC(c, {max_chars: e.target.value === "" ? null : Number(e.target.value)})}/></Field>
        <Field label={tr("bv.emoji")}><select className="ui-input" value={v.emoji || ""} onChange={e => setC(c, {emoji: e.target.value || null})}>
          <option value="">{tr("bv.inherit")}</option>{["none", "light", "free"].map(p => <option key={p} value={p}>{tr(`bv.emoji_${p}` as Key)}</option>)}</select></Field>
      </FormRow>
      <div className="tmRow biz-wrap">
        <label className="biz-check"><input type="checkbox" checked={v.no_markdown ?? !!defs[c]?.no_markdown} onChange={e => setC(c, {no_markdown: e.target.checked})}/> {tr("bv.no_markdown")}</label>
        <label className="biz-check"><input type="checkbox" checked={v.signature_required ?? !!defs[c]?.signature_required} onChange={e => setC(c, {signature_required: e.target.checked})}/> {tr("bv.sig_required")}</label>
      </div>
    </section>; })}</div>
  </fieldset>;
}

function ExamplesTab({spec, set, editable, companyId}: any) {
  const [st, setSt] = useState<any>(null), [err, setErr] = useState<unknown>(null);
  const ex = spec.examples || [];
  const setE = (i: number, patch: any) => { const n = [...ex]; n[i] = {...ex[i], ...patch}; set({examples: n}); };
  async function test() { setErr(null); try { setSt(await apiVoice.selftest({company_id: companyId, spec})); } catch (e) { setErr(voiceErr(e)); } }
  return <div data-testid="bv-examples">
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)}/> : null}
    <div className="tmRow biz-wrap"><p className="tmGuide" style={{margin: 0}}>{tr("bv.examples_explain")}</p><span className="ui-grow"/>
      <button className="ui-btn is-sm" onClick={test} data-testid="bv-selftest">{tr("bv.selftest")}</button></div>
    {st && <p data-testid="bv-selftest-result"><StatusPill tone={st.all_ok ? "ok" : "risk"}>{tr(st.all_ok ? "bv.selftest_ok" : "bv.selftest_bad")}</StatusPill>{" "}
      <small>{tr("bv.selftest_sum", {p0: st.good_pass, p1: st.bad_caught, p2: st.total})}</small></p>}
    {ex.length === 0 && <EmptyState compact mood="chao" title={tr("bv.no_examples")}>{tr("bv.no_examples_hint")}</EmptyState>}
    <fieldset className="ui-form bv-form" disabled={!editable}>
      {ex.map((e: any, i: number) => { const r = st?.examples?.[i]; return <section key={i} className="ui-panel tm-card" data-testid={`bv-ex-${i}`}>
        <FormRow>
          <Field label={tr("bv.channel")}><select className="ui-input" value={e.channel} onChange={x => setE(i, {channel: x.target.value})}>
            {CHANNELS.map(c => <option key={c} value={c}>{ch(c)}</option>)}</select></Field>
          <Field label={tr("bv.situation")}><input className="ui-input" value={e.situation || ""} onChange={x => setE(i, {situation: x.target.value})}/></Field>
        </FormRow>
        <FormRow>
          <Field label={tr("bv.good")}><textarea className="ui-input bv-good" rows={3} value={e.good || ""} onChange={x => setE(i, {good: x.target.value})}/></Field>
          <Field label={tr("bv.bad")}><textarea className="ui-input bv-bad" rows={3} value={e.bad || ""} onChange={x => setE(i, {bad: x.target.value})}/></Field>
        </FormRow>
        <Field label={tr("bv.why")}><input className="ui-input" value={e.why || ""} onChange={x => setE(i, {why: x.target.value})}/></Field>
        {r && <div className="tmRow biz-wrap">
          {r.good_ok !== null && <StatusPill tone={r.good_ok ? "ok" : "risk"}>{tr("bv.good_score", {p0: r.good_score})}</StatusPill>}
          {r.bad_caught !== null && <StatusPill tone={r.bad_caught ? "ok" : "risk"}>{tr(r.bad_caught ? "bv.bad_caught" : "bv.bad_missed", {p0: r.bad_score})}</StatusPill>}
          {(r.good_violations || []).map((v: any, k: number) => <small key={k} className="bv-viol">{violationText(v)}</small>)}
        </div>}
        {editable && <button className="ui-btn is-ghost is-sm" onClick={() => set({examples: ex.filter((_: any, j: number) => j !== i)})}>{tr("bv.remove")}</button>}
      </section>; })}
      {editable && <button className="ui-btn is-sm" onClick={() => set({examples: [...ex, {channel: "zalo", situation: "", good: "", bad: "", why: ""}]})} data-testid="bv-add-example">{tr("bv.add_example")}</button>}
    </fieldset>
  </div>;
}

function Player({path}: {path: string}) {
  const [url, setUrl] = useState<string | null>(null), [err, setErr] = useState(false);
  useEffect(() => { let u: string | null = null; apiVoice.audioUrl(path).then(x => { u = x; setUrl(x); }).catch(() => setErr(true));
    return () => { if (u) URL.revokeObjectURL(u); }; }, [path]);
  if (err) return <small>{tr("bv.audio_err")}</small>;
  return url ? <audio controls src={url} className="bv-audio" data-testid="bv-audio"/> : <small>…</small>;
}

function VoiceTab({companyId, canEdit}: {companyId: number; canEdit: boolean}) {
  const {data, error, reload, setError} = useLoad(() => Promise.all([apiVoice.profile(companyId), apiVoice.samples(companyId)]), [companyId]);
  const [f, setF] = useState<any>(null), [busy, setBusy] = useState(false), [spoken, setSpoken] = useState<string>("");
  const [ttsErr, setTtsErr] = useState<any>(null);
  const toast = useToast();
  useEffect(() => { if (data) setF({...(data as any)[0]}); }, [data]);
  if (error && !data) return <ErrorBanner error={voiceErr(error)} onRetry={reload}/>;
  if (!data || !f) return <SkeletonRows n={4} h={40}/>;
  const [p, samples] = data as any;
  const s = (k: string) => (e: any) => setF({...f, [k]: e.target.value});
  async function save() {
    setBusy(true); setError(null);
    try { await apiVoice.saveProfile({company_id: companyId, provider: f.provider, model: f.model, voice_name: f.voice_name, language: f.language,
      speed: Number(f.speed), pitch: f.pitch, style: f.style, greeting_script: f.greeting_script, closing_script: f.closing_script, sample_text: f.sample_text});
      toast(tr("bv.saved")); await reload(); } catch (e) { setError(voiceErr(e)); } finally { setBusy(false); }
  }
  async function listen(which: string) {
    setBusy(true); setTtsErr(null); setError(null);
    try { await apiVoice.preview({company_id: companyId, which}); toast(tr("bv.audio_ready")); await reload(); }
    catch (e: any) { setTtsErr(voiceErr(e)); await reload(); } finally { setBusy(false); }
  }
  async function showSpoken() { try { setSpoken((await apiVoice.spoken(companyId, f.sample_text || f.greeting_script || "")).text); } catch (e) { setError(voiceErr(e)); } }
  return <div data-testid="bv-voice">
    {error ? <ErrorBanner error={error} onClose={() => setError(null)}/> : null}
    <p className="tmGuide">{tr("bv.voice_explain")}</p>
    {p.is_demo && <StatusPill tone="wait">{tr("bv.demo")}</StatusPill>}
    <fieldset className="ui-form bv-form" disabled={!canEdit || busy}>
      <section className="ui-panel tm-card"><h3>{tr("bv.voice_profile")}</h3>
        <FormRow>
          <Field label={tr("bv.provider")}><select className="ui-input" value={f.provider} onChange={s("provider")} data-testid="bv-provider">
            {p.providers.map((x: any) => <option key={x.key} value={x.key}>{x.label}{x.configured ? "" : " — " + tr("bv.not_configured")}</option>)}</select></Field>
          <Field label={tr("bv.model")}><select className="ui-input" value={f.model} onChange={s("model")}>{p.models.map((m: string) => <option key={m}>{m}</option>)}</select></Field>
        </FormRow>
        <FormRow>
          <Field label={tr("bv.voice_name")} hint={tr("bv.voice_name_hint")}><input className="ui-input" list="bv-voices" value={f.voice_name} onChange={s("voice_name")}/></Field>
          <Field label={tr("bv.language")}><input className="ui-input" value={f.language} onChange={s("language")}/></Field>
        </FormRow>
        <datalist id="bv-voices">{p.voices.map((v: string) => <option key={v} value={v}/>)}</datalist>
        <FormRow>
          <Field label={tr("bv.speed", {p0: f.speed})}><input type="range" min={0.5} max={2} step={0.05} value={f.speed} onChange={s("speed")}/></Field>
          <Field label={tr("bv.pitch")}><select className="ui-input" value={f.pitch} onChange={s("pitch")}>{p.pitches.map((x: string) => <option key={x} value={x}>{tr(`bv.pitch_${x}` as Key)}</option>)}</select></Field>
        </FormRow>
        <Field label={tr("bv.style")} hint={tr("bv.style_hint")}><input className="ui-input" value={f.style} onChange={s("style")}/></Field>
      </section>
      <section className="ui-panel tm-card"><h3>{tr("bv.scripts")}</h3>
        <Field label={tr("bv.greeting_script")}><textarea className="ui-input" rows={2} value={f.greeting_script} onChange={s("greeting_script")}/></Field>
        <Field label={tr("bv.closing_script")}><textarea className="ui-input" rows={2} value={f.closing_script} onChange={s("closing_script")}/></Field>
        <Field label={tr("bv.sample_text")} hint={tr("bv.sample_hint")}><textarea className="ui-input" rows={2} value={f.sample_text} onChange={s("sample_text")} data-testid="bv-sample-text"/></Field>
        <div className="tmRow biz-wrap">
          {canEdit && <button className="ui-btn is-primary is-sm" onClick={save} data-testid="bv-voice-save">{tr("bv.save_voice")}</button>}
          {canEdit && p.exists && <>
            <button className="ui-btn is-sm" onClick={() => listen("sample")} data-testid="bv-listen">{tr("bv.listen")}</button>
            <button className="ui-btn is-sm" onClick={() => listen("greeting")}>{tr("bv.listen_greeting")}</button>
            <button className="ui-btn is-sm" onClick={() => listen("closing")}>{tr("bv.listen_closing")}</button></>}
          <button type="button" className="ui-btn is-ghost is-sm" onClick={showSpoken}>{tr("bv.show_spoken")}</button>
        </div>
        {spoken && <p data-testid="bv-spoken"><small>{tr("bv.spoken")}:</small> {spoken}</p>}
        {busy && <small>{tr("bv.generating")}</small>}
      </section>
    </fieldset>
    {ttsErr && <div className="ui-panel tm-card bv-tts-err" role="alert" data-testid="bv-tts-error"><b>{tr("bv.tts_failed")}</b><p>{ttsErr.message}</p><small>{tr("bv.tts_failed_hint")}</small></div>}
    <section className="ui-panel tm-card"><h3>{tr("bv.samples")}</h3>
      {samples.items.length === 0 ? <small>{tr("bv.no_samples")}</small> : <ul className="biz-timeline" data-testid="bv-samples">
        {samples.items.map((x: any) => <li key={x.id}>
          <div className="tmRow biz-wrap"><StatusPill tone={x.status === "ok" ? "ok" : "risk"}>{tr(x.status === "ok" ? "bv.sample_ok" : "bv.sample_err")}</StatusPill>
            <small>{fmtDateTime(x.created_at)} · {x.provider} · {x.model} · {x.voice_name}</small></div>
          <small>{x.text_spoken}</small>
          {x.status === "ok" ? <Player path={x.audio_path}/> : <p><small className="bv-viol">{x.error}</small></p>}
        </li>)}</ul>}
    </section>
  </div>;
}

function CheckTab({companyId, d, canEdit, canPublish, onChanged}: any) {
  const [text, setText] = useState(""), [channel, setChannel] = useState("zalo"), [segment, setSegment] = useState("");
  const [useDraft, setUseDraft] = useState(!d.published && !!d.draft), [useModel, setUseModel] = useState(false);
  const [res, setRes] = useState<any>(null), [err, setErr] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const {data: hist, reload} = useLoad(() => apiVoice.checks(companyId), [companyId]);
  const [st, setSt] = useState<any>(d.settings);
  const toast = useToast();
  const segs = useMemo(() => ((d.draft || d.published)?.spec?.address?.segments || []), [d]);
  async function check() {
    setBusy(true); setErr(null);
    try { setRes(await apiVoice.check({company_id: companyId, text, channel, segment, use_model: useModel, version_id: useDraft && d.draft ? d.draft.id : undefined})); reload(); }
    catch (e) { setErr(voiceErr(e)); } finally { setBusy(false); }
  }
  async function saveSettings() {
    setErr(null);
    try { setSt(await apiVoice.settings({company_id: companyId, enforcement: st.enforcement, min_score: Number(st.min_score), model_check: st.model_check})); toast(tr("bv.saved")); onChanged(); }
    catch (e) { setErr(voiceErr(e)); }
  }
  async function mkEval() { setErr(null); try { const s = await apiVoice.evalSuite(companyId); toast(tr("bv.eval_ok", {p0: s.cases.length})); } catch (e) { setErr(voiceErr(e)); } }
  return <div data-testid="bv-check">
    {err ? <ErrorBanner error={err} onClose={() => setErr(null)} testId="bv-check-error"/> : null}
    <section className="ui-panel tm-card"><h3>{tr("bv.try_title")}</h3>
      <p><small>{tr("bv.try_hint")}</small></p>
      <textarea className="ui-input" rows={4} value={text} onChange={e => setText(e.target.value)} placeholder={tr("bv.try_ph")} data-testid="bv-try-text"/>
      <div className="tmRow biz-wrap" style={{marginTop: 8}}>
        <select className="ui-input bv-sel" value={channel} onChange={e => setChannel(e.target.value)} data-testid="bv-try-channel">{CHANNELS.map(c => <option key={c} value={c}>{ch(c)}</option>)}</select>
        {segs.length > 0 && <select className="ui-input bv-sel" value={segment} onChange={e => setSegment(e.target.value)}><option value="">{tr("bv.seg_default")}</option>
          {segs.map((s: any) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>}
        {d.draft && <label className="biz-check"><input type="checkbox" checked={useDraft} onChange={e => setUseDraft(e.target.checked)}/> {tr("bv.use_draft")}</label>}
        {st?.model_check && <label className="biz-check"><input type="checkbox" checked={useModel} onChange={e => setUseModel(e.target.checked)}/> {tr("bv.use_model")}</label>}
        <span className="ui-grow"/>
        <button className="ui-btn is-primary is-sm" disabled={busy || !text.trim()} onClick={check} data-testid="bv-try-run">{tr("bv.try_run")}</button>
      </div>
      {res && <div className="bv-result" data-testid="bv-try-result">
        <div className="tmRow biz-wrap"><StatusPill tone={res.passed ? "ok" : "risk"}>{tr(res.passed ? "bv.pass" : "bv.fail")}</StatusPill>
          <b data-testid="bv-score">{tr("bv.score", {p0: res.score})}</b><small>{tr("bv.len", {p0: res.length})} · {ch(res.channel)}{res.voice_version ? ` · v${res.voice_version}` : ""}</small></div>
        {res.violations.length === 0 ? <p><small>{tr("bv.no_violations")}</small></p> : <ul className="bv-viols">{res.violations.map((v: any, i: number) =>
          <li key={i}><StatusPill tone={v.severity === "high" ? "risk" : v.severity === "medium" ? "wait" : "neutral"}>{tr(`bv.sev_${v.severity}` as Key)}</StatusPill> {violationText(v)}
            {v.source === "provider_floor" && <> <small>({tr("bv.floor")})</small></>}</li>)}</ul>}
        {res.model_result && <p><small>{tr("bv.model_result")}: {res.model_result.status === "ok" ? tr("bv.score", {p0: res.model_result.score}) + (res.model_result.issues?.length ? " — " + res.model_result.issues.join("; ") : "")
          : res.model_result.status === "disabled" ? tr("bv.model_disabled") : tr("bv.model_error", {p0: res.model_result.message || ""})}</small></p>}
      </div>}
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.enforce_title")}</h3>
      <p><small>{tr("bv.enforce_hint")}</small></p>
      <fieldset className="ui-form" disabled={!canPublish}>
        <FormRow>
          <Field label={tr("bv.enforcement")}><select className="ui-input" value={st.enforcement} onChange={e => setSt({...st, enforcement: e.target.value})} data-testid="bv-enforcement">
            {["off", "flag", "rework"].map(x => <option key={x} value={x}>{tr(`bv.enf_${x}` as Key)}</option>)}</select></Field>
          <Field label={tr("bv.min_score")}><input className="ui-input" type="number" min={0} max={1} step={0.05} value={st.min_score} onChange={e => setSt({...st, min_score: e.target.value})}/></Field>
        </FormRow>
        <label className="biz-check"><input type="checkbox" checked={!!st.model_check} onChange={e => setSt({...st, model_check: e.target.checked})}/> {tr("bv.model_check")}</label>
        {!st.model_check_available && <p><small>{tr("bv.model_unavailable")}</small></p>}
        {canPublish && <div className="tmRow" style={{marginTop: 8}}><button className="ui-btn is-sm" onClick={saveSettings} data-testid="bv-settings-save">{tr("bv.save_settings")}</button></div>}
      </fieldset>
      {!canPublish && <p><small>{tr("bv.admin_only")}</small></p>}
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.eval_title")}</h3>
      <p><small>{tr("bv.eval_hint")}</small></p>
      {canEdit && <button className="ui-btn is-sm" disabled={!d.published} onClick={mkEval} data-testid="bv-eval">{tr("bv.eval_make")}</button>}
    </section>
    <section className="ui-panel tm-card"><h3>{tr("bv.history")}</h3>
      {!hist ? <SkeletonRows n={2}/> : (hist as any).items.length === 0 ? <small>{tr("bv.no_history")}</small> :
        <table className="ui-table biz-table" data-testid="bv-history"><thead><tr><th>{tr("bv.h_when")}</th><th className="biz-hide-m">{tr("bv.h_source")}</th>
          <th>{tr("bv.h_score")}</th><th className="biz-hide-m">{tr("bv.channel")}</th><th>{tr("bv.h_text")}</th></tr></thead>
          <tbody>{(hist as any).items.map((x: any) => <tr key={x.id}><td className="biz-mono">{fmtDateTime(x.created_at)}</td>
            <td className="biz-hide-m">{tr(`bv.src_${x.source}` as Key)}{x.member_name ? ` · ${x.member_name}` : ""}</td>
            <td><StatusPill tone={x.passed ? "ok" : "risk"}>{x.score}</StatusPill></td><td className="biz-hide-m">{ch(x.channel)}</td>
            <td><small className="bv-excerpt">{x.text_excerpt}</small></td></tr>)}</tbody></table>}
    </section>
  </div>;
}
