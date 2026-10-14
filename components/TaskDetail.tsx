"use client";
import {useEffect, useState} from "react";
import Link from "next/link";
import {api, apiTask} from "../lib/api";
import {Icon, IconName} from "./Icon";
import {TaskLinksPanel, TaskRunsPanel, TaskWakeupsPanel} from "./TaskGraphPanels";
import {TaskPolicyPanel} from "./TaskPolicyPanel";
import {t, lazy, intlLocale} from "../lib/i18n";

/* WP-4.3 UI — Chi tiết một công việc: sổ ghi, bàn giao, và gói ngữ cảnh.

   Màn hình này trả lời ba câu mà bảng việc không trả lời được:

   1. **Việc này đã đi tới đâu?**  -> sổ ghi theo thời gian (task_journal_entries)
   2. **Giao cho ai tiếp?**        -> bàn giao kèm hướng dẫn (artifact_handoffs)
   3. **Agent sẽ nhận được gì?**   -> gói ngữ cảnh bảy khối (work_context)

   Hai quyết định thiết kế của màn hình này:

   * **Thanh ngân sách bảy khối.** Mỗi khối là một đoạn rộng theo số ký tự thật
     của nó, nên người đọc thấy ngay khối nào đang chiếm prompt. Khối 2, 6, 7 có
     dấu khoá: đó là ba khối *không bao giờ bị cắt*, vì thiếu bối cảnh thì agent
     làm kém còn thiếu luật thì agent làm sai. Thanh này không phải trang trí —
     nó là thứ duy nhất cho thấy quy tắc cắt bất đối xứng.

   * **Xem trước là thật, không phải mô phỏng.** Endpoint gọi đúng hàm
     `work_context.build_pack` mà `agent_dispatch` gọi. Một màn hình xem trước
     hiện khác cái agent nhận thì tệ hơn là không có. */

type Row = Record<string, any>;

/* Loại mục sổ ghi: icon và màu mang nghĩa, không phải để đẹp. */
const KIND_STYLE: Record<string, {label: string; icon: IconName; tint: string}> = lazy(() => ({
  attempt:  {label: t("task.bat_tay_lam"),   icon: "pulse",  tint: "blue"},
  result:   {label: t("task.ket_qua"),       icon: "check",  tint: "green"},
  review:   {label: t("task.nhan_xet"),      icon: "shield", tint: "amber"},
  handoff:  {label: t("task.ban_giao"),      icon: "users",  tint: "violet"},
  decision: {label: t("task.quyet_dinh"),    icon: "crown",  tint: "pink"},
  blocker:  {label: t("task.vuong"),         icon: "bell",   tint: "pink"},
  note:     {label: t("task.ghi_chu"),       icon: "doc",    tint: "blue"},
}));

/* Kết quả đo được. Rỗng nghĩa là CHƯA ĐO ĐƯỢC — khác với thất bại, nên nó có
   nhãn riêng chứ không bị bỏ trống. */
const OUTCOME_LABEL: Record<string, {text: string; cls: string}> = lazy(() => ({
  success:   {text: t("task.dat"),        cls: "low"},
  partial:   {text: t("task.mot_phan"),  cls: "mid"},
  failed:    {text: t("task.khong_dat"), cls: "high"},
  rejected:  {text: t("task.bi_tu_choi"), cls: "high"},
  blocked:   {text: t("task.bi_chan"),   cls: "high"},
  cancelled: {text: t("task.da_huy"),    cls: "mid"},
}));

const BLOCK_TINT = ["#6366f1", "#0ea5e9", "#14b8a6", "#f59e0b", "#a855f7",
                    "#ef4444", "#64748b"];

function stamp(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(intlLocale(), {day: "2-digit", month: "2-digit",
                                    hour: "2-digit", minute: "2-digit"});
}

