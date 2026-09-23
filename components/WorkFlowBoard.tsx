"use client";
import {useEffect, useMemo, useState} from "react";
import {Icon, IconName} from "./Icon";
import {api} from "../lib/api";

type Task = {
  id: number | string; title: string; status: string; assignee?: string;
  owner_type?: "agent" | "human"; minutes_in_state?: number; note?: string;
  project?: string; subtitle?: string; blocked?: boolean; unassigned?: boolean;
};

const COLUMNS: {key: string; label: string; target: number; hint: string}[] = [
  {key: "backlog", label: "Backlog", target: 2880, hint: "target 2d"},
  {key: "spec_ready", label: "Sẵn spec", target: 480, hint: "target 8h"},
  {key: "in_progress", label: "Đang làm", target: 240, hint: "target 4h"},
  {key: "review", label: "Chờ duyệt", target: 120, hint: "target 2h"},
  {key: "done", label: "Xong hôm nay", target: 0, hint: "đã chốt"},
];

const DEMO: Task[] = [
  {id: 1, title: "Chuẩn hoá lỗi gateway", subtitle: "Runtime", status: "backlog", assignee: "Nina", owner_type: "agent", minutes_in_state: 620},
  {id: 2, title: "Trạng thái rỗng 12 console", subtitle: "UI v2", status: "backlog", assignee: "Kai", owner_type: "agent", minutes_in_state: 3120, note: "Quá target 4 tiếng. Không ai nhận từ thứ Hai.", unassigned: true},
  {id: 3, title: "Thu hồi khoá đã lộ", subtitle: "Bảo mật", status: "spec_ready", assignee: "Rudi", owner_type: "human", minutes_in_state: 96},
  {id: 4, title: "Gộp hai khối media 1024px", subtitle: "UI v2", status: "spec_ready", assignee: "Kai", owner_type: "agent", minutes_in_state: 240},
  {id: 5, title: "Lớp bộ nhớ bài học", subtitle: "Learning", status: "in_progress", assignee: "Nina", owner_type: "agent", minutes_in_state: 410, note: "Giữ lâu nhất hôm nay. Chờ migration 0013.", blocked: true},
  {id: 6, title: "Board Work Flow", subtitle: "UI v2", status: "in_progress", assignee: "Kai", owner_type: "agent", minutes_in_state: 85},
  {id: 7, title: "Hợp nhất token theme v2", subtitle: "UI v2", status: "review", assignee: "Rudi", owner_type: "human", minutes_in_state: 150, note: "Quá hạn duyệt 30 phút."},
  {id: 8, title: "Script đo endpoint mồ côi", subtitle: "G1", status: "review", assignee: "Rudi", owner_type: "human", minutes_in_state: 40},
  {id: 9, title: "Baseline KPI học hỏi", subtitle: "Learning", status: "done", assignee: "Nina", owner_type: "agent", minutes_in_state: 0},
];

const fmt = (min?: number) =>
  !min ? "0m" : min < 60 ? min + "m" : min < 1440 ? Math.round(min / 60) + "h" : Math.round(min / 1440) + "d";

function TaskCard({t, target, lit}: {t: Task; target: number; lit: boolean}) {
  const over = target > 0 && (t.minutes_in_state || 0) > target;
  return <article className={"taskCard" + (lit ? " focus" : "")}>
    <div className="tcHead">
      <span className={"tcAvatar " + (t.owner_type === "human" ? "blueTag" : "greenTag")}>
        {(t.assignee || "?").slice(0, 1).toUpperCase()}
      </span>
      <span className="tcTitleWrap">
        <b className="tcTitle">{t.title}</b>
        <span className="tcSub">{t.subtitle || t.project || "-"}</span>
      </span>
    </div>
    <div className="tcFoot">
      <span className="tcWho">{t.assignee || "Chưa giao"}</span>
      <span className={"timePill " + (over ? "red" : (t.minutes_in_state || 0) > target * 0.6 ? "amber" : "neutral")}>
        {fmt(t.minutes_in_state)}
      </span>
    </div>
    {t.note && <p className="tcNote">{t.note}</p>}
  </article>;
}

type ChipKey = "over" | "blocked" | "unassigned" | "human";

