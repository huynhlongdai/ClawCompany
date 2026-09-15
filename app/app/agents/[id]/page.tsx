import {AuthGate} from "../../../../components/AuthGate";
import {V17AppShell} from "../../../../components/V17AppShell";
import {AgentDetail} from "../../../../components/AgentDetail";
import {SeatProfileByMember} from "../../../../components/SeatProfile";

/* Chi tiết một nhân sự AI.

   WP-2.1/2.2 thêm khối "hồ sơ" lên trên: sáu tab đọc/ghi được danh tính, tính
   cách, mô tả công việc, năng lực, quyền và hạn mức — ghi thẳng vào gateway
   OpenClaw qua agents.files.set và config.patch.

   Khối cũ (AgentDetail: nhiệm vụ đang giữ, trạng thái runtime, kỹ năng) giữ
   nguyên bên dưới. Hai khối trả lời hai câu khác nhau: "nhân viên này được
   cấu hình thế nào" và "nhân viên này đang làm gì". */
export default function Page({params}: {params: {id: string}}) {
  const memberId = Number(params.id);
  return <AuthGate>
    <V17AppShell title="Hồ sơ nhân sự AI"
                 subtitle="Danh tính, tính cách, mô tả công việc, năng lực, quyền và hạn mức — ghi trực tiếp vào gateway OpenClaw">
      {Number.isFinite(memberId)
        ? <>
            <SeatProfileByMember memberId={memberId}/>
            <AgentDetail memberId={memberId}/>
          </>
        : <div className="v8Error">Id agent không hợp lệ.</div>}
    </V17AppShell>
  </AuthGate>;
}
