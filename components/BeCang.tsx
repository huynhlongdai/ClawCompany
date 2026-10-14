"use client";
import type {ReactNode} from "react";

/* Bé Càng — ốc mượn hồn mang vỏ là toà nhà văn phòng (design/mascot, bản đã chốt).
   Cửa sổ sáng = agent đang làm. Năm trạng thái theo plan-v2 §6; M4b dùng cho trạng
   thái rỗng / lỗi / xong. SVG vẽ tay, không tải ảnh ngoài. Trước M4b chưa có
   component mascot nào trong repo — đây là bản đầu, các trang mới dùng chung. */

export type BeCangMood = "hello" | "working" | "done" | "error" | "sleep";

export function BeCang({mood = "hello", size = 96, title, lit: litCount}: {mood?: BeCangMood; size?: number; title?: string; lit?: number}) {
  /* `lit` (0–6): số cửa sổ sáng = số agent đang làm (Tổng quan). Không truyền thì theo tâm trạng. */
  const lit = litCount !== undefined ? litCount > 0 : mood === "working" || mood === "done";
  const win = (x: number, y: number, on: boolean) =>
    <rect key={`${x}-${y}`} x={x} y={y} width="9" height="9" rx="1.5" fill={on ? "#FFD36B" : "#EADFD5"} className={on ? "bc-lit" : undefined}/>;
  const windows = [[44, 22], [57, 22], [44, 36], [57, 36], [44, 50], [57, 50]]
    .map(([x, y], i) => win(x, y, litCount !== undefined ? i < litCount : lit && (mood === "done" || i % 2 === 0)));
  return <svg className={`bc-svg bc-${mood}`} width={size} height={size} viewBox="0 0 100 100" role="img"
    aria-label={title || "Bé Càng"}>
    {/* vỏ: toà nhà */}
    <rect x="38" y="12" width="34" height="56" rx="4" fill="#FFFFFF" stroke="#1A1C2B" strokeWidth="2.5"/>
    <rect x="49" y="6" width="12" height="7" rx="1.5" fill="#1A1C2B"/>
    {windows}
    <rect x="51" y="58" width="9" height="10" rx="1.5" fill="#1A1C2B"/>
    {/* thân cua */}
    <ellipse cx="38" cy="72" rx="20" ry="13" fill="#FF5A4E" stroke="#1A1C2B" strokeWidth="2.5"/>
    {/* càng */}
    <path d="M20 66 q-12 -6 -10 -18 q8 2 10 8 q2 -8 8 -8 q2 10 -8 18z" fill="#FF5A4E" stroke="#1A1C2B"
      strokeWidth="2.2" strokeLinejoin="round"/>
    {/* chân */}
    {[24, 32, 44, 52].map(x => <path key={x} d={`M${x} 82 l-3 9`} stroke="#1A1C2B" strokeWidth="2.2" strokeLinecap="round"/>)}
    {/* mắt */}
    {mood === "error" ? <>
      <path d="M28 60 l6 6 M34 60 l-6 6 M40 60 l6 6 M46 60 l-6 6" stroke="#1A1C2B" strokeWidth="2.2" strokeLinecap="round"/>
      <path d="M31 77 q6 -5 12 0" fill="none" stroke="#1A1C2B" strokeWidth="2.2" strokeLinecap="round"/>
      <path d="M58 30 q4 6 0 9 q-4 -3 0 -9z" fill="#2F5FD0"/>
    </> : mood === "sleep" ? <>
      <path d="M28 64 q3 3 6 0 M40 64 q3 3 6 0" fill="none" stroke="#1A1C2B" strokeWidth="2.2" strokeLinecap="round"/>
      <text x="74" y="16" fontSize="12" fontWeight="700" fill="#5B6075">z</text>
      <text x="82" y="8" fontSize="9" fontWeight="700" fill="#5B6075">z</text>
    </> : <>
      <circle cx="31" cy="63" r="3.2" fill="#1A1C2B"/><circle cx="43" cy="63" r="3.2" fill="#1A1C2B"/>
      <path d={mood === "done" || mood === "hello" ? "M31 74 q6 6 12 0" : "M32 75 h10"} fill="none"
        stroke="#1A1C2B" strokeWidth="2.2" strokeLinecap="round"/>
    </>}
    {mood === "done" && <path d="M76 70 l5 5 l10 -12" fill="none" stroke="#0B7A6D" strokeWidth="4"
      strokeLinecap="round" strokeLinejoin="round"/>}
  </svg>;
}

/* Khối trạng thái rỗng / lỗi có Bé Càng: một câu nói thẳng chuyện gì xảy ra + cách xử lý. */
export function BeCangState({mood, title, children, action}: {
  mood: BeCangMood; title: string; children?: ReactNode; action?: ReactNode;
}) {
  return <div className={"bc-state" + (mood === "error" ? " is-error" : "")} role={mood === "error" ? "alert" : "status"}>
    <BeCang mood={mood} size={88}/>
    <b>{title}</b>
    {children && <span>{children}</span>}
    {action}
  </div>;
}
