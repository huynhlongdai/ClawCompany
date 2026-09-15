"use client";
import {Suspense, useEffect, useMemo, useState} from "react";
import {useRouter, useSearchParams} from "next/navigation";
import {apiV10, apiV17} from "../lib/api";
import {Icon, IconName} from "./Icon";

/* Trang chủ — hiện thực hoá Screen 01 của design/clawcompany-ui-canvas.html.
   Mọi số liệu lấy từ /api/v17/workspace/* và /api/v10/events; không có dữ
   liệu demo nào trong file này. */

type Row = Record<string, any>;
type Tab = "home" | "companies" | "people" | "agents" | "projects" | "tasks" | "knowledge";

const TABS: [Tab, string][] = [
  ["home", "Trang chủ"], ["companies", "Công ty"], ["people", "Nhân sự"], ["agents", "AI Agents"],
  ["projects", "Dự án"], ["tasks", "Nhiệm vụ"], ["knowledge", "Kiến thức"],
];

/* Số liệu chính đứng riêng thành dải 4 ô; phần còn lại là hàng phụ, vì một
   dải 8 ô bằng nhau thì không nói được cái nào quan trọng. */
const PRIMARY: [string, string, IconName][] = [
  ["companies", "Công ty", "building"],
  ["members", "Nhân sự", "users"],
  ["agents", "AI Agents", "sparkle"],
  ["projects_active", "Dự án đang chạy", "board"],
];
const SECONDARY: [string, string][] = [
  ["humans", "Người"], ["customers", "Khách hàng"],
  ["approvals_pending", "Chờ phê duyệt"], ["knowledge_documents", "Tài liệu"],
];

const COMPANY_HUES = ["pink", "blue", "violet", "green"];

function Tag({value}: {value?: string | null}) {
  const v = (value || "").toLowerCase();
  const cls = /active|done|completed|healthy|indexed|ok/.test(v) ? "tag greenTag"
    : /planning|pending|review|in_progress|backlog|todo/.test(v) ? "tag orangeTag"
    : /risk|failed|blocked|denied|cancelled|error/.test(v) ? "tag redTag" : "tag blueTag";
  return <span className={cls}>{value || "—"}</span>;
}

function Bar({value}: {value: number}) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return <div className="progress" title={`${pct}%`}><span style={{width: `${pct}%`}}/></div>;
}

function initials(name?: string) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();
}

/* API trả success_rate dạng phần trăm (98.0), nhưng model khai Float mặc
   định 0.0 nên vài bản ghi cũ có thể lưu dạng tỉ lệ (0.98). Bản trước nhân
   100 vô điều kiện và hiển thị "9800%". Đoán theo biên độ, và nói rõ khi
   không có số. */
