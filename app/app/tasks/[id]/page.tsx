"use client";
import {PageFrame} from "../../../../components/shell/PageFrame";
import {TaskDetail} from "../../../../components/TaskDetail";
import {Notice} from "../../../../components/ui/EmptyState";
import {t} from "../../../../lib/i18n";

/* Chi tiết một công việc.

   Ba khối, trả lời ba câu mà bảng việc không trả lời được: việc này đã đi tới
   đâu (sổ ghi), giao cho ai tiếp (bàn giao kèm hướng dẫn), và agent sẽ nhận
   được gì (gói ngữ cảnh bảy khối). */
export default function Page({params}: {params: {id: string}}) {
  const taskId = Number(params.id);
  return (
    <PageFrame title={t("task.page_title")} subtitle={t("task.page_sub")}>
      {Number.isFinite(taskId)
        ? <TaskDetail taskId={taskId}/>
        : <Notice tone="error">{t("task.bad_id")}</Notice>}
    </PageFrame>
  );
}
