"use client"

import { useState } from "react"
import { apiV32 } from "@/lib/api"

type Tier = { tier: string; days: number; note?: string }
type RetentionPlan = {
  total_events: number
  deletable: number
  kept_protected: number
  by_tier: Record<string, number>
  oldest_deletable: string
  has_more: boolean
  dry_run?: boolean
  deleted?: number
  policy: { tiers: Tier[] }
}
type RevisionKind = {
  kind: string
  exact_guard: number
  timestamp_guard: number
  ready_to_adopt: number
  too_recent: number
}
type RevisionPlan = {
  timestamp_guard_total: number
  ready_total: number
  quiet_seconds: number
  kinds: RevisionKind[]
  updated_total?: number
  dry_run?: boolean
}

// v32: hai viec don dep ma khong ai lam neu khong co man hinh.
// Ca hai deu xem truoc roi moi ghi, va mac dinh la dry-run:
// xoa so kiem toan hay gan lai revision deu khong the hoan tac.
export function HousekeepingPanel() {
  const [retention, setRetention] = useState<RetentionPlan | null>(null)
  const [revisions, setRevisions] = useState<RevisionPlan | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label)
    setError("")
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Khong goi duoc API v32")
    } finally {
      setBusy("")
    }
  }

  const previewRetention = () =>
    run("retention", async () => {
      setRetention((await apiV32.retentionPreview()) as RetentionPlan)
    })

  const prune = () =>
    run("prune", async () => {
      // Day la lenh duy nhat trong he thong xoa du lieu that.
      if (!window.confirm("Xoa vinh vien cac su kien da qua han?")) return
      setRetention((await apiV32.prune({ dry_run: false })) as RetentionPlan)
    })

  const previewRevisions = () =>
    run("revisions", async () => {
      setRevisions((await apiV32.revisionsPreview()) as RevisionPlan)
    })

  const backfill = () =>
    run("backfill", async () => {
      if (!window.confirm("Gan revision = 1 cho cac hang du cu?")) return
      setRevisions((await apiV32.revisionsBackfill({ dry_run: false })) as RevisionPlan)
    })

  return (
    <div className="panel">
      <div className="panelHead">
        <b>Don dep du lieu (v32)</b>
        <span className="tag blueTag">xem truoc roi moi ghi</span>
      </div>
      <div className="pad">
        {error && <p className="tag redTag">{error}</p>}

        <h4 style={{ margin: "4px 0 8px" }}>Luu tru su kien</h4>
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button className="darkBtn" onClick={previewRetention} disabled={busy !== ""}>
            {busy === "retention" ? "Dang tinh..." : "Xem truoc"}
          </button>
          <button className="ghost" onClick={prune} disabled={busy !== "" || !retention?.deletable}>
            {busy === "prune" ? "Dang xoa..." : "Xoa that"}
          </button>
        </div>
        {retention && (
          <>
            <table className="dataTable">
              <tbody>
                <tr>
                  <td>Tong su kien</td>
                  <td>{retention.total_events}</td>
                </tr>
                <tr>
                  <td>Se xoa</td>
                  <td>
                    {retention.deletable}
                    {retention.has_more ? " (con nua, chay lai)" : ""}
                  </td>
                </tr>
                <tr>
                  <td>Giu vi con dung de hoan tac</td>
                  <td>{retention.kept_protected}</td>
                </tr>
                <tr>
                  <td>Cu nhat</td>
                  <td>{retention.oldest_deletable || "-"}</td>
                </tr>
                {typeof retention.deleted === "number" && retention.dry_run === false && (
                  <tr>
                    <td>Da xoa</td>
                    <td>{retention.deleted}</td>
                  </tr>
                )}
              </tbody>
            </table>
            <p style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
              Theo tang: {Object.entries(retention.by_tier).map(([k, v]) => k + "=" + v).join(", ")}
              {" - chinh sach: "}
              {retention.policy.tiers.map((t) => t.tier + ":" + t.days + "d").join(", ")}
            </p>
          </>
        )}

        <h4 style={{ margin: "16px 0 8px" }}>Revision counter con NULL</h4>
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button className="darkBtn" onClick={previewRevisions} disabled={busy !== ""}>
            {busy === "revisions" ? "Dang tinh..." : "Xem truoc"}
          </button>
          <button className="ghost" onClick={backfill} disabled={busy !== "" || !revisions?.ready_total}>
            {busy === "backfill" ? "Dang gan..." : "Gan counter"}
          </button>
        </div>
        {revisions && (
          <>
            <table className="dataTable">
              <thead>
                <tr>
                  <th>Loai</th>
                  <th>Guard chinh xac</th>
                  <th>Guard theo thoi gian</th>
                  <th>Du dieu kien</th>
                  <th>Qua moi</th>
                </tr>
              </thead>
              <tbody>
                {revisions.kinds.map((k) => (
                  <tr key={k.kind}>
                    <td>{k.kind}</td>
                    <td>{k.exact_guard}</td>
                    <td>{k.timestamp_guard}</td>
                    <td>{k.ready_to_adopt}</td>
                    <td>{k.too_recent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
              Bo qua hang vua ghi trong {revisions.quiet_seconds}s: co the con client dang giu token thoi gian.
              {typeof revisions.updated_total === "number" && revisions.dry_run === false
                ? " Da gan: " + revisions.updated_total + "."
                : ""}
            </p>
          </>
        )}
      </div>
    </div>
  )
}