/* UI v2: nhãn tiếng Việt thay cho mã enum thô (in_progress, high) ở dòng tiêu đề. */
const STATUS_VI: Record<string, string> = lazy(() => ({backlog: t("task.ton_dong"), todo: t("task.can_lam"), in_progress: t("task.dang_lam"), review: t("task.cho_duyet"), blocked: t("task.bi_chan_2"), done: "Xong", cancelled: t("task.da_huy_2")}));
const PRIO_VI: Record<string, string> = lazy(() => ({urgent: t("task.khan"), high: "Cao", medium: t("task.vua"), low: t("task.thap")}));

export function TaskDetail({taskId}: {taskId: number}) {
  const [task, setTask] = useState<Row | null>(null);
  const [journal, setJournal] = useState<Row | null>(null);
  const [pack, setPack] = useState<Row | null>(null);
  const [members, setMembers] = useState<Row[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  async function load() {
    const miss: string[] = [];
    // Mỗi nguồn hỏng độc lập: màn hình không được trắng vì một endpoint lỗi.
    try { setTask(await apiTask.get(taskId)); } catch { miss.push(t("task.cong_viec")); }
    try { setJournal(await apiTask.journal(taskId)); } catch { miss.push(t("task.so_ghi")); }
    try { setPack(await apiTask.contextPack(taskId)); } catch { miss.push(t("task.goi_ngu_canh")); }
    try { setMembers((await api.members() as Row[]) || []); } catch { miss.push(t("task.nhan_su")); }
    setFailed(miss);
    setLoading(false);
    setTick(n => n + 1);
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [taskId]);

  if (loading) return <div className="v8Empty">{t("task.dang_tai_cong_viec")}</div>;

  const digest = journal?.digest || {};
  const entries: Row[] = journal?.entries || [];
  const owner = members.find(m => m.id === task?.assignee_member_id);

  return <div className="tdPage">
    {/* ---------------- công việc này là gì, của ai ---------------- */}
    <div className="panel">
      <div className="panelHead">
        <div>
          <b>{task?.title || t("task.cong_viec_2", {p0: taskId})}</b>
          <small style={{display: "block"}}>
            {task?.status ? t("task.trang_thai", {p0: STATUS_VI[task.status] || task.status}) : ""}
            {task?.priority ? t("task.uu_tien", {p0: PRIO_VI[task.priority] || task.priority}) : ""}
            {owner ? t("task.dang_thuoc", {p0: owner.name}) : t("task.chua_co_nguoi_nhan")}
          </small>
        </div>
        <Link href={`/app/work?peek=${taskId}`}>{t("task.ve_cong_viec")}</Link>
      </div>

      {task?.description && <p style={{margin: "4px 0 12px", fontSize: 13.5}}>
        {task.description}
      </p>}

      <section className="v14Metrics"
               style={{gridTemplateColumns: "repeat(auto-fit,minmax(168px,1fr))"}}>
        <div className="metric">
          <div className="metricIcon"><Icon name="doc" size={16}/></div>
          <label>{t("task.muc_trong_so_ghi")}</label><strong>{digest.entries ?? 0}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon"><Icon name="users" size={16}/></div>
          <label>{t("task.da_qua_tay")}</label>
          <strong>{(digest.hands || []).length || 0}</strong>
          <small style={{color: "var(--muted)", fontSize: 11}}>
            {(digest.hands || []).join(" → ") || t("task.chua_ai")}
          </small>
        </div>
        <div className="metric">
          <div className="metricIcon"><Icon name="chart" size={16}/></div>
          <label>{t("task.ti_le_dat")}</label>
          <strong>{digest.success_rate == null ? t("task.chua_do_duoc")
            : `${digest.success_rate}%`}</strong>
          <small style={{color: "var(--muted)", fontSize: 11}}>
            {digest.measurable_outcomes ?? 0}/{digest.entries ?? 0} {t("task.muc_do_duoc")}
          </small>
        </div>
        <div className="metric">
          <div className="metricIcon"><Icon name="pulse" size={16}/></div>
          <label>{t("task.phien_runtime")}</label>
          <strong style={{fontSize: 13, wordBreak: "break-all"}}>
            {task?.runtime_session_key ? task.runtime_session_key.split(":").slice(-1)[0] : "—"}
          </strong>
        </div>
      </section>

      {digest.success_rate == null && (digest.entries ?? 0) > 0 &&
        <small style={{display: "block", marginTop: 10, color: "var(--muted)"}}>
          {t("task.chua_do_duoc_khac_voi")}
        </small>}

      {!!failed.length && <div className="v8Error" style={{marginTop: 12}}>
        {t("task.khong_tai_duoc")} {failed.join(", ")}{t("task.cac_phan_con_lai_van")}
      </div>}
    </div>

    <div className="tdCols">
      <div className="tdCol">
        <JournalPanel entries={entries} kinds={journal?.kinds || []} taskId={taskId} onDone={load}/>
        <ContextPackPanel pack={pack}/>
      </div>
      <div className="tdCol">
        <HandoffPanel taskId={taskId} members={members} ownerId={task?.assignee_member_id}
                      onDone={load}/>
        <TaskPolicyPanel taskId={taskId} members={members} onChange={load} refreshKey={tick}/>
        <TaskLinksPanel taskId={taskId} onChange={load}/>
        <TaskRunsPanel taskId={taskId} refreshKey={tick}/>
        <TaskWakeupsPanel taskId={taskId} refreshKey={tick}/>
      </div>
    </div>
  </div>;
}

/* ------------------------------------------------- sổ ghi theo thời gian */

function JournalPanel({entries, kinds, taskId, onDone}: {entries: Row[]; kinds: string[];
                                                     taskId: number; onDone: () => void}) {
  const [open, setOpen] = useState<number | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState("");

  async function send() {
    if (!note.trim()) return;
    setSending(true); setSent("");
    try {
      const out = await apiTask.comment(taskId, note.trim());
      setNote("");
      setSent(out?.woke?.length ? t("task.da_ghi_danh_thuc_seat", {p0: out.woke.length}) : t("task.da_ghi_vao_so"));
      onDone();
    } catch (e: any) { setSent(t("task.khong_ghi_duoc", {p0: e?.message || e})); }
    setSending(false);
  }

  const shown = filter ? entries.filter(e => e.kind === filter) : entries;
  const present = kinds.filter(k => entries.some(e => e.kind === k));

  return <div className="panel">
    <div className="panelHead">
      <div><b>{t("task.so_ghi_cong_viec")}</b></div>
      <small>task_journal_entries</small>
    </div>

    <div style={{display: "flex", gap: 8, marginBottom: 10}}>
      <input data-testid="journal-input" value={note} onChange={e => setNote(e.target.value)}
             placeholder={t("task.ghi_mot_dong_go_ten")}
             onKeyDown={e => { if (e.key === "Enter") send(); }}
             style={{flex: 1, padding: "7px 10px", border: "1px solid var(--line)", borderRadius: 8, fontSize: 13}}/>
      <button className="primary" data-testid="journal-send" disabled={sending || !note.trim()} onClick={send}>
        {sending ? t("task.dang_ghi") : "Ghi"}
      </button>
    </div>
    {sent && <small data-testid="journal-sent" style={{display: "block", marginBottom: 8, color: "var(--muted)"}}>{sent}</small>}

    {!!present.length && <div className="pillTabs">
      <button className={filter === "" ? "active" : ""} onClick={() => setFilter("")}>
        {t("task.tat_ca")}{entries.length})
      </button>
      {present.map(kind => {
        const style = KIND_STYLE[kind] || KIND_STYLE.note;
        const count = entries.filter(e => e.kind === kind).length;
        return <button key={kind} className={filter === kind ? "active" : ""}
                       onClick={() => setFilter(kind)}>
          {style.label} ({count})
        </button>;
      })}
    </div>}

    {!shown.length
      ? <div className="v8Empty">
          {t("task.so_ghi_trong_viec_nay")}
        </div>
      : <div className="timeline">
          {shown.map(entry => {
            const style = KIND_STYLE[entry.kind] || KIND_STYLE.note;
            const outcome = OUTCOME_LABEL[entry.outcome];
            const expanded = open === entry.seq;
            return <div key={entry.seq} className="timeRow">
              <span>{stamp(entry.created_at)}</span>
              <div>
                <i><span className={`iconTile ${style.tint}`}
                         style={{width: 22, height: 22, borderRadius: 7}}>
                  <Icon name={style.icon} size={12}/>
                </span></i>
                <div style={{display: "flex", gap: 8, alignItems: "baseline",
                             flexWrap: "wrap", marginLeft: 18}}>
                  <b style={{display: "inline"}}>{entry.actor_name}</b>
                  <small>{style.label}</small>
                  {outcome && <span className={`prio ${outcome.cls}`}>{outcome.text}</span>}
                  {!entry.outcome && <small style={{opacity: .65}}>{t("task.chua_do_ket_qua")}</small>}
                </div>
                <div style={{marginLeft: 18, marginTop: 2, fontSize: 13}}>
                  {entry.summary}
                </div>
                {entry.detail && <div style={{marginLeft: 18, marginTop: 4}}>
                  <button onClick={() => setOpen(expanded ? null : entry.seq)}
                          style={{background: "none", border: "none", padding: 0,
                                  color: "var(--accent)", fontSize: 12}}>
                    {expanded ? t("task.an_chi_tiet") : t("task.xem_chi_tiet")}
                  </button>
                  {expanded && <pre style={{
                    whiteSpace: "pre-wrap", fontSize: 12, marginTop: 6,
                    background: "var(--cream)", padding: 10, borderRadius: 8,
                    fontFamily: "ui-monospace, monospace",
                  }}>{entry.detail}</pre>}
                </div>}
              </div>
            </div>;
          })}
        </div>}

    <small style={{display: "block", marginTop: 12, color: "var(--muted)"}}>
      {t("task.chi_dong_tom_tat_di")}
    </small>
  </div>;
}

