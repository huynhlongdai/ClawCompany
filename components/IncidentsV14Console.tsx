"use client";
import {apiV14} from "../lib/api";
import {Any, Intro, LabBody, Panel, Pill, Stats, Table, useLoad} from "./lab/kit";

/* Phòng thí nghiệm · Sự cố (v14): mỗi lần SLO vi phạm thành một sự cố có chủ và dòng thời gian. */
export function IncidentsV14Console() {
  const q = useLoad(async () => (await apiV14.incidents()) as Any[], []);
  const items = q.data, open = items.filter(x => x.status !== "resolved");
  return <LabBody q={q}>
    <Intro>Mỗi lần SLO vi phạm, triển khai lỗi hay báo tay đều thành một sự cố có người phụ trách và dòng thời gian. Nina thấy cùng trạng thái như người và agent; nhận, giảm nhẹ và xử lý xong là các bước chuyển tường minh, có kiểm toán.</Intro>
    <Stats items={[["Sự cố đang mở", open.length], ["Nghiêm trọng", open.filter(x => x.severity === "critical").length], ["Cao", open.filter(x => x.severity === "high").length], ["Tổng", items.length]]}/>
    <Panel title="Hàng đợi sự cố" desc="Từ SLO, triển khai và báo tay">
      <Table rows={items} empty="Không có sự cố nào — hệ thống ổn." cols={[
        {label: "Sự cố", render: x => <><b>{x.title}</b><br/><small>{x.summary || x.source}</small></>},
        {label: "Môi trường / bản", render: x => <small>môi trường #{x.environment_id || "—"} · bản #{x.release_id || "—"}</small>, hideSm: true},
        {label: "Mức độ", render: x => <Pill s={x.severity}/>},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
