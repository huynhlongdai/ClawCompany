"use client";
import {useEffect, useState} from "react";
import Link from "next/link";
import {api, apiTask} from "../lib/api";
import {Icon, IconName} from "./Icon";

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
const KIND_STYLE: Record<string, {label: string; icon: IconName; tint: string}> = {
  attempt:  {label: "Bắt tay làm",   icon: "pulse",  tint: "blue"},
  result:   {label: "Kết quả",       icon: "check",  tint: "green"},
  review:   {label: "Nhận xét",      icon: "shield", tint: "amber"},
  handoff:  {label: "Bàn giao",      icon: "users",  tint: "violet"},
  decision: {label: "Quyết định",    icon: "crown",  tint: "pink"},
  blocker:  {label: "Vướng",         icon: "bell",   tint: "pink"},
  note:     {label: "Ghi chú",       icon: "doc",    tint: "blue"},
};

/* Kết quả đo được. Rỗng nghĩa là CHƯA ĐO ĐƯỢC — khác với thất bại, nên nó có
   nhãn riêng chứ không bị bỏ trống. */
const OUTCOME_LABEL: Record<string, {text: string; cls: string}> = {
  success:   {text: "đạt",        cls: "low"},
  partial:   {text: "một phần",  cls: "mid"},
  failed:    {text: "không đạt", cls: "high"},
  rejected:  {text: "bị từ chối", cls: "high"},
  blocked:   {text: "bị chặn",   cls: "high"},
  cancelled: {text: "đã huỷ",    cls: "mid"},
};

const BLOCK_TINT = ["#6366f1", "#0ea5e9", "#14b8a6", "#f59e0b", "#a855f7",
                    "#ef4444", "#64748b"];

function stamp(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("vi-VN", {day: "2-digit", month: "2-digit",
                                    hour: "2-digit", minute: "2-digit"});
}

export function TaskDetail({taskId}: {taskId: number}) {
  const [task, setTask] = useState<Row | null>(null);
  const [journal, setJournal] = useState<Row | null>(null);
  const [pack, setPack] = useState<Row | null>(null);
  const [members, setMembers] = useState<Row[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    const miss: string[] = [];
    // Mỗi nguồn hỏng độc lập: màn hình không được trắng vì một endpoint lỗi.
    try { setTask(await apiTask.get(taskId)); } catch { miss.push("công việc"); }
    try { setJournal(await apiTask.journal(taskId)); } catch { miss.push("sổ ghi"); }
    try { setPack(await apiTask.contextPack(taskId)); } catch { miss.push("gói ngữ cảnh"); }
    try { setMembers((await api.members() as Row[]) || []); } catch { miss.push("nhân sự"); }
    setFailed(miss);
    setLoading(false);
  }

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [taskId]);

  if (loading) return <div className="v8Empty">Đang tải công việc…</div>;

  const digest = journal?.digest || {};
  const entries: Row[] = journal?.entries || [];
  const owner = members.find(m => m.id === task?.assignee_member_id);

  return <>
    {/* ---------------- công việc này là gì, của ai ---------------- */}
    <div className="panel">
      <div className="panelHead">
        <div>
          <b>{task?.title || `Công việc #${taskId}`}</b>
          <small style={{display: "block"}}>
            {task?.status ? `trạng thái: ${task.status}` : ""}
            {task?.priority ? ` · ưu tiên: ${task.priority}` : ""}
            {owner ? ` · đang thuộc ${owner.name}` : " · chưa có người nhận"}
          </small>
        </div>
        <Link href="/app/os?tab=tasks">Về bảng việc →</Link>
      </div>

      {task?.description && <p style={{margin: "4px 0 12px", fontSize: 13.5}}>
        {task.description}
      </p>}

      <section className="v14Metrics"
               style={{gridTemplateColumns: "repeat(auto-fit,minmax(168px,1fr))"}}>
        <div className="metric">
          <div className="metricIcon"><Icon name="doc" size={16}/></div>
          <label>Mục trong sổ ghi</label><strong>{digest.entries ?? 0}</strong>
        </div>
        <div className="metric">
          <div className="metricIcon"><Icon name="users" size={16}/></div>
          <label>Đã qua tay</label>
          <strong>{(digest.hands || []).length || 0}</strong>
          <small style={{color: "var(--muted)", fontSize: 11}}>
            {(digest.hands || []).join(" → ") || "chưa ai"}
          </small>
        </div>
        <div className="metric">
          <div className="metricIcon"><Icon name="chart" size={16}/></div>
          <label>Tỉ lệ đạt</label>
          <strong>{digest.success_rate == null ? "chưa đo được"
            : `${digest.success_rate}%`}</strong>
          <small style={{color: "var(--muted)", fontSize: 11}}>
            {digest.measurable_outcomes ?? 0}/{digest.entries ?? 0} mục đo được
          </small>
        </div>
        <div className="metric">
          <div className="metricIcon"><Icon name="pulse" size={16}/></div>
          <label>Phiên runtime</label>
          <strong style={{fontSize: 13, wordBreak: "break-all"}}>
            {task?.runtime_session_key ? task.runtime_session_key.split(":").slice(-1)[0] : "—"}
          </strong>
        </div>
      </section>

      {digest.success_rate == null && (digest.entries ?? 0) > 0 &&
        <small style={{display: "block", marginTop: 10, color: "var(--muted)"}}>
          "Chưa đo được" khác với 0%: chưa có mục nào trong sổ ghi kết quả đo
          được, nên mọi tỉ lệ tính ra đều là số nói dối.
        </small>}

      {!!failed.length && <div className="v8Error" style={{marginTop: 12}}>
        Không tải được: {failed.join(", ")}. Các phần còn lại vẫn là dữ liệu thật.
      </div>}
    </div>

    <div style={{display: "grid", gridTemplateColumns: "minmax(0,1.35fr) minmax(0,1fr)",
                 gap: 18, alignItems: "start"}}>
      <div style={{display: "grid", gap: 18}}>
        <JournalPanel entries={entries} kinds={journal?.kinds || []}/>
        <ContextPackPanel pack={pack}/>
      </div>
      <HandoffPanel taskId={taskId} members={members} ownerId={task?.assignee_member_id}
                    onDone={load}/>
    </div>
  </>;
}

