"use client";
import {apiV14} from "../lib/api";
import {Button} from "./ui/Button";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, parseJson, useAction, useLoad} from "./lab/kit";
import {ErrorBanner} from "./ui/EmptyState";

/* Phòng thí nghiệm · Danh mục kỹ thuật (v14): Nina gộp sáng kiến, CI lỗi, SLO vi phạm, sự cố thành một tín hiệu sức khoẻ. */
export function NinaPortfolioConsole() {
  const q = useLoad(async () => {
    const [o, r] = await Promise.all([apiV14.portfolioObjectives(), apiV14.portfolioReviews()]);
    return {objectives: o as Any[], reviews: r as Any[]};
  }, {objectives: [], reviews: []});
  const {data, reload} = q;
  const act = useAction();
  const latest = data.reviews[0];
  const m = parseJson<Any>(latest?.metrics_json, {});
  const recs = parseJson<string[]>(latest?.recommendations_json, []);
  const run = () => act.run("review", async () => { await apiV14.reviewPortfolio({objective_id: data.objectives[0]?.id || null}); await reload(); }, "Nina đã đánh giá xong danh mục");
  return <LabBody q={q}>
    <Intro>Nina đọc sức khoẻ giao phần mềm chứ không chỉ từng việc: gộp sáng kiến, CI lỗi, SLO vi phạm, sự cố và lượt triển khai hỏng thành một tín hiệu, kèm đề xuất xác định.</Intro>
    {act.error ? <ErrorBanner error={act.error} context="Đánh giá danh mục" onClose={() => act.setError(null)}/> : null}
    <Panel title="Sức khoẻ gần nhất" actions={<Button variant="primary" icon="sparkle" busy={act.busy === "review"} onClick={run}>Chạy đánh giá danh mục</Button>}>
      <p style={{margin: 0}}>{latest ? <><Pill s={latest.health}/> {latest.summary}</> : "Chưa có lần đánh giá nào — bấm Chạy đánh giá danh mục."}</p>
    </Panel>
    <Stats items={[["Sáng kiến đang chạy", m.active_initiatives], ["CI lỗi", m.failed_ci], ["Sự cố đang mở", m.open_incidents], ["SLO vi phạm", m.slo_breaches]]}/>
    <div className="ui-grid is-2">
      <Panel title="Mục tiêu danh mục" desc="Kết quả kỹ thuật cấp điều hành">
        <Table rows={data.objectives} empty="Chưa có mục tiêu danh mục nào." cols={[
          {label: "Mục tiêu", render: x => <><b>{x.title}</b><br/><small>{x.objective}</small></>},
          {label: "Ưu tiên", render: x => <Pill s={x.priority}/>},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Đề xuất của Nina" desc="Suy ra từ trạng thái hiện tại">
        {recs.length ? <ol className="lab-list">{recs.map((x, i) => <li key={i}>{x}</li>)}</ol>
          : <p className="ui-empty-line">Chạy đánh giá danh mục để có đề xuất.</p>}
      </Panel>
    </div>
  </LabBody>;
}
