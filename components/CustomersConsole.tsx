"use client";
import {useEffect, useState} from "react";
import {api} from "../lib/api";
import {Icon} from "./Icon";

/* Khách hàng — màn hình có trong mẫu nhưng app chưa có route.
   Dữ liệu thật: GET /api/customers, /api/customers/{id}/agents,
   /api/usage/customers/{id}/summary (chi phí AI theo khách). */

type Row = Record<string, any>;

export function CustomersConsole() {
  const [rows, setRows] = useState<Row[]>([]);
  const [usage, setUsage] = useState<Record<number, Row>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const list = (await api.customers() as Row[]) || [];
        setRows(list);
        // Chi phí AI theo từng khách: gọi song song, lỗi một khách không làm
        // sập cả bảng.
        const pairs = await Promise.all(list.map(async c => {
          try { return [c.id, await api.usageSummary(c.id)] as const; }
          catch { return [c.id, null] as const; }
        }));
        setUsage(Object.fromEntries(pairs.filter(([, v]) => v)) as Record<number, Row>);
      } catch (e: any) { setError(e?.message || "Không tải được khách hàng"); }
    })();
  }, []);

  const active = rows.filter(r => r.status === "active").length;

  return <div>
    {error && <div className="v8Error" style={{marginBottom: 14}}>{error}</div>}

    <section className="v14Metrics" style={{gridTemplateColumns: "repeat(auto-fit,minmax(178px,1fr))"}}>
      <div className="metric">
        <div className="metricIcon"><Icon name="users" size={16}/></div>
        <label>Khách hàng</label><strong>{rows.length}</strong>
      </div>
      <div className="metric">
        <div className="metricIcon"><Icon name="check" size={16}/></div>
        <label>Đang hoạt động</label><strong>{active}</strong>
      </div>
      <div className="metric">
        <div className="metricIcon"><Icon name="chart" size={16}/></div>
        <label>Ghế đã bán</label>
        <strong>{rows.reduce((s, r) => s + (r.seats || 0), 0)}</strong>
      </div>
      <div className="metric">
        <div className="metricIcon"><Icon name="doc" size={16}/></div>
        <label>Giá tháng</label>
        <strong>${rows.reduce((s, r) => s + (r.monthly_price || 0), 0).toLocaleString("vi-VN")}</strong>
      </div>
    </section>

    <section className="panel">
      <div className="panelHead">
        <div><b>Danh sách khách hàng</b></div>
        <small>{rows.length} bản ghi · từ /api/customers</small>
      </div>
      <table className="dataTable">
        <thead><tr>
          <th>Khách hàng</th><th>Đội phụ trách</th><th>Mã</th><th>Ghế</th>
          <th>Giá tháng</th><th>Chi phí AI</th><th>Trạng thái</th>
        </tr></thead>
        <tbody>
          {rows.map(r => <tr key={r.id}>
            <td>
              <div className="person">
                <span className="avatarSm">{(r.name || "?").slice(0, 1)}</span>
                <div><b>{r.name}</b><small>{r.portal_enabled ? "có cổng riêng" : "chưa mở cổng"}</small></div>
              </div>
            </td>
            <td>{r.account_team || "—"}</td>
            <td><code>{r.external_ref || "—"}</code></td>
            <td>{r.seats ?? "—"}</td>
            <td>${(r.monthly_price || 0).toLocaleString("vi-VN")}</td>
            <td>{usage[r.id] ? `$${Number(usage[r.id].total_amount ?? usage[r.id].amount ?? 0).toFixed(2)}` : "—"}</td>
            <td><span className={`tag ${r.status === "active" ? "greenTag" : "orangeTag"}`}>{r.status}</span></td>
          </tr>)}
          {!rows.length && <tr><td colSpan={7}><div className="v8Empty">Chưa có khách hàng nào.</div></td></tr>}
        </tbody>
      </table>
    </section>
  </div>;
}