/* ------------------------------------------- gói ngữ cảnh agent sẽ nhận */

function ContextPackPanel({pack}: {pack: Row | null}) {
  const [showText, setShowText] = useState(false);
  if (!pack) return <div className="panel"><div className="v8Empty">
    {t("task.khong_doc_duoc_goi_ngu")}
  </div></div>;

  const blocks: Row[] = pack.blocks || [];
  const total = Math.max(1, pack.chars || 1);
  const never: number[] = pack.never_trimmed || [];

  return <div className="panel">
    <div className="panelHead">
      <div><b>{t("task.goi_ngu_canh_agent_se")}</b></div>
      <small>{pack.chars}/{pack.budget_chars} {t("task.ky_tu")}</small>
    </div>

    {/* Thanh ngân sách: mỗi đoạn rộng theo số ký tự THẬT của khối đó. */}
    <div style={{display: "flex", height: 10, borderRadius: 999, overflow: "hidden",
                 border: "1px solid var(--line)", marginBottom: 12}}>
      {blocks.filter(b => b.chars > 0).map(b =>
        <div key={b.index} title={t("task.ky_tu_2", {p0: b.index, p1: b.title, p2: b.chars})}
             style={{width: `${(b.chars / total) * 100}%`,
                     background: BLOCK_TINT[(b.index - 1) % BLOCK_TINT.length]}}/>)}
    </div>

    {/* Grid cố định cột: chấm màu · số · tên khối · trạng thái cắt · ký tự.
        Dùng flex ở đây làm nhãn "không cắt" xuống dòng và chèn vào cột số —
        thấy rõ trong ảnh chụp lần đầu ở _reports/ui/. */}
    <div style={{display: "grid", gap: 7}}>
      {blocks.map(b => {
        const locked = never.includes(b.index);
        return <div key={b.index} style={{
          display: "grid",
          gridTemplateColumns: "10px 20px minmax(0,1fr) 78px 84px",
          gap: 8, alignItems: "center", fontSize: 12.5,
        }}>
          <span style={{width: 10, height: 10, borderRadius: 3,
                        background: b.chars ? BLOCK_TINT[(b.index - 1) % BLOCK_TINT.length]
                                            : "var(--line)"}}/>
          <b style={{fontWeight: 600, color: "var(--muted)"}}>{b.index}.</b>
          <span style={{overflow: "hidden", textOverflow: "ellipsis",
                        whiteSpace: "nowrap"}}>{b.title}</span>
          <span style={{fontSize: 11, textAlign: "right", whiteSpace: "nowrap",
                        color: locked ? "var(--accent)" : "var(--muted)"}}>
            {b.trimmed ? t("task.da_luoc")
              : locked ? t("task.khong_cat")
              : b.empty ? t("task.trong") : ""}
          </span>
          <span style={{color: "var(--muted)", textAlign: "right",
                        fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap"}}>
            {b.chars}/{b.budget}
          </span>
        </div>;
      })}
    </div>
    <small style={{display: "block", marginTop: 8, color: "var(--muted)"}}>
      {t("task.khong_cat_khoi_luon_duoc")}
    </small>

    {!!(pack.trimmed || []).length && <div className="v8Error" style={{marginTop: 10}}>
      {t("task.da_luoc_de_vua_ngan")} {(pack.trimmed || []).join("; ")}{t("task.thu_tu_cat_la_khoi")}
    </div>}

    <div style={{marginTop: 12}}>
      <button onClick={() => setShowText(!showText)}>
        {showText ? t("task.an_noi_dung_goi") : t("task.xem_nguyen_van_goi_se")}
      </button>
      {showText && <pre style={{
        whiteSpace: "pre-wrap", fontSize: 12, marginTop: 10, maxHeight: 420,
        overflow: "auto", background: "var(--cream)", padding: 12, borderRadius: 10,
        fontFamily: "ui-monospace, monospace",
      }}>{pack.text}</pre>}
    </div>

    <small style={{display: "block", marginTop: 10, color: "var(--muted)"}}>
      {t("task.day_la_nguyen_van_prompt")}
    </small>
  </div>;
}

/* ------------------------------------------------------ bàn giao cho người khác */

function HandoffPanel({taskId, members, ownerId, onDone}:
                      {taskId: number; members: Row[]; ownerId?: number;
                       onDone: () => void}) {
  const [to, setTo] = useState<string>("");
  const [instructions, setInstructions] = useState("");
  const [purpose, setPurpose] = useState("continue_work");
  const [dispatch, setDispatch] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Row | null>(null);
  const [error, setError] = useState("");

  const candidates = members.filter(m => m.id !== ownerId && m.status === "active");
  const target = candidates.find(m => String(m.id) === to);

  async function submit() {
    if (!to) return;
    setBusy(true); setError(""); setResult(null);
    try {
      const out = await apiTask.handoff(taskId, {
        to_member_id: Number(to), instructions, purpose, dispatch,
      });
      setResult(out);
      setInstructions("");
      onDone();
    } catch (e: any) {
      const detail = e?.detail || e?.body?.detail;
      setError(detail?.message || detail || e?.message || t("task.ban_giao_that_bai"));
    } finally { setBusy(false); }
  }

  return <div className="panel">
    <div className="panelHead">
      <div><b>{t("task.ban_giao_cho_nguoi_khac")}</b></div>
      <small>artifact_handoffs</small>
    </div>

    <label style={{fontSize: 12.5, fontWeight: 600}}>Giao cho ai</label>
    <select value={to} onChange={e => setTo(e.target.value)}
            style={{width: "100%", padding: 9, borderRadius: 9, marginTop: 4,
                    border: "1px solid var(--line)"}}>
      <option value="">{t("task.chon_nguoi_nhan")}</option>
      {candidates.map(m =>
        <option key={m.id} value={m.id}>
          {m.name} · {m.role || t("task.chua_co_chuc_danh")}
          {m.member_type === "agent" ? " (AI)" : ""}
        </option>)}
    </select>
    {target && target.member_type !== "agent" &&
      <small style={{display: "block", marginTop: 6, color: "var(--muted)"}}>
        {target.name} {t("task.la_nhan_su_nguoi_ban")}
      </small>}

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 14}}>
      {t("task.muc_dich")}
    </label>
    <select value={purpose} onChange={e => setPurpose(e.target.value)}
            style={{width: "100%", padding: 9, borderRadius: 9, marginTop: 4,
                    border: "1px solid var(--line)"}}>
      <option value="continue_work">{t("task.lam_tiep")}</option>
      <option value="review">{t("task.soat_lai")}</option>
      <option value="approve">{t("task.phe_duyet")}</option>
      <option value="publish">{t("task.dang_phat_hanh")}</option>
    </select>

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 14}}>
      {t("task.huong_dan_cho_nguoi_nhan")}
    </label>
    <textarea value={instructions} onChange={e => setInstructions(e.target.value)}
              rows={6} placeholder={t("task.viec_gi_can_lam_tiep")}
              style={{width: "100%", padding: 10, borderRadius: 9, marginTop: 4,
                      border: "1px solid var(--line)", fontSize: 13}}/>
    <small style={{display: "block", marginTop: 4, color: "var(--muted)"}}>
      {t("task.noi_dung_nay_vao_khoi")}
    </small>

    <label style={{display: "flex", gap: 8, alignItems: "flex-start",
                   marginTop: 14, fontSize: 12.5}}>
      <input type="checkbox" checked={dispatch} style={{marginTop: 3}}
             onChange={e => setDispatch(e.target.checked)}/>
      <span>
        {t("task.giao_viec_luon_cho_nguoi")}
        <small style={{display: "block", color: "var(--muted)"}}>
          {t("task.bo_chon_thi_chi_ghi")}
        </small>
      </span>
    </label>

    <button className="primary" onClick={submit}
            disabled={busy || !to}
            style={{marginTop: 14, width: "100%"}}>
      {busy ? t("task.dang_ban_giao") : t("task.ban_giao")}
    </button>

    {error && <div className="v8Error" style={{marginTop: 10}}>{error}</div>}

    {result && <HandoffResult result={result}/>}
  </div>;
}