export function WorkFlowBoard() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [scope, setScope] = useState<"all" | "agent" | "human">("all");
  const [chip, setChip] = useState<ChipKey | null>("over");

  useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("demo") === "1") {
      setDemo(true); setTasks(DEMO); return;
    }
    let alive = true;
    api.tasks()
      .then((rows: any) => { if (alive) setTasks(Array.isArray(rows) ? rows : rows?.items || []); })
      .catch(() => { if (alive) setError("Không nối được dịch vụ nhiệm vụ. Kiểm tra backend rồi thử lại."); });
    return () => { alive = false; };
  }, []);

  const rows = tasks || [];
  const isOver = (t: Task) => {
    const col = COLUMNS.find(c => c.key === t.status);
    return !!col && col.target > 0 && (t.minutes_in_state || 0) > col.target;
  };
  const match = (t: Task, k: ChipKey | null) =>
    k === "over" ? isOver(t)
    : k === "blocked" ? !!t.blocked
    : k === "unassigned" ? !!t.unassigned
    : k === "human" ? t.owner_type === "human" : false;

  const inScope = useMemo(() => rows.filter(t => scope === "all" || t.owner_type === scope), [rows, scope]);
  const litCount = inScope.filter(t => match(t, chip)).length;

  const chips: {key: ChipKey; label: string}[] = [
    {key: "over", label: "Quá target"},
    {key: "blocked", label: "Đang bị chặn"},
    {key: "unassigned", label: "Chưa ai nhận"},
    {key: "human", label: "Cần người quyết"},
  ];

  const kpis: {icon: IconName; label: string; value: string; unit?: string; badge?: string; tone?: string}[] = [
    {icon: "pulse", label: "Đang làm ngay bây giờ", value: String(rows.filter(t => t.status === "in_progress").length), unit: "nhiệm vụ"},
    {icon: "shield", label: "Quá target vòng đời", value: String(rows.filter(isOver).length), badge: "cần xử lý", tone: "critical"},
    {icon: "check", label: "Chờ người duyệt", value: String(rows.filter(t => t.status === "review").length), badge: "chỉ người"},
    {icon: "chart", label: "Xong hôm nay", value: String(rows.filter(t => t.status === "done").length), unit: "trên " + rows.length},
  ];

  return <div className="wfWrap">
    {demo && <p className="wfDemo">Dữ liệu mẫu (?demo=1) — không phải số liệu thật</p>}
    {error && <div className="v8Error">{error}</div>}

    <section className="wfKpis">
      {kpis.map(k => <div key={k.label} className="wfKpi">
        <span className="iconTile wfKpiIcon"><Icon name={k.icon}/></span>
        <div className="wfKpiBody">
          <p className="wfKpiLabel">{k.label}</p>
          <div className="wfKpiValue">
            <span className="wfKpiNum">{k.value}</span>
            {k.unit && <small>{k.unit}</small>}
            {k.badge && <span className={"statBadge" + (k.tone === "critical" ? " critical" : "")}>{k.badge}</span>}
          </div>
        </div>
      </div>)}
    </section>

    <div className="wfToolbar">
      <div className="pillTabs wfGroup">
        <button className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>Tất cả</button>
        <button className={scope === "agent" ? "active" : ""} onClick={() => setScope("agent")}>Agent làm</button>
        <button className={scope === "human" ? "active" : ""} onClick={() => setScope("human")}>Người làm</button>
      </div>
      <p className="wfCount">{inScope.length} nhiệm vụ trong phạm vi này</p>
    </div>

    <div className="wfToolbar wfToolbar2">
      <div className="wfChips">
        {chips.map(c => {
          const n = inScope.filter(t => match(t, c.key)).length;
          return <button key={c.key} className={"pill filterChip" + (chip === c.key ? " selected" : "")}
            onClick={() => setChip(chip === c.key ? null : c.key)}>
            {c.label}<span className="chipCount">{n}</span>
          </button>;
        })}
      </div>
      <p className="wfCount">{chip ? "Làm nổi " + litCount + " trên " + inScope.length + " nhiệm vụ" : "Không làm nổi mục nào"}</p>
    </div>

    {!tasks && !error && <div className="emptyState">Đang tải nhiệm vụ...</div>}
    {tasks && rows.length === 0 && <div className="emptyState">
      <b>Chưa có nhiệm vụ nào</b>
      <span>Tạo nhiệm vụ đầu tiên hoặc để agent đề xuất từ một mission.</span>
    </div>}

    {tasks && rows.length > 0 && <div className="wfBoard">
      {COLUMNS.map(col => {
        const items = inScope.filter(t => t.status === col.key);
        return <section key={col.key} className={"kanCol" + (col.key === "done" ? " wfDone" : "")}>
          <header className="kanHead">
            <h4>{col.label}</h4>
            <span className="kanCount">{items.length}</span>
            <small className="wfHint">{col.hint}</small>
          </header>
          {items.map(t => <TaskCard key={t.id} t={t} target={col.target} lit={match(t, chip)}/>)}
          <button className="kanAdd">+ Thêm nhiệm vụ</button>
        </section>;
      })}
    </div>}
  </div>;
}
