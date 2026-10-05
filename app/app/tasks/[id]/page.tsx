import {AuthGate} from "../../../../components/AuthGate";
import {V17AppShell} from "../../../../components/V17AppShell";
import {TaskDetail} from "../../../../components/TaskDetail";

/* Chi tiết một công việc.

   Ba khối, trả lời ba câu mà bảng việc không trả lời được: việc này đã đi tới
   đâu (sổ ghi), giao cho ai tiếp (bàn giao kèm hướng dẫn), và agent sẽ nhận
   được gì (gói ngữ cảnh bảy khối). */
export default function Page({params}: {params: {id: string}}) {
  const taskId = Number(params.id);
  return <AuthGate>
    <V17AppShell title="Chi tiết công việc"
                 subtitle="Sổ ghi theo thời gian, bàn giao kèm hướng dẫn, và gói ngữ cảnh mà agent sẽ nhận">
      {Number.isFinite(taskId)
        ? <TaskDetail taskId={taskId}/>
        : <div className="v8Error">Id công việc không hợp lệ.</div>}
    </V17AppShell>
  </AuthGate>;
}
