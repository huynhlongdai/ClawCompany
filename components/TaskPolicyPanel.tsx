"use client";
import {useEffect, useState} from "react";
import {apiTask, errorText} from "../lib/api";

type Stage = {type: string; participants: number[]};
type Member = {id?: number; name?: string; member_type?: string; [k: string]: any};

const STATE_VI: Record<string, string> = {
  not_started: "chưa bắt đầu", in_review: "đang chờ quyết", changes_requested: "đã yêu cầu sửa",
  approved: "đã qua đủ chặng", needs_reviewer: "thiếu người duyệt",
};

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
      <div><b>Chặng duyệt</b></div>
      <small>{stages.length ? `vòng ${st.round || 0} · ${STATE_VI[st.status] || st.status}` : "không có"}</small>
    </div>
    {error && <div className="v8Error" data-testid="policy-error">{error}</div>}
    {st.missing_report && <div className="v8Error" data-testid="policy-missing-report">
      Lượt #{String(st.missing_report)} kết thúc mà người làm không ghi báo cáo vào sổ — việc bị giữ lại
      ở "blocked" cho tới khi có báo cáo.
    </div>}
    {!stages.length && !draft && <div className="v8Empty">
      Việc này xong là xong, không cần ai duyệt. Thêm chặng để bắt buộc review hoặc phê duyệt trước khi "done".
    </div>}

    {!!stages.length && !draft && <ol data-testid="policy-stepper" style={{display: "grid", gap: 8, paddingLeft: 18, margin: 0}}>
      {stages.map((s, i) => {
        const state = st.status === "approved" || i < idx ? "passed"
          : i === idx && st.status === "in_review" ? "current" : "pending";
        return <li key={i} data-testid="policy-stage" data-state={state} style={{fontSize: 13}}>
          <b>{s.type === "review" ? "Review" : "Phê duyệt"}</b>{" "}
          <span className={`prio ${state === "passed" ? "low" : state === "current" ? "mid" : ""}`}>
            {state === "passed" ? "đã qua" : state === "current" ? "đang chờ" : "chưa tới"}</span>
          <div style={{color: "var(--muted)"}}>
            {s.participants.map(name).join(", ")}
            {state === "current" && st.reviewer_member_id ? ` · người quyết: ${name(st.reviewer_member_id)}` : ""}
            {state === "current" && st.approval_id ? ` · yêu cầu duyệt #${st.approval_id} (Hộp việc)` : ""}
          </div>
        </li>;
      })}
    </ol>}

    {st.status === "in_review" && stages[idx]?.type === "review" && !draft &&
      <div style={{display: "grid", gap: 6, marginTop: 10}}>
        <input data-testid="review-note" value={note} onChange={e => setNote(e.target.value)}
               placeholder="Nhận xét (bắt buộc khi yêu cầu sửa)"/>
        <div style={{display: "flex", gap: 8}}>
          <button className="primary" data-testid="review-approve" disabled={busy}
                  onClick={() => act(() => apiTask.review(taskId, "approve", note))}>Duyệt</button>
          <button data-testid="review-revise" disabled={busy || !note.trim()}
                  onClick={() => act(() => apiTask.review(taskId, "revise", note))}>Yêu cầu sửa</button>
        </div>
      </div>}

    {!!(st.history || []).length && !draft && <details style={{marginTop: 10}} data-testid="policy-history">
      <summary>Lịch sử quyết định ({st.history.length})</summary>
      {st.history.map((h: any, i: number) => <div key={i} style={{fontSize: 12.5, marginTop: 4}}>
        Vòng {h.round} · chặng {h.stage_index + 1}: <b>{h.decision === "approve" ? "DUYỆT" : "SỬA"}</b>
        {" "}bởi {name(h.reviewer_member_id)} ({h.via}){h.note ? ` — ${h.note.slice(0, 160)}` : ""}
      </div>)}
    </details>}

    {draft ? <div style={{display: "grid", gap: 8, marginTop: 10}} data-testid="policy-editor">
      {draft.map((s, i) => <div key={i} style={{display: "flex", gap: 6, alignItems: "center"}}>
        <select data-testid="policy-type" value={s.type}
                onChange={e => setDraft(draft.map((x, j) => j === i ? {...x, type: e.target.value} : x))}>
          <option value="review">Review</option><option value="approval">Phê duyệt</option>
        </select>
        <select data-testid="policy-participant" value={s.participants[0] || ""}
                onChange={e => setDraft(draft.map((x, j) => j === i ? {...x, participants: [Number(e.target.value)]} : x))}>
          <option value="">— chọn người —</option>
          {members.map(m => <option key={m.id} value={m.id}>{m.name}{m.member_type === "agent" ? " (agent)" : ""}</option>)}
        </select>
        <button onClick={() => setDraft(draft.filter((_, j) => j !== i))}>Bỏ</button>
      </div>)}
      <div style={{display: "flex", gap: 8}}>
        <button data-testid="policy-add" onClick={() => setDraft([...draft, {type: "review", participants: []}])}>+ Thêm chặng</button>
        <button className="primary" data-testid="policy-save"
                disabled={busy || draft.some(s => !s.participants.length)}
                onClick={() => act(async () => { await apiTask.setPolicy(taskId, draft); setDraft(null); })}>Lưu</button>
        <button onClick={() => setDraft(null)}>Huỷ</button>
      </div>
    </div> : st.status !== "in_review" &&
      <button style={{marginTop: 10}} data-testid="policy-edit"
              onClick={() => setDraft(stages.length ? stages.map(s => ({...s})) : [{type: "review", participants: []}])}>
        {stages.length ? "Sửa chặng" : "Thêm chặng duyệt"}</button>}
  </div>;
}
