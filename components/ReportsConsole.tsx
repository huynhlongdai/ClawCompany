"use client";
import {useEffect, useState} from "react";
import {api, apiV36} from "../lib/api";
import {Icon} from "./Icon";

/* Báo cáo — màn hình có trong mẫu nhưng app chưa có route.
   Dữ liệu thật: /api/analytics (chỉ số có trị hiện tại, trị trước và mục
   tiêu) và /api/reports (báo cáo đã sinh).

   v36 thêm bảng ``metric_samples``, nên biểu đồ đường của bản thiết kế nay
   vẽ được từ số thật. Nhưng số điểm đúng bằng số lần đã chốt số: sau
   migration là hai điểm (backfill từ trị hiện tại và trị kỳ trước), và dài ra
   mỗi lần gọi POST /api/v36/metrics/snapshot. Biểu đồ nói rõ điều đó thay vì
   trông như một chuỗi đo liên tục sáu tháng. */

type Row = Record<string, any>;

function fmt(value: number, unit: string) {
  if (unit === "USD") {
    if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
    if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
    return `$${value.toLocaleString("vi-VN")}`;
  }
  return `${value.toLocaleString("vi-VN")}${unit === "%" ? "%" : unit ? ` ${unit}` : ""}`;
}

/* Đường lịch sử chỉ số, vẽ bằng SVG thuần từ metric_samples. Không thêm thư
   viện chart: một đường và vài điểm không đáng 40KB JavaScript.

   Một điểm thì không vẽ đường được — hiện đúng một dấu, và nói ra. */
function HistoryLine({points, unit}: {points: {period: string; value: number}[]; unit: string}) {
  if (!points.length) return <div className="v8Empty">Chưa có mẫu nào.</div>;

  const width = 260, height = 110, pad = 26;
  const values = points.map(p => p.value);
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  const x = (i: number) => points.length === 1
    ? width / 2
    : pad + (i * (width - pad * 2)) / (points.length - 1);
  const y = (v: number) => height - 18 - ((v - min) / span) * (height - 42);

  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

  return <svg viewBox={`0 0 ${width} ${height}`} style={{width: "100%", height: 120}}>
    <defs>
      <linearGradient id="hl" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="#7c5cff"/><stop offset="1" stopColor="#5b5be6"/>
      </linearGradient>
    </defs>
    {points.length > 1 && <path d={path} fill="none" stroke="url(#hl)" strokeWidth="2"
                                strokeLinejoin="round" strokeLinecap="round"/>}
    {points.map((p, i) => <g key={p.period}>
      <circle cx={x(i)} cy={y(p.value)} r="3.5" fill="#5b5be6"/>
      <text x={x(i)} y={height - 4} textAnchor="middle" fontSize="8.5" fill="#79809a">
        {p.period}
      </text>
    </g>)}
    <text x={pad} y="12" fontSize="8.5" fill="#79809a">{fmt(max, unit)}</text>
    <text x={pad} y={height - 22} fontSize="8.5" fill="#79809a">{fmt(min, unit)}</text>
  </svg>;
}

export function ReportsConsole() {
  const [metrics, setMetrics] = useState<Row[]>([]);
  const [reports, setReports] = useState<Row[]>([]);
  const [history, setHistory] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [m, r] = await Promise.all([api.analytics(), api.reports()]);
      setMetrics((m as Row[]) || []);
      setReports((r as Row[]) || []);
    } catch (e: any) { setError(e?.message || "Không tải được báo cáo"); }
    try { setHistory(await apiV36.metricHistory()); } catch { setHistory(null); }
  }
  useEffect(() => { load(); }, []);

  async function snapshot() {
    setBusy(true);
    try { await apiV36.snapshotMetrics("month"); await load(); }
    catch (e: any) { setError(String(e?.message || e).slice(0, 200)); }
    finally { setBusy(false); }
  }

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
        <div className="panelHead">
          <div><b>Lịch sử chỉ số</b></div>
          <button className="v8Ghost" onClick={snapshot} disabled={busy}>
            {busy ? "Đang chốt…" : "Chốt số kỳ này"}
          </button>
        </div>
        <div style={{display: "grid", gap: 18}}>
          {(history?.series || []).map((s: Row) => {
            const unit = s.points?.[0]?.unit || "";
            return <div key={s.metric_key}>
              <b style={{fontSize: 12.5}}>{s.metric_key}</b>
              <HistoryLine points={s.points || []} unit={unit}/>
            </div>;
          })}
          {!history?.series?.length && <div className="v8Empty">
            Chưa có mẫu nào trong metric_samples.
          </div>}
        </div>
        {!!history && <small style={{display: "block", marginTop: 8}}>
          {history.sample_count} mẫu · nguồn: {(history.sources || []).join(", ") || "—"}.
          {history.points_are_measurements
            ? " Mỗi điểm là một lần chốt số."
            : " Hai điểm đầu là backfill từ trị hiện tại và trị kỳ trước của analytics_metrics"
              + " — chuỗi dài ra mỗi lần chốt số, nên đừng đọc nó như một chuỗi đo liên tục."}
        </small>}
      </div>
    </section>
  </div>;
}