/* ------------------------------------------------- sổ ghi theo thời gian */

function JournalPanel({entries, kinds}: {entries: Row[]; kinds: string[]}) {
  const [open, setOpen] = useState<number | null>(null);
  const [filter, setFilter] = useState<string>("");

  const shown = filter ? entries.filter(e => e.kind === filter) : entries;
  const present = kinds.filter(k => entries.some(e => e.kind === k));

  return <div className="panel">
    <div className="panelHead">
      <div><b>Sổ ghi công việc</b></div>
      <small>task_journal_entries</small>
    </div>

    {!!present.length && <div className="pillTabs">
      <button className={filter === "" ? "active" : ""} onClick={() => setFilter("")}>
        Tất cả ({entries.length})
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
          Sổ ghi trống. Việc này chưa có lượt nào — đó là sự thật, không phải lỗi
          tải dữ liệu.
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
                  {!entry.outcome && <small style={{opacity: .65}}>chưa đo kết quả</small>}
                </div>
                <div style={{marginLeft: 18, marginTop: 2, fontSize: 13}}>
                  {entry.summary}
                </div>
                {entry.detail && <div style={{marginLeft: 18, marginTop: 4}}>
                  <button onClick={() => setOpen(expanded ? null : entry.seq)}
                          style={{background: "none", border: "none", padding: 0,
                                  color: "var(--accent)", fontSize: 12}}>
                    {expanded ? "Ẩn chi tiết" : "Xem chi tiết"}
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
      Chỉ dòng tóm tắt đi vào prompt của agent; phần chi tiết ở lại đây. Nhờ vậy
      một việc chạy 50 lần vẫn không làm nổ ngân sách ký tự.
    </small>
  </div>;
}

/* ------------------------------------------- gói ngữ cảnh agent sẽ nhận */

function ContextPackPanel({pack}: {pack: Row | null}) {
  const [showText, setShowText] = useState(false);
  if (!pack) return <div className="panel"><div className="v8Empty">
    Không đọc được gói ngữ cảnh.
  </div></div>;

  const blocks: Row[] = pack.blocks || [];
  const total = Math.max(1, pack.chars || 1);
  const never: number[] = pack.never_trimmed || [];

  return <div className="panel">
    <div className="panelHead">
      <div><b>Gói ngữ cảnh agent sẽ nhận</b></div>
      <small>{pack.chars}/{pack.budget_chars} ký tự</small>
    </div>

    {/* Thanh ngân sách: mỗi đoạn rộng theo số ký tự THẬT của khối đó. */}
    <div style={{display: "flex", height: 10, borderRadius: 999, overflow: "hidden",
                 border: "1px solid var(--line)", marginBottom: 12}}>
      {blocks.filter(b => b.chars > 0).map(b =>
        <div key={b.index} title={`${b.index}. ${b.title} — ${b.chars} ký tự`}
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
            {b.trimmed ? "đã lược"
              : locked ? "không cắt"
              : b.empty ? "trống" : ""}
          </span>
          <span style={{color: "var(--muted)", textAlign: "right",
                        fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap"}}>
            {b.chars}/{b.budget}
          </span>
        </div>;
      })}
    </div>
    <small style={{display: "block", marginTop: 8, color: "var(--muted)"}}>
      "không cắt" = khối luôn được giữ nguyên khi gói vượt ngân sách. Thứ tự cắt
      là 4 → 3 → 5 → 1.
    </small>

    {!!(pack.trimmed || []).length && <div className="v8Error" style={{marginTop: 10}}>
      Đã lược để vừa ngân sách: {(pack.trimmed || []).join("; ")}.
      Thứ tự cắt là khối 4 → 3 → 5 → 1; khối 2 (việc), 6 (luật) và 7 (thoả thuận)
      không bao giờ bị cắt.
    </div>}

    <div style={{marginTop: 12}}>
      <button onClick={() => setShowText(!showText)}>
        {showText ? "Ẩn nội dung gói" : "Xem nguyên văn gói sẽ gửi"}
      </button>
      {showText && <pre style={{
        whiteSpace: "pre-wrap", fontSize: 12, marginTop: 10, maxHeight: 420,
        overflow: "auto", background: "var(--cream)", padding: 12, borderRadius: 10,
        fontFamily: "ui-monospace, monospace",
      }}>{pack.text}</pre>}
    </div>

    <small style={{display: "block", marginTop: 10, color: "var(--muted)"}}>
      Đây là nguyên văn prompt mà agent nhận, dựng bằng đúng hàm mà lệnh giao
      việc dùng — không phải bản mô phỏng.
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
      setError(detail?.message || detail || e?.message || "Bàn giao thất bại");
    } finally { setBusy(false); }
  }

  return <div className="panel">
    <div className="panelHead">
      <div><b>Bàn giao cho người khác</b></div>
      <small>artifact_handoffs</small>
    </div>

    <label style={{fontSize: 12.5, fontWeight: 600}}>Giao cho ai</label>
    <select value={to} onChange={e => setTo(e.target.value)}
            style={{width: "100%", padding: 9, borderRadius: 9, marginTop: 4,
                    border: "1px solid var(--line)"}}>
      <option value="">— chọn người nhận —</option>
      {candidates.map(m =>
        <option key={m.id} value={m.id}>
          {m.name} · {m.role || "chưa có chức danh"}
          {m.member_type === "agent" ? " (AI)" : ""}
        </option>)}
    </select>
    {target && target.member_type !== "agent" &&
      <small style={{display: "block", marginTop: 6, color: "var(--muted)"}}>
        {target.name} là nhân sự người: bàn giao sẽ vào hộp thư của họ, hệ thống
        không tự làm việc thay người.
      </small>}

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 14}}>
      Mục đích
    </label>
    <select value={purpose} onChange={e => setPurpose(e.target.value)}
            style={{width: "100%", padding: 9, borderRadius: 9, marginTop: 4,
                    border: "1px solid var(--line)"}}>
      <option value="continue_work">Làm tiếp</option>
      <option value="review">Soát lại</option>
      <option value="approve">Phê duyệt</option>
      <option value="publish">Đăng/phát hành</option>
    </select>

    <label style={{fontSize: 12.5, fontWeight: 600, display: "block", marginTop: 14}}>
      Hướng dẫn cho người nhận
    </label>
    <textarea value={instructions} onChange={e => setInstructions(e.target.value)}
              rows={6} placeholder="Việc gì cần làm tiếp, điều gì đã thử rồi, cái gì phải tránh…"
              style={{width: "100%", padding: 10, borderRadius: 9, marginTop: 4,
                      border: "1px solid var(--line)", fontSize: 13}}/>
    <small style={{display: "block", marginTop: 4, color: "var(--muted)"}}>
      Nội dung này vào khối 5 của gói ngữ cảnh, nên người nhận đọc được nó ngay
      khi bắt tay làm.
    </small>

    <label style={{display: "flex", gap: 8, alignItems: "flex-start",
                   marginTop: 14, fontSize: 12.5}}>
      <input type="checkbox" checked={dispatch} style={{marginTop: 3}}
             onChange={e => setDispatch(e.target.checked)}/>
      <span>
        Giao việc luôn cho người nhận
        <small style={{display: "block", color: "var(--muted)"}}>
          Bỏ chọn thì chỉ ghi sổ và chuyển hồ sơ. Mỗi lượt giao việc cho agent là
          một lời gọi model có phí.
        </small>
      </span>
    </label>

    <button className="primary" onClick={submit}
            disabled={busy || !to}
            style={{marginTop: 14, width: "100%"}}>
      {busy ? "Đang bàn giao…" : "Bàn giao"}
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
    <b>Đã bàn giao cho {result.to_member_name}.</b>
    <ul style={{margin: "6px 0 0 18px", fontSize: 12.5}}>
      <li>Ghi sổ: {d.journal?.recorded
        ? `xong (mục #${d.journal.journal_seq})` : `không — ${d.journal?.reason}`}</li>
      {d.reassign?.reassigned &&
        <li>Chủ việc đã chuyển sang người nhận</li>}
      <li>Giao việc: {ok ? "đã chạy" : `chưa — lý do \`${d.reason}\``}</li>
      {d.runtime_session_key && <li>Phiên: <code>{d.runtime_session_key}</code></li>}
      {result.created_handoff_note &&
        <li>Việc chưa có sản phẩm nào nên hệ thống đã tạo một phiếu bàn giao</li>}
    </ul>
    {!ok && d.note && <small style={{display: "block", marginTop: 6}}>{d.note}</small>}
  </div>;
}
