"use client";
import {useSearchParams} from "next/navigation";
import {LinkTabs} from "./ui/Tabs";
import {AgentDetail} from "./AgentDetail";
import {SeatProfileByMember} from "./SeatProfile";
import {AgentHRPanel} from "./AgentHR";
import {t as tr, lazy} from "../lib/i18n";

/* UI v2: hồ sơ agent chia 3 tab theo câu hỏi người dùng hỏi, thay vì xếp ba khối
   dài liền nhau (trang cũ cao ~6000px trên điện thoại).
   - Đang làm gì      → AgentDetail (việc đang giữ, runtime, kỹ năng)
   - Nhân sự          → AgentHRPanel (sửa hồ sơ 2 chiều, vòng đời, lệch, quyền tool)
   - Cấu hình OpenClaw → SeatProfile (6 tab file/config ghi thẳng gateway)
   Tab nằm trên URL (?tab=) nên chia sẻ/back được. Ba component giữ nguyên logic. */
const TABS = lazy(() => ([
  {key: "", label: tr("agent.dang_lam_gi")},
  {key: "hr", label: tr("agent.nhan_su")},
  {key: "openclaw", label: tr("agent.cau_hinh_openclaw")},
]));

export function AgentProfile({memberId}: {memberId: number}) {
  const tab = useSearchParams().get("tab") || "";
  const base = `/app/agents/${memberId}`;
  const href = (k: string) => k ? `${base}?tab=${k}` : base;
  const active = TABS.some(t => t.key === tab) ? tab : "";
  return <>
    <LinkTabs label={tr("agent.phan_ho_so")} active={href(active)} tabs={TABS.map(t => ({href: href(t.key), label: t.label}))}/>
    {active === "" && <AgentDetail memberId={memberId}/>}
    {active === "hr" && <AgentHRPanel memberId={memberId}/>}
    {active === "openclaw" && <SeatProfileByMember memberId={memberId}/>}
  </>;
}
