"use client"

import { useState } from "react"
import { apiV33 } from "@/lib/api"

type Orphan = {
  task_id: number
  title: string
  status: string
  session_key: string
  lease_held: boolean
}

type RuntimePlan = {
  member_id: number
  member_status: string
  member_is_archived: boolean
  orphan_count: number
  orphans: Orphan[]
  parkable_task_ids: number[]
  contested_task_ids: number[]
  blocked_reason: string | null
  dry_run?: boolean
  parked?: number
}

type DriftRow = {
  project_id: number
  name: string
  status: string
  stored_progress: number
  derived_progress: number | null
  drift: number | null
}

type DriftPlan = {
  projects_checked: number
  eligible_count: number
  unknown_count: number
  worst_drift: number
  eligible: DriftRow[]
  dry_run?: boolean
  synced?: number
}

type LeaseIndex = {
  backend: string
  index_size: number | null
  index_pruned: number
  preview?: { live: number; stale: number; removed: number }
}

export function RecoveryPanel() {
  const [memberId, setMemberId] = useState("")
  const [runtime, setRuntime] = useState<RuntimePlan | null>(null)
  const [drift, setDrift] = useState<DriftPlan | null>(null)
  const [lease, setLease] = useState<LeaseIndex | null>(null)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label)
    setError("")
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy("")
    }
  }

  const previewRuntime = () =>
    run("runtime", async () => {
      const id = Number(memberId)
      if (!id) {
        setError("Nhap ma nhan su truoc")
        return
      }
      setRuntime(await apiV33.memberRuntime(id))
    })

  const parkRuntime = () =>
    run("park", async () => {
      const id = Number(memberId)
      if (!id) return
      if (!window.confirm("Go session key da chet cua cac nhiem vu nay?")) return
      setRuntime(await apiV33.memberRuntimePark(id, { dry_run: false }))
    })

  const previewDrift = () =>
    run("drift", async () => {
      setDrift(await apiV33.progressDrift())
    })

  const syncDrift = () =>
    run("sync", async () => {
      if (!window.confirm("Ghi tien do suy ra len cac du an bi lech?")) return
      setDrift(await apiV33.progressSync({ dry_run: false }))
    })

  const loadLease = () =>
    run("lease", async () => {
      setLease(await apiV33.leaseIndex())
    })

  const pruneLease = () =>
    run("prune", async () => {
      if (!window.confirm("Xoa cac muc index khong con lease?")) return
      await apiV33.leaseIndexPrune({ dry_run: false })
      setLease(await apiV33.leaseIndex())
    })

  return (
    <div className="panel">
      <div className="panelHead">
        <b>Khoi phuc &amp; truy xuat (v33)</b>
        <span className="tag blueTag">dry run mac dinh</span>
      </div>
      <div className="pad">
        {error ? <p className="tag redTag">{error}</p> : null}

        <h4>Runtime con sot sau khi bo luu tru nhan su</h4>
        <input
          value={memberId}
          onChange={(e) => setMemberId(e.target.value)}
          placeholder="Ma nhan su"
        />
        <button className="ghost" onClick={previewRuntime} disabled={busy !== ""}>
          {busy === "runtime" ? "Dang xem..." : "Xem truoc"}
        </button>
        <button className="darkBtn" onClick={parkRuntime} disabled={busy !== ""}>
          {busy === "park" ? "Dang xu ly..." : "Go session da chet"}
        </button>
        {runtime ? (
          <div>
            <p>
              Trang thai: <b>{runtime.member_status}</b> &middot; con sot{" "}
              <b>{runtime.orphan_count}</b> nhiem vu &middot; co the go{" "}
              {runtime.parkable_task_ids.length} &middot; dang bi giu{" "}
              {runtime.contested_task_ids.length}
              {typeof runtime.parked === "number" && runtime.dry_run === false
                ? ` · da go ${runtime.parked}`
                : ""}
            </p>
            {runtime.blocked_reason ? (
              <p className="tag orangeTag">{runtime.blocked_reason}</p>
            ) : null}
            <table className="dataTable">
              <thead>
                <tr>
                  <th>Nhiem vu</th>
                  <th>Trang thai</th>
                  <th>Session</th>
                  <th>Lease</th>
                </tr>
              </thead>
              <tbody>
                {runtime.orphans.map((row) => (
                  <tr key={row.task_id}>
                    <td>{row.title}</td>
                    <td>{row.status}</td>
                    <td>{row.session_key}</td>
                    <td>
                      <span className={row.lease_held ? "tag orangeTag" : "tag greenTag"}>
                        {row.lease_held ? "dang giu" : "tu do"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <h4>Tien do du an lech so voi bang nhiem vu</h4>
        <button className="ghost" onClick={previewDrift} disabled={busy !== ""}>
          {busy === "drift" ? "Dang xem..." : "Xem do lech"}
        </button>
        <button className="darkBtn" onClick={syncDrift} disabled={busy !== ""}>
          {busy === "sync" ? "Dang dong bo..." : "Dong bo tien do"}
        </button>
        {drift ? (
          <div>
            <p>
              Kiem tra <b>{drift.projects_checked}</b> du an &middot; can sua{" "}
              <b>{drift.eligible_count}</b> &middot; khong do duoc{" "}
              {drift.unknown_count} &middot; lech lon nhat {drift.worst_drift}
              {typeof drift.synced === "number" && drift.dry_run === false
                ? ` · da ghi ${drift.synced}`
                : ""}
            </p>
            <table className="dataTable">
              <thead>
                <tr>
                  <th>Du an</th>
                  <th>Dang luu</th>
                  <th>Suy ra</th>
                  <th>Lech</th>
                </tr>
              </thead>
              <tbody>
                {drift.eligible.slice(0, 12).map((row) => (
                  <tr key={row.project_id}>
                    <td>{row.name}</td>
                    <td>{row.stored_progress}</td>
                    <td>{row.derived_progress ?? "-"}</td>
                    <td>{row.drift ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <h4>Index lease runtime</h4>
        <button className="ghost" onClick={loadLease} disabled={busy !== ""}>
          {busy === "lease" ? "Dang tai..." : "Xem index"}
        </button>
        <button className="darkBtn" onClick={pruneLease} disabled={busy !== ""}>
          {busy === "prune" ? "Dang don..." : "Don index"}
        </button>
        {lease ? (
          <p>
            Backend <b>{lease.backend}</b> &middot; kich thuoc{" "}
            {lease.index_size ?? "khong ro"} &middot; da don{" "}
            {lease.index_pruned}
            {lease.preview
              ? ` · con song ${lease.preview.live} · qua han ${lease.preview.stale}`
              : ""}
          </p>
        ) : null}
      </div>
    </div>
  )
}
