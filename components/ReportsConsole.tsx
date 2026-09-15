"use client";
import {useEffect, useState} from "react";
import {api} from "../lib/api";
import {Icon} from "./Icon";

/* Báo cáo — màn hình có trong mẫu nhưng app chưa có route.
   Dữ liệu thật: /api/analytics (chỉ số có trị hiện tại, trị trước và mục
   tiêu) và /api/reports (báo cáo đã sinh).

   Mẫu có biểu đồ đường "Doanh thu 6 tháng qua". Bảng analytics_metrics chỉ
   lưu HAI mốc (hiện tại, kỳ trước) nên vẽ đường 6 tháng là bịa. Ở đây là cột
   so sánh hai mốc thật, cộng vạch mục tiêu — cùng thông tin, không thêm số
   nào không có. */

type Row = Record<string, any>;

function fmt(value: number, unit: string) {
  if (unit === "USD") {
    if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
    if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
    return `$${value.toLocaleString("vi-VN")}`;
  }
  return `${value.toLocaleString("vi-VN")}${unit === "%" ? "%" : unit ? ` ${unit}` : ""}`;
}

/* Cột so sánh: kỳ trước vs hiện tại, kèm vạch mục tiêu. Vẽ bằng SVG thuần —
   không thêm thư viện chart cho hai cột. */
function CompareBars({current, previous, target, unit}: {
  current: number; previous: number; target: number; unit: string;
}) {
  const max = Math.max(current, previous, target) || 1;
  const h = (v: number) => Math.max(3, Math.round((v / max) * 92));
  return <svg viewBox="0 0 160 120" style={{width: "100%", maxWidth: 190, height: 120}}>
    {[["Kỳ trước", previous, 26, "#c9cbe8"], ["Hiện tại", current, 86, "url(#g)"]].map(
      ([label, value, x, fill]) => <g key={String(label)}>
        <defs>
          <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7c5cff"/><stop offset="1" stopColor="#5b5be6"/>
          </linearGradient>
        </defs>
        <rect x={Number(x)} y={104 - h(Number(value))} width="44" rx="7"
              height={h(Number(value))} fill={String(fill)}/>
        <text x={Number(x) + 22} y="117" textAnchor="middle" fontSize="9" fill="#79809a">{label}</text>
      </g>)}
    {!!target && <>
      <line x1="10" x2="150" y1={104 - h(target)} y2={104 - h(target)}
            stroke="#e11d48" strokeWidth="1" strokeDasharray="3 3"/>
      <text x="150" y={100 - h(target)} textAnchor="end" fontSize="8" fill="#e11d48">
        mục tiêu {fmt(target, unit)}
      </text>
    </>}
  </svg>;
}

export function ReportsConsole() {
  const [metrics, setMetrics] = useState<Row[]>([]);
  const [reports, setReports] = useState<Row[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [m, r] = await Promise.all([api.analytics(), api.reports()]);
        setMetrics((m as Row[]) || []);
        setReports((r as Row[]) || []);
      } catch (e: any) { setError(e?.message || "Không tải được báo cáo"); }
    })();
  }, []);

  return <div>
    {error && <div className="v8Error" style={{marginBottom: 14}}>{error}</div>}

    <section className="v14Metrics" style={{gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))"}}>
      {metrics.map(m => {
        const delta = m.previous_value
          ? ((m.current_value - m.previous_value) / Math.abs(m.previous_value)) * 100 : null;
        return <div key={m.id} className="metric">
          <div className="metricIcon"><Icon name="chart" size={16}/></div>
          <label>{m.metric_key}</label>
          <strong>{fmt(m.current_value, m.unit)}</strong>
          {delta !== null && <span className={`delta${delta < 0 ? " down" : ""}`}>
            {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}% · mục tiêu {fmt(m.target_value, m.unit)}
          </span>}
        </div>;
      })}
      {!metrics.length && <div className="v8Empty">Chưa có chỉ số nào trong analytics_metrics.</div>}
    </section>

    <section className="v13Split">
      <div className="panel">
        <div className="panelHead">
          <div><b>Báo cáo đã sinh</b></div>
          <small>{reports.length} bản · từ /api/reports</small>
        </div>
        <table className="dataTable">
          <thead><tr><th>Tiêu đề</th><th>Loại</th><th>Chu kỳ</th><th>Người nhận</th><th>Trạng thái</th></tr></thead>
          <tbody>
            {reports.map(r => <tr key={r.id}>
              <td><b>{r.title}</b>{r.summary && <small style={{display: "block"}}>{r.summary}</small>}</td>
              <td>{r.report_type || "—"}</td>
              <td>{r.period || "—"}</td>
              <td>{r.audience || "—"}</td>
              <td><span className={`tag ${r.status === "ready" ? "greenTag" : "orangeTag"}`}>{r.status}</span></td>
            </tr>)}
            {!reports.length && <tr><td colSpan={5}><div className="v8Empty">Chưa có báo cáo.</div></td></tr>}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <div className="panelHead"><div><b>So sánh kỳ</b></div><small>hai mốc thật</small></div>
        <div style={{display: "grid", gap: 16}}>
          {metrics.map(m => <div key={m.id}>
            <b style={{fontSize: 12.5}}>{m.metric_key}</b>
            <CompareBars current={m.current_value} previous={m.previous_value}
                         target={m.target_value} unit={m.unit}/>
          </div>)}
        </div>
        <small style={{display: "block", marginTop: 8}}>
          analytics_metrics chỉ lưu hai mốc (hiện tại và kỳ trước), nên không có
          đường 6 tháng như bản thiết kế — vẽ ra sẽ là số bịa.
        </small>
      </div>
    </section>
  </div>;
}