function HandoffResult({result}: {result: Row}) {
  const d = result.dispatch || {};
  const ok = d.dispatched;
  // `.v8Empty` căn giữa (đúng cho trạng thái trống, sai cho một danh sách kết
  // quả) — thấy rõ trong _reports/ui/task-handoff-result.png. Ghi đè tại chỗ.
  return <div className={ok ? "v8Empty" : "v8Error"}
              style={{marginTop: 12, textAlign: "left"}}>
    <b>{t("task.da_ban_giao_cho")} {result.to_member_name}.</b>
    <ul style={{margin: "6px 0 0 18px", fontSize: 12.5}}>
      <li>{t("task.ghi_so")} {d.journal?.recorded
        ? t("task.xong_muc", {p0: d.journal.journal_seq}) : t("task.khong", {p0: d.journal?.reason})}</li>
      {d.reassign?.reassigned &&
        <li>{t("task.chu_viec_da_chuyen_sang")}</li>}
      <li>{t("task.giao_viec")} {ok ? t("task.da_chay") : t("task.chua_ly_do", {p0: d.reason})}</li>
      {d.runtime_session_key && <li>{t("task.phien")} <code>{d.runtime_session_key}</code></li>}
      {result.created_handoff_note &&
        <li>{t("task.viec_chua_co_san_pham")}</li>}
    </ul>
    {!ok && d.note && <small style={{display: "block", marginTop: 6}}>{d.note}</small>}
  </div>;
}
