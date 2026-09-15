"use client"

import {useEffect, useState} from "react"
import {apiV34} from "@/lib/api"

type Row = Record<string, any>

export function ReplayPanel() {
  const [coverage, setCoverage] = useState<Row | null>(null)
  const [backlog, setBacklog] = useState<Row | null>(null)
  const [schedules, setSchedules] = useState<Row | null>(null)
  const [grants, setGrants] = useState<Row | null>(null)
  const [busy, setBusy] = useState("")
  const [note, setNote] = useState("")

  async function load() {
    try {
      const [c, b, s, g] = await Promise.all([
        apiV34.coverage(),
        apiV34.eventBacklog(20),
        apiV34.progressSchedules(),
        apiV34.grants(),
      ])
      setCoverage(c); setBacklog(b); setSchedules(s); setGrants(g)
    } catch (e: any) {
      setNote("Không tải được dữ liệu v34: " + (e?.message || e))
    }
  }

  useEffect(() => { load() }, [])

  async function replay(dryRun: boolean) {
    if (!dryRun && !confirm("Phát lại thật sẽ chạy lại các trigger (tạo nhiệm vụ, tin nhắn, workflow). Tiếp tục?")) return
    setBusy("replay")
    try {
      const r = await apiV34.eventReplay({dry_run: dryRun, limit: 50})
      setNote(dryRun
        ? `Thử khan: ${r.candidates} sự kiện đủ điều kiện phát lại.`
        : `Đã phát lại ${r.replayed} sự kiện, ${(r.failed || []).length} lỗi, ${r.trigger_executions} trigger đã chạy.`)
      await load()
    } catch (e: any) {
      setNote("Lỗi phát lại: " + (e?.message || e))
    } finally { setBusy("") }
  }

  async function registerSchedule() {
    if (!confirm("Đăng ký lịch đồng bộ tiến độ (mặc định 15 phút mỗi giờ, ghi thật)?")) return
    setBusy("schedule")
    try {
      const r = await apiV34.progressScheduleCreate({})
      setNote(`Đã đăng ký lịch #${r.operation_id} (${r.schedule}). Lần chạy kế: ${r.next_run_at || "chưa tính"}.`)
      await load()
    } catch (e: any) {
      setNote("Không đăng ký được lịch: " + (e?.message || e))
    } finally { setBusy("") }
  }

  async function revokeGrant(key: string) {
    if (!confirm(`Đóng sổ quyền "${key}"? Hãy xoá quyền trên gateway trước — hệ thống này không thu hồi được phía gateway.`)) return
    setBusy("grant")
    try {
      await apiV34.grantRevoke({grant_key: key, confirmed_cleared_upstream: true, note: "Đóng sổ từ bảng điều khiển"})
      setNote(`Đã đóng sổ quyền ${key}. Quyền phía gateway vẫn phải xoá bằng tay.`)
      await load()
    } catch (e: any) {
      setNote("Không đóng sổ được: " + (e?.message || e))
    } finally { setBusy("") }
  }

  return (
    <div className="panel">
      <div className="panelHead">
        <b>v34 · Phát lại & Lịch</b>
        <span className="tag blueTag">1.24.0</span>
      </div>
      <div className="pad">
        {note ? <p>{note}</p> : null}

        <h4>Sự kiện tồn đọng</h4>
        <p className="muted">
          {coverage?.event_replay?.why_not || "Chỉ phát lại được sự kiện đã ghi xuống đĩa."}
        </p>
        <p>
          Đang kẹt: <b>{backlog?.stuck_total ?? "—"}</b> sự kiện
          {backlog?.oldest_age_seconds ? ` · cũ nhất ${Math.round(backlog.oldest_age_seconds / 60)} phút` : ""}
        </p>
        <table className="dataTable">
          <thead><tr><th>ID</th><th>Loại</th><th>Trạng thái</th><th>Tuổi (giây)</th></tr></thead>
          <tbody>
            {(backlog?.rows || []).slice(0, 8).map((r: Row) => (
              <tr key={r.event_id}>
                <td>{r.event_id}</td>
                <td>{r.event_type}</td>
                <td><span className={r.status === "error" ? "tag redTag" : "tag orangeTag"}>{r.status}</span></td>
                <td>{r.age_seconds}</td>
              </tr>
            ))}
            {!(backlog?.rows || []).length ? <tr><td colSpan={4}>Không có sự kiện kẹt.</td></tr> : null}
          </tbody>
        </table>
        <p>
          <button className="ghost" disabled={busy === "replay"} onClick={() => replay(true)}>Thử khan</button>{" "}
          <button className="darkBtn" disabled={busy === "replay"} onClick={() => replay(false)}>Phát lại thật</button>
        </p>

        <h4>Lịch đồng bộ tiến độ</h4>
        <p className="muted">{coverage?.progress_schedule?.scheduler_note || ""}</p>
        <table className="dataTable">
          <thead><tr><th>#</th><th>Cron</th><th>Bật</th><th>Lần chạy cuối</th></tr></thead>
          <tbody>
            {(schedules?.rows || []).map((r: Row) => (
              <tr key={r.operation_id}>
                <td>{r.operation_id}</td>
                <td>{r.schedule}</td>
                <td>{r.enabled ? <span className="tag greenTag">bật</span> : <span className="tag">tắt</span>}</td>
                <td>{r.last_run_at || "chưa từng chạy"}</td>
              </tr>
            ))}
            {!(schedules?.rows || []).length ? <tr><td colSpan={4}>Chưa có lịch nào.</td></tr> : null}
          </tbody>
        </table>
        <p>
          <button className="darkBtn" disabled={busy === "schedule"} onClick={registerSchedule}>Đăng ký lịch</button>
        </p>

        <h4>Quyền thường trú (standing grant)</h4>
        <p className="muted">{coverage?.grant_expiry?.why_not || ""}</p>
        <table className="dataTable">
          <thead><tr><th>Khoá</th><th>Phiên</th><th>Trạng thái</th><th>Còn (ngày)</th><th></th></tr></thead>
          <tbody>
            {(grants?.rows || []).slice(0, 8).map((r: Row) => (
              <tr key={r.grant_key}>
                <td>{r.tool}</td>
                <td>{r.session_key}</td>
                <td>
                  <span className={r.status === "expired" ? "tag redTag" : r.status === "active" ? "tag greenTag" : "tag orangeTag"}>
                    {r.status}
                  </span>
                </td>
                <td>{r.days_remaining ?? "—"}</td>
                <td>
                  <button className="ghost" disabled={busy === "grant"} onClick={() => revokeGrant(r.grant_key)}>Đóng sổ</button>
                </td>
              </tr>
            ))}
            {!(grants?.rows || []).length ? <tr><td colSpan={5}>Chưa có quyền thường trú nào được ghi sổ.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
