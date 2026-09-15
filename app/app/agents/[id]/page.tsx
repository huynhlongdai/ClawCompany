import {AuthGate} from "../../../../components/AuthGate";
import {V17AppShell} from "../../../../components/V17AppShell";
import {AgentDetail} from "../../../../components/AgentDetail";

export default function Page({params}: {params: {id: string}}) {
  const memberId = Number(params.id);
  return <AuthGate>
    <V17AppShell title="Chi tiết agent"
                 subtitle="Hồ sơ, nhiệm vụ đang giữ, trạng thái runtime và kỹ năng khả dụng">
      {Number.isFinite(memberId)
        ? <AgentDetail memberId={memberId}/>
        : <div className="v8Error">Id agent không hợp lệ.</div>}
    </V17AppShell>
  </AuthGate>;
}
