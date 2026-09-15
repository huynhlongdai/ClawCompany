"use client"

import { useState } from "react"
import { apiV31 } from "@/lib/api"

type Entry = { event_id: number; from: unknown; to: unknown; at: string; actor_member_id: number | null }
type History = {
  timeline: Record<string, Entry[]>
  field_names: string[]
  writes_without_values: number
  note: string
}

const show = (v: unknown) => {
  if (v === null || v === undefined) return "(trong)"
  if (v === "") return "(rong)"
  return String(v)
}

// v31: doc lai gia tri truoc va sau cua tung truong.
// v30 chi ghi ten truong da doi, nen khong tra loi duoc "truoc do la gi".
export function FieldHistoryPanel() {
  const [entityType, setEntityType] = useState("project")
  const [entityId, setEntityId] = useState("")
  const [data, setData] = useState<History | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const load = async () => {
    if (!entityId.trim()) {
      setError("Nhap ID cua hang can xem")
      return
    }
    setLoading(true)
    setError("")
    try {
      const res = (await apiV31.history(entityType, entityId.trim(), { limit: 50 })) as History
      setData(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Khong tai duoc lich su")
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="panel">
      <div className="panelHead">
        <strong>Lich su gia tri tung truong (v31)</strong>
        <span className="tag blueTag">field audit</span>
      </div>
      <div className="pad">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
            <option value="company">company</option>
            <option value="department">department</option>
            <option value="member">member</option>
            <option value="project">project</option>
            <option value="task">task</option>
          </select>
          <input
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            placeholder="ID hang, vi du 12"
          />
          <button className="darkBtn" onClick={load} disabled={loading}>
            {loading ? "Dang tai..." : "Xem lich su"}
          </button>
        </div>

        {error ? <p className="tag redTag">{error}</p> : null}

        {data ? (
          <>
            {data.note ? <p className="tag orangeTag">{data.note}</p> : null}
            {data.field_names.length === 0 ? (
              <p>Chua co thay doi nao duoc ghi lai cho hang nay.</p>
            ) : (
              data.field_names.map((field) => (
                <div key={field} style={{ marginBottom: 14 }}>
                  <strong>{field}</strong>
                  <table className="dataTable">
                    <thead>
                      <tr>
                        <th>Truoc</th>
                        <th>Sau</th>
                        <th>Thoi diem</th>
                        <th>Nguoi thuc hien</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(data.timeline[field] || []).map((entry) => (
                        <tr key={`${field}-${entry.event_id}`}>
                          <td>{show(entry.from)}</td>
                          <td>{show(entry.to)}</td>
                          <td>{entry.at || "-"}</td>
                          <td>{entry.actor_member_id ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))
            )}
            {data.writes_without_values > 0 ? (
              <p className="tag orangeTag">
                {data.writes_without_values} lan ghi truoc v31 khong luu gia tri cu.
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  )
}
