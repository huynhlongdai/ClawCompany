"use client";
import {useState} from "react";
import {apiV16} from "../lib/api";
import {viTime} from "../lib/labels";
import {ErrorBanner} from "./ui/EmptyState";
import {Any, Intro, LabBody, Panel, Pill, Rows, Stats, Table, useLoad} from "./lab/kit";

/* Phòng họp (v16): đội agent, phòng phối hợp có thứ tự lượt, hợp đồng giao việc giữa agent. */
export function CollaborationFabricConsole() {
  const q = useLoad(async () => {
    const [a, b, c, d] = await Promise.all([apiV16.summary(), apiV16.teams(), apiV16.rooms(), apiV16.delegations()]);
    return {summary: a as Any, teams: b as Any[], rooms: c as Any[], delegations: d as Any[]};
  }, {summary: {}, teams: [], rooms: [], delegations: []});
  const {data} = q; const s = data.summary;
  const [room, setRoom] = useState<Any | null>(null);
  const [roomErr, setRoomErr] = useState<unknown>(null);
  const openRoom = (id: number) => { setRoomErr(null); apiV16.room(id).then(x => setRoom(x as Any)).catch(setRoomErr); };
  return <LabBody q={q}>
    <Intro flow={["Đội", "Phòng", "Lượt", "Giao việc", "Tri thức"]}>
      Nhiều agent làm chung trong một phiên có thứ tự và có kiểm toán: mỗi lượt nói, quyết định và lần giao việc đều ghi kèm danh tính, phạm vi và ngân sách.
      Agent không nói ngoài lượt và không tự quyết nếu không có quyền trong phòng.
    </Intro>
    <Stats items={[["Đội đang hoạt động", s.teams_active || 0], ["Phòng đang mở", s.rooms_open || 0], ["Lượt trao đổi", s.turns_total || 0], ["Giao việc đang chạy", s.delegations_open || 0]]}/>
    <div className="ui-grid is-2">
      <Panel title="Đội agent" desc="Nhóm liên công ty có trưởng nhóm, người làm và người review">
        <Table rows={data.teams.slice(0, 12)} empty="Chưa có đội agent nào." cols={[
          {label: "Đội", render: x => <><b>{x.name}</b><br/><code>{x.team_key}</code></>},
          {label: "Cách phối hợp", render: x => x.collaboration_mode, hideSm: true},
          {label: "Phạm vi", render: x => x.cross_company ? "Liên công ty" : "Nội bộ"},
          {label: "Trạng thái", render: x => <Pill s={x.status}/>},
        ]}/>
      </Panel>
      <Panel title="Phòng phối hợp" desc="Chọn một phòng để xem biên bản có đánh số lượt">
        <Rows rows={data.rooms.slice(0, 12)} empty="Chưa có phòng nào." onPick={x => openRoom(x.id)} picked={x => room?.room?.id === x.id}
          title={x => x.topic || x.room_key} meta={x => `${x.mode} · ${x.turn_cursor} lượt`} end={x => <Pill s={x.status}/>}/>
      </Panel>
    </div>
    {roomErr ? <ErrorBanner error={roomErr} context="Mở phòng" onRetry={() => room?.room?.id && openRoom(room.room.id)}/> : null}
    {room && <Panel title={`Biên bản · ${room.room?.topic || room.room?.room_key}`}
      desc={`${(room.participants || []).length} thành viên · lượt kế tiếp: ${room.expected_speaker_member_id != null ? "#" + room.expected_speaker_member_id : "tự do"}`}>
      <Table rows={room.turns || []} empty="Phòng chưa có lượt nào." cols={[
        {label: "#", render: (t: Any) => t.sequence, num: true},
        {label: "Thành viên", render: (t: Any) => <>#{t.member_id}</>},
        {label: "Loại", render: (t: Any) => <code>{t.turn_type}</code>, hideSm: true},
        {label: "Nội dung", render: (t: Any) => String(t.content || "").slice(0, 160)},
        {label: "Lúc", render: (t: Any) => viTime(t.created_at), nowrap: true, hideSm: true},
      ]}/>
    </Panel>}
    <Panel title="Hợp đồng giao việc" desc="Agent giao việc cho agent, kèm tiêu chí nghiệm thu và trần chi phí">
      <Table rows={data.delegations.slice(0, 15)} empty="Chưa có hợp đồng giao việc nào." cols={[
        {label: "Việc", render: x => <b>{x.title}</b>},
        {label: "Giao → nhận", render: x => <>#{x.from_member_id} → #{x.to_member_id}</>, nowrap: true},
        {label: "Trần chi phí", render: x => `$${Number(x.max_cost_usd || 0).toFixed(2)}`, num: true},
        {label: "Trạng thái", render: x => <Pill s={x.status}/>},
      ]}/>
    </Panel>
  </LabBody>;
}
