"use client";
import {useEffect, useState} from "react";
import {apiTask, errorText} from "../lib/api";
import {t, lazy} from "../lib/i18n";

type Stage = {type: string; participants: number[]};
type Member = {id?: number; name?: string; member_type?: string; [k: string]: any};

const STATE_VI: Record<string, string> = lazy(() => ({
  not_started: t("taskPolicy.chua_bat_dau"), in_review: t("taskPolicy.dang_cho_quyet"), changes_requested: t("taskPolicy.da_yeu_cau_sua"),
  approved: t("taskPolicy.da_qua_du_chang"), needs_reviewer: t("taskPolicy.thieu_nguoi_duyet"),
}));

/** D2.2 — các chặng phải qua trước khi việc được "done", và trình soạn đơn giản. */
export function TaskPolicyPanel({taskId, members, onChange, refreshKey = 0}:
    {taskId: number; members: Member[]; onChange?: () => void; refreshKey?: number}) {
  const [data, setData] = useState<any>(null);
  const [draft, setDraft] = useState<Stage[] | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => apiTask.policy(taskId).then(d => { setData(d); setError(""); })
    .catch(e => setError(errorText(e)));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [taskId, refreshKey]);

  const name = (id?: number | null) => members.find(m => m.id === id)?.name || (id ? `#${id}` : "—");
  const stages: Stage[] = data?.policy?.stages || [];
  const st = data?.state || {};
  const idx = st.stage_index ?? 0;

  async function act(fn: () => Promise<any>) {
    setBusy(true); setError("");
    try { await fn(); await load(); onChange?.(); } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  return <div className="panel" data-testid="task-policy">
    <div className="panelHead">
      <div><b>{t("taskPolicy.chang_duyet")}</b></div>
      <small>{stages.length ? t("taskPolicy.vong", {p0: st.round || 0, p1: STATE_VI[st.status] || st.status}) : t("taskPolicy.khong_co")}</small>
    </div>
    {error && <div className="v8Error" data-testid="policy-error">{error}</div>}
    {st.missing_report && <div className="v8Error" data-testid="policy-missing-report">
      {t("taskPolicy.luot")}{String(st.missing_report)} {t("taskPolicy.ket_thuc_ma_nguoi_lam")}
    </div>}
    {!stages.length && !draft && <div className="v8Empty">
      {t("taskPolicy.viec_nay_xong_la_xong")}
    </div>}

    {!!stages.length && !draft && <ol data-testid="policy-stepper" style={{display: "grid", gap: 8, paddingLeft: 18, margin: 0}}>
      {stages.map((s, i) => {
        const state = st.status === "approved" || i < idx ? "passed"
          : i === idx && st.status === "in_review" ? "current" : "pending";
        return <li key={i} data-testid="policy-stage" data-state={state} style={{fontSize: 13}}>
          <b>{s.type === "review" ? "Review" : t("taskPolicy.phe_duyet")}</b>{" "}
          <span className={`prio ${state === "passed" ? "low" : state === "current" ? "mid" : ""}`}>
            {state === "passed" ? t("taskPolicy.da_qua") : state === "current" ? t("taskPolicy.dang_cho") : t("taskPolicy.chua_toi")}</span>
          <div style={{color: "var(--muted)"}}>
            {s.participants.map(name).join(", ")}
            {state === "current" && st.reviewer_member_id ? t("taskPolicy.nguoi_quyet", {p0: name(st.reviewer_member_id)}) : ""}
            {state === "current" && st.approval_id ? t("taskPolicy.yeu_cau_duyet_hop_viec", {p0: st.approval_id}) : ""}
          </div>
        </li>;
      })}
    </ol>}

    {st.status === "in_review" && stages[idx]?.type === "review" && !draft &&
      <div style={{display: "grid", gap: 6, marginTop: 10}}>
        <input data-testid="review-note" value={note} onChange={e => setNote(e.target.value)}
               placeholder={t("taskPolicy.nhan_xet_bat_buoc_khi")}/>
        <div style={{display: "flex", gap: 8}}>
          <button className="primary" data-testid="review-approve" disabled={busy}
                  onClick={() => act(() => apiTask.review(taskId, "approve", note))}>{t("taskPolicy.duyet")}</button>
          <button data-testid="review-revise" disabled={busy || !note.trim()}
                  onClick={() => act(() => apiTask.review(taskId, "revise", note))}>{t("taskPolicy.yeu_cau_sua")}</button>
        </div>
      </div>}

    {!!(st.history || []).length && !draft && <details style={{marginTop: 10}} data-testid="policy-history">
      <summary>{t("taskPolicy.lich_su_quyet_dinh")}{st.history.length})</summary>
      {st.history.map((h: any, i: number) => <div key={i} style={{fontSize: 12.5, marginTop: 4}}>
        {t("taskPolicy.vong_2")} {h.round} {t("taskPolicy.chang")} {h.stage_index + 1}: <b>{h.decision === "approve" ? t("taskPolicy.duyet_2") : t("taskPolicy.sua")}</b>
        {" "}{t("taskPolicy.boi")} {name(h.reviewer_member_id)} ({h.via}){h.note ? ` — ${h.note.slice(0, 160)}` : ""}
      </div>)}
    </details>}

    {draft ? <div style={{display: "grid", gap: 8, marginTop: 10}} data-testid="policy-editor">
      {draft.map((s, i) => <div key={i} style={{display: "flex", gap: 6, alignItems: "center"}}>
        <select data-testid="policy-type" value={s.type}
                onChange={e => setDraft(draft.map((x, j) => j === i ? {...x, type: e.target.value} : x))}>
          <option value="review">Review</option><option value="approval">{t("taskPolicy.phe_duyet")}</option>
        </select>
        <select data-testid="policy-participant" value={s.participants[0] || ""}
                onChange={e => setDraft(draft.map((x, j) => j === i ? {...x, participants: [Number(e.target.value)]} : x))}>
          <option value="">{t("taskPolicy.chon_nguoi")}</option>
          {members.map(m => <option key={m.id} value={m.id}>{m.name}{m.member_type === "agent" ? " (agent)" : ""}</option>)}
        </select>
        <button onClick={() => setDraft(draft.filter((_, j) => j !== i))}>{t("taskPolicy.bo")}</button>
      </div>)}
      <div style={{display: "flex", gap: 8}}>
        <button data-testid="policy-add" onClick={() => setDraft([...draft, {type: "review", participants: []}])}>{t("taskPolicy.them_chang")}</button>
        <button className="primary" data-testid="policy-save"
                disabled={busy || draft.some(s => !s.participants.length)}
                onClick={() => act(async () => { await apiTask.setPolicy(taskId, draft); setDraft(null); })}>{t("taskPolicy.luu")}</button>
        <button onClick={() => setDraft(null)}>{t("taskPolicy.huy")}</button>
      </div>
    </div> : st.status !== "in_review" &&
      <button style={{marginTop: 10}} data-testid="policy-edit"
              onClick={() => setDraft(stages.length ? stages.map(s => ({...s})) : [{type: "review", participants: []}])}>
        {stages.length ? t("taskPolicy.sua_chang") : t("taskPolicy.them_chang_duyet")}</button>}
  </div>;
}