function percent(value?: number | null) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${Math.round(n <= 1 ? n * 100 : n)}%`;
}

function timeOf(iso?: string) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—"
    : d.toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"});
}

/* Tên event của company_event_bus là dạng "task.assigned",
   "openclaw.task.dispatched" — đọc thẳng thì khô, nên dịch sang tiếng người.
   Không có trong bảng thì giữ nguyên tên gốc, đừng bịa. */
const EVENT_LABELS: Record<string, string> = {
  "task.created": "Tạo nhiệm vụ",
  "task.assigned": "Giao nhiệm vụ",
  "task.moved": "Chuyển trạng thái",
  "task.status_changed": "Đổi trạng thái",
  "project.created": "Tạo dự án",
  "project.archived": "Lưu trữ dự án",
  "company.created": "Tạo công ty",
  "department.created": "Tạo phòng ban",
  "member.created": "Thêm thành viên",
  "knowledge.created": "Thêm tài liệu",
  "openclaw.task.dispatched": "Giao việc cho agent",
  "board.write.guarded": "Ghi có guard",
  "board.write.conflict": "Xung đột ghi",
  "delegation.budget.overrun": "Vượt trần ngân sách",
};

const TAB_IDS = new Set<string>(TABS.map(([id]) => id));

export function WorkspaceCockpit() {
  /* Ranh giới Suspense bắt buộc: bên trong có useSearchParams, mà Next 14
     không prerender tĩnh được nếu thiếu nó. */
  return <Suspense fallback={<div className="v8Empty">Đang tải workspace…</div>}>
    <WorkspaceCockpitInner/>
  </Suspense>;
}

function WorkspaceCockpitInner() {
  /* Sidebar trỏ tới /app/os?tab=agents, /app/os?tab=projects... nên tab phải
     đọc từ URL. Bản trước giữ tab trong state nội bộ, nên mọi liên kết
     "Công ty / Nhân sự / AI Agents / Dự án" trên sidebar đều rơi về Trang chủ
     -- một lời hứa điều hướng bị bỏ lửng. */
  const router = useRouter();
  const params = useSearchParams();
  const urlTab = params.get("tab");
  const [tab, setTabState] = useState<Tab>(
    urlTab && TAB_IDS.has(urlTab) ? (urlTab as Tab) : "home");

  useEffect(() => {
    const next = params.get("tab");
    setTabState(next && TAB_IDS.has(next) ? (next as Tab) : "home");
  }, [params]);

  // Đổi tab thì đổi luôn URL: chia sẻ được đường dẫn, và nút back hoạt động.
  function setTab(next: Tab) {
    setTabState(next);
    router.replace(next === "home" ? "/app/os" : `/app/os?tab=${next}`, {scroll: false});
  }

  const [overview, setOverview] = useState<Row | null>(null);
  const [chart, setChart] = useState<Row | null>(null);
  const [people, setPeople] = useState<Row[]>([]);
  const [agents, setAgents] = useState<Row[]>([]);
  const [projects, setProjects] = useState<Row[]>([]);
  const [tasks, setTasks] = useState<Row[]>([]);
  const [docs, setDocs] = useState<Row[]>([]);
  const [events, setEvents] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true); setError("");
    try {
      const [o, c, h, a, p, t, k] = await Promise.all([
        apiV17.overview(), apiV17.orgChart(), apiV17.people("human"), apiV17.people("agent"),
        apiV17.projects(), apiV17.tasks(), apiV17.knowledge(),
      ]);
      setOverview(o); setChart(c); setPeople(h || []); setAgents(a || []);
      setProjects(p || []); setTasks(t || []); setDocs(k || []);
      // Feed hoạt động là phụ: event bus lỗi thì trang vẫn phải dùng được.
      try { setEvents((await apiV10.events() as Row[] || []).slice(0, 8)); } catch { setEvents([]); }
    } catch (e: any) {
      setError(e?.message || "Không tải được dữ liệu workspace");
    } finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);

  const k = overview?.kpis || {};
  const companies: Row[] = overview?.companies || [];
  const orgName = overview?.organization?.name || "Workspace";
  /* Thành viên theo công ty, lấy từ org-chart để vẽ chồng avatar. */
  function membersOf(companyId: number): Row[] {
    const company = (chart?.companies || []).find((c: Row) => c.id === companyId);
    if (!company) return [];
    const fromDepts = (company.departments || []).flatMap((d: Row) => d.members || []);
    return [...fromDepts, ...(company.unassigned_members || [])];
  }

  const totalMembers = useMemo(
    () => companies.reduce((sum, c) => sum + (c.members || 0) + (c.agents || 0), 0),
    [companies],
  );

  return <div>
    {error && <div className="v8Error" style={{marginBottom: 14}}>
      {error} — đăng nhập lại hoặc kiểm tra API.
    </div>}

    {/* ---------- hero ---------- */}
    <section className="v14Hero">
      <div>
        <div className="eyebrow">Chào mừng trở lại</div>
        <h2>{orgName}</h2>
        <p>
          Toàn bộ số liệu trên trang này đọc trực tiếp từ <code>/api/v17/workspace/*</code>
          {" "}và <code>/api/v10/events</code> — không có dữ liệu demo.
        </p>
        <div className="quote">“Một công ty lớn là tập hợp những trí tuệ lớn, cả người và AI,
          cùng hướng về một tương lai có ý nghĩa.”</div>
        <div className="heroActions" style={{marginTop: 16}}>
          <button className="v8Primary" onClick={load} disabled={busy}>
            {busy ? "Đang tải…" : "Làm mới số liệu"}
          </button>
          <a className="v8Ghost" href="/app/workspace-ops">Vận hành tổ chức →</a>
        </div>
      </div>
      <div className="heroArt" style={{textAlign: "center"}}>
        {/* Chân dung Nina: ảnh thật trong public/, không phải vòng gradient.
            Mockup dùng một ảnh nhân vật lớn làm điểm nhìn của hero. */}
        <img src="/nina.jpg" alt="Nina — AI Chief of Staff"
             className="portrait" width={168} height={168}
             style={{width: 168, height: 168}}/>
        <div style={{marginTop: 12}}>
          <b style={{display: "block", fontSize: 14}}>Nina</b>
          <small>AI Chief of Staff · luôn ở cạnh bạn</small>
        </div>
      </div>
    </section>

    {/* ---------- tab ---------- */}
    <nav className="moduleTabs">
      {TABS.map(([id, label]) =>
        <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}
    </nav>

    {tab === "home" && <>
      <section className="v14Metrics" style={{gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))"}}>
        {PRIMARY.map(([key, label, icon]) =>
          <div key={key} className="metric">
            <div className="metricIcon"><Icon name={icon} size={16}/></div>
            <label>{label}</label>
            <strong>{k[key] ?? 0}</strong>
          </div>)}
      </section>

      <section className="v14Metrics" style={{gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))"}}>
        {SECONDARY.map(([key, label]) =>
          <div key={key} className="metric" style={{minHeight: 68}}>
            <label>{label}</label>
            <strong style={{fontSize: 19}}>{k[key] ?? 0}</strong>
          </div>)}
      </section>

      {/* ---------- cây tổ chức ---------- */}
      <section className="panel" style={{marginBottom: 18}}>
        <div className="panelHead">
          <div>
            <b>Tổ chức của bạn</b>
            <small style={{marginLeft: 8}}>{orgName} · tổng quan các công ty con</small>
          </div>
          <a className="v8Ghost" href="/app/workspace-ops">Thêm công ty</a>
        </div>
        <div className="holdingTree">
          <div className="rootNode">
            <span className="crown"><Icon name="crown" size={16}/></span>
            <b>{orgName}</b>
            <small>{companies.length} công ty con · {totalMembers} ghế</small>
          </div>
          <div className="companyGrid">
            {companies.map((c, i) =>
              <div key={c.id} className="companyCard">
                <div className="companyTop">
                  <div className={`companyLogo ${COMPANY_HUES[i % COMPANY_HUES.length]}`}>
                    {initials(c.name)}
                  </div>
                  <div style={{minWidth: 0}}>
                    <b>{c.name}</b>
                    <small>{c.industry || "Chưa phân ngành"}</small>
                  </div>
                </div>
                <div className="companyMeta">
                  {/* Chồng avatar như mockup. Số trong vòng tròn là chữ đầu
                      tên thành viên thật của công ty đó, lấy từ org-chart;
                      không có thì hiện tổng số ghế. */}
                  <span className="stack">
                    {(membersOf(c.id).slice(0, 3)).map((m: Row) =>
                      <i key={m.id} title={m.name}>{initials(m.name)}</i>)}
                    {!membersOf(c.id).length && <i>·</i>}
                    <em>{(c.members || 0) + (c.agents || 0)} ghế</em>
                  </span>
                  <span>{c.projects || 0} dự án</span>
                </div>
              </div>)}
            {!companies.length && <div className="v8Empty">Chưa có công ty nào.</div>}
          </div>
        </div>
      </section>

      {/* ---------- dự án + hoạt động ---------- */}
      <section className="v13Split">
        <div style={{display: "flex", flexDirection: "column", gap: 16}}>
        <div className="panel">
          <div className="panelHead">
            <div><b>Dự án gần đây</b></div>
            <button className="v8Ghost" onClick={() => setTab("projects")}>Xem tất cả →</button>
          </div>
          <table className="dataTable">
            <thead><tr><th>Dự án</th><th>Công ty</th><th>Tiến độ</th><th>Trạng thái</th></tr></thead>
            <tbody>
              {projects.slice(0, 6).map(p =>
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>{p.company_name || "—"}</td>
                  <td>
                    <Bar value={p.progress || 0}/>
                    <small style={{marginTop: 3, display: "block"}}>
                      {p.progress || 0}% · {p.tasks_done ?? 0}/{p.tasks_total ?? 0} việc
                    </small>
                  </td>
                  <td><Tag value={p.status}/></td>
                </tr>)}
              {!projects.length && <tr><td colSpan={4}><div className="v8Empty">Chưa có dự án.</div></td></tr>}
            </tbody>
          </table>
        </div>
          <div className="panel">
            <div className="panelHead">
              <div><b>Nhiệm vụ cần chú ý</b></div>
              <button className="v8Ghost" onClick={() => setTab("tasks")}>Xem bảng việc →</button>
            </div>
            <table className="dataTable">
              <thead><tr><th>Nhiệm vụ</th><th>Người / Agent</th><th>Ưu tiên</th><th>Trạng thái</th></tr></thead>
              <tbody>
                {tasks.filter(t => ["in_progress", "review", "blocked", "todo"].includes(t.status))
                  .slice(0, 5).map(t =>
                  <tr key={t.id}>
                    <td>{t.title}</td>
                    <td>{t.assignee_name || <small>chưa giao</small>}{t.assignee_type === "agent" ? " ✦" : ""}</td>
                    <td>{t.priority}</td>
                    <td><Tag value={t.status}/></td>
                  </tr>)}
                {!tasks.some(t => ["in_progress", "review", "blocked", "todo"].includes(t.status)) &&
                  <tr><td colSpan={4}><div className="v8Empty">Không có việc nào đang mở.</div></td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panelHead">
            <div><b>AI Agents</b></div>
            <button className="v8Ghost" onClick={() => setTab("agents")}>Xem tất cả →</button>
          </div>
          <div>
            {agents.slice(0, 6).map(m => {
              /* Trạng thái lấy từ lifecycle thật của runtime: active = đã bind
                 và khớp gateway, detached = ghế mồ côi (v19 reconcile phát
                 hiện). Mockup gọi là Online/Đang chạy/Bận — ở đây gọi đúng
                 tên trạng thái mà hệ thống biết, không bịa "online". */
              const life = m.agent?.lifecycle || "";
              const cls = life === "active" ? "" : life === "detached" ? "busy" : "off";
              const label = life === "active" ? "đã bind"
                : life === "detached" ? "rời gateway" : "chưa bind";
              return <div key={m.id} className="agentLine">
                <span className="avatarSm">{initials(m.name)}</span>
                <div style={{minWidth: 0}}>
                  <b>{m.name}</b>
                  <small>{m.role || "—"}{m.agent?.model ? ` · ${m.agent.model}` : ""}</small>
                </div>
                <span className={`statusPill ${cls}`}>{label}</span>
              </div>;
            })}
            {!agents.length && <div className="v8Empty">Chưa có agent nào.</div>}
          </div>
        </div>
      </section>

      {/* ---------- sơ đồ tổ chức ---------- */}
      <section className="panel" style={{marginTop: 18}}>
        <div className="panelHead">
          <div><b>Sơ đồ tổ chức</b><small style={{marginLeft: 8}}>công ty → phòng ban → thành viên</small></div>
        </div>
        <div className="v10Grid">
          {(chart?.companies || []).map((c: Row) =>
            <div key={c.id} className="orgNode" style={{padding: 14, textAlign: "left"}}>
              <b>{c.name}</b>
              <small>{c.industry || "—"}</small>
              <div className="divider" style={{margin: "10px 0"}}/>
              {(c.departments || []).map((d: Row) =>
                <div key={d.id} className="railItem">
                  <div>
                    <b>{d.name}</b>
                    <small>{(d.members || []).length} thành viên</small>
                  </div>
                  {!!(d.members || []).length && <div className="faces">
                    {(d.members || []).slice(0, 4).map((m: Row) => <i key={m.id} title={m.name}/>)}
                  </div>}
                </div>)}
              {!(c.departments || []).length && <small>Chưa có phòng ban.</small>}
              {!!(c.unassigned_members || []).length &&
                <div className="railItem"><div><b>Chưa xếp phòng</b>
                  <small>{c.unassigned_members.length} thành viên</small></div></div>}
            </div>)}
          {!chart && <div className="v8Empty">Đang tải sơ đồ…</div>}
        </div>
      </section>
    </>}

    {tab === "companies" && <section className="panel">
      <div className="panelHead"><div><b>Công ty</b></div><small>{companies.length} bản ghi</small></div>
      <table className="dataTable">
        <thead><tr><th>Tên</th><th>Ngành</th><th>Trạng thái</th><th>Nhân sự</th><th>Agents</th><th>Dự án</th></tr></thead>
        <tbody>{companies.map(c =>
          <tr key={c.id}><td>{c.name}</td><td>{c.industry || "—"}</td><td><Tag value={c.status}/></td>
            <td>{c.members}</td><td>{c.agents}</td><td>{c.projects}</td></tr>)}
          {!companies.length && <tr><td colSpan={6}><div className="v8Empty">Chưa có công ty.</div></td></tr>}
        </tbody>
      </table>
    </section>}

    {(tab === "people" || tab === "agents") && <section className="panel">
      <div className="panelHead">
        <div><b>{tab === "people" ? "Nhân sự" : "AI Agents"}</b></div>
        <small>{(tab === "people" ? people : agents).length} bản ghi</small>
      </div>
      <table className="dataTable">
        <thead><tr>
          <th>Tên</th><th>Vai trò</th><th>Công ty</th><th>Phòng ban</th>
          {tab === "agents" && <><th>Model</th><th>Runtime</th><th>Thành công</th><th>Chi phí 30d</th></>}
          <th>Trạng thái</th>
        </tr></thead>
        <tbody>
          {(tab === "people" ? people : agents).map(m =>
            <tr key={m.id}>
              <td>
                <div className="person">
                  <span className="avatarSm">{initials(m.name)}</span>
                  <div><b>{m.name}</b><small>{m.member_type === "agent" ? "agent" : "người"}</small></div>
                </div>
              </td>
              <td>{m.role || "—"}</td>
              <td>{m.company_name || "—"}</td>
              <td>{m.department_name || "—"}</td>
              {tab === "agents" && <>
                <td><code>{m.agent?.model || "—"}</code></td>
                <td>
                  {m.agent?.runtime_agent_id
                    ? <div>
                        <code>{m.agent.runtime_agent_id}</code>
                        {/* lifecycle "detached" nghĩa là ghế này không còn
                            khớp agent nào trên gateway — chính trạng thái mà
                            /api/v19 reconcile phát hiện. Hiện nó ra thay vì
                            để người dùng đoán. */}
                        <span className={`tag ${m.agent.lifecycle === "active" ? "greenTag" : "orangeTag"}`}
                              style={{marginLeft: 6}}>
                          {m.agent.lifecycle === "detached" ? "rời gateway" : m.agent.lifecycle}
                        </span>
                      </div>
                    : <small>chưa bind</small>}
                </td>
                <td>{percent(m.agent?.success_rate)}</td>
                <td>{m.agent ? `$${m.agent.cost_30d}` : "—"}</td>
              </>}
              <td><Tag value={m.status}/></td>
            </tr>)}
          {!(tab === "people" ? people : agents).length &&
            <tr><td colSpan={9}><div className="v8Empty">Chưa có dữ liệu.</div></td></tr>}
        </tbody>
      </table>
    </section>}

    {tab === "projects" && <section className="panel">
      <div className="panelHead"><div><b>Dự án</b></div><small>{projects.length} bản ghi</small></div>
      <table className="dataTable">
        <thead><tr><th>Dự án</th><th>Công ty</th><th>Tiến độ</th><th>Nhiệm vụ</th><th>Trạng thái</th></tr></thead>
        <tbody>{projects.map(p =>
          <tr key={p.id}>
            <td>{p.name}</td><td>{p.company_name || "—"}</td>
            <td><Bar value={p.progress || 0}/><small style={{display: "block", marginTop: 3}}>{p.progress || 0}%</small></td>
            <td>{p.tasks_done}/{p.tasks_total}</td><td><Tag value={p.status}/></td>
          </tr>)}
          {!projects.length && <tr><td colSpan={5}><div className="v8Empty">Chưa có dự án.</div></td></tr>}
        </tbody>
      </table>
    </section>}

    {tab === "tasks" && <section className="panel">
      <div className="panelHead"><div><b>Nhiệm vụ</b></div><small>{tasks.length} bản ghi</small></div>
      <table className="dataTable">
        <thead><tr><th>Nhiệm vụ</th><th>Dự án</th><th>Người / Agent</th><th>Ưu tiên</th><th>Trạng thái</th></tr></thead>
        <tbody>{tasks.map(t =>
          <tr key={t.id}>
            <td>{t.title}</td><td>{t.project_name || "—"}</td>
            <td>{t.assignee_name || "—"}{t.assignee_type === "agent" ? " ✦" : ""}</td>
            <td>{t.priority}</td><td><Tag value={t.status}/></td>
          </tr>)}
          {!tasks.length && <tr><td colSpan={5}><div className="v8Empty">Chưa có nhiệm vụ.</div></td></tr>}
        </tbody>
      </table>
    </section>}

    {tab === "knowledge" && <section className="panel">
      <div className="panelHead"><div><b>Kiến thức</b></div><small>{docs.length} tài liệu</small></div>
      <table className="dataTable">
        <thead><tr><th>Tài liệu</th><th>Công ty</th><th>Nguồn</th><th>Mức truy cập</th><th>Đã index</th></tr></thead>
        <tbody>{docs.map(d =>
          <tr key={d.id}>
            <td>{d.title}</td><td>{d.company_name || "—"}</td><td><code>{d.source_type}</code></td>
            <td>{d.access_level}</td>
            <td><span className={d.indexed ? "tag greenTag" : "tag orangeTag"}>{d.indexed ? "Có" : "Chưa"}</span></td>
          </tr>)}
          {!docs.length && <tr><td colSpan={5}><div className="v8Empty">Chưa có tài liệu.</div></td></tr>}
        </tbody>
      </table>
    </section>}
  </div>;
}
