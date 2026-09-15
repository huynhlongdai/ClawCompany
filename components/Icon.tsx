/* Bộ icon SVG tối giản.
   Vì sao không dùng ký tự Unicode như ⌂ ▤ ◫ ✦ ⛬ ◈: chúng phụ thuộc font hệ
   thống và trên Linux/headless chúng render thành ô vuông tofu — đã thấy
   đúng như vậy khi chụp UI. SVG thì luôn hiện, canh nét được, và ăn theo
   currentColor nên tự đổi màu theo trạng thái nav. */

type Name =
  | "home" | "building" | "users" | "sparkle" | "board" | "check" | "book"
  | "pencil" | "room" | "mesh" | "crown" | "gear" | "pulse" | "search"
  | "plus" | "arrow-right" | "bell" | "shield" | "chart" | "doc";

const PATHS: Record<Name, string> = {
  home: "M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3.5v-4.5h-5V17H4a1 1 0 0 1-1-1V9.5Z",
  building: "M4 17V4.8c0-.4.3-.8.8-.8h6.4c.5 0 .8.4.8.8V17M12 9h3.2c.5 0 .8.4.8.8V17M6.5 7h3M6.5 10h3M6.5 13h3",
  users: "M7 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Zm7 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM2.5 16.5c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4M13 12.6c2.2.1 4 1.5 4 3.9",
  sparkle: "M10 3.2l1.5 3.9L15.4 8.6l-3.9 1.5L10 14l-1.5-3.9L4.6 8.6l3.9-1.5L10 3.2Z",
  board: "M3.5 4.5h13v11h-13v-11Zm4.3 0v11m4.4-11v11",
  check: "M4 10.5l3.5 3.5L16 5.5",
  book: "M4 4.5h5.2c.6 0 1 .4 1 1V17c0-.6-.4-1-1-1H4V4.5Zm12 0h-5.2c-.6 0-1 .4-1 1V17c0-.6.4-1 1-1H16V4.5Z",
  pencil: "M4 16h3l9-9a2.1 2.1 0 0 0-3-3l-9 9v3Z",
  room: "M4 6.5h12v8H4v-8Zm3-2.5v2.5m6-2.5v2.5M7 17v-2.5m6 2.5v-2.5",
  mesh: "M10 3.5l5.5 3.2v6.6L10 16.5 4.5 13.3V6.7L10 3.5Zm0 0v13m5.5-9.8L4.5 13.3m11 0L4.5 6.7",
  crown: "M3.5 14.5h13l-1-7-3.5 2.6L10 5.5 8 10.1 4.5 7.5l-1 7Z",
  gear: "M10 12.6a2.6 2.6 0 1 0 0-5.2 2.6 2.6 0 0 0 0 5.2Zm7-2.6-1.7-.5-.4-1 .8-1.5-1.6-1.6-1.5.8-1-.4L11.1 4H8.9l-.5 1.7-1 .4-1.5-.8L4.3 6.9l.8 1.5-.4 1L3 10v2.1l1.7.5.4 1-.8 1.5 1.6 1.6 1.5-.8 1 .4.5 1.7h2.2l.5-1.7 1-.4 1.5.8 1.6-1.6-.8-1.5.4-1 1.7-.5V10Z",
  pulse: "M2.5 10.5h3l2-5 3 9 2.3-4h4.7",
  search: "M9 14.5a5.5 5.5 0 1 0 0-11 5.5 5.5 0 0 0 0 11Zm4-1.5 4 4",
  plus: "M10 4.5v11M4.5 10h11",
  "arrow-right": "M4 10h11m-4-4 4 4-4 4",
  bell: "M6 8.5a4 4 0 0 1 8 0c0 3 .8 4.2 1.5 5H4.5C5.2 12.7 6 11.5 6 8.5ZM8.5 16a1.6 1.6 0 0 0 3 0",
  shield: "M10 3.5 16 6v4.2c0 3.3-2.4 5.6-6 6.8-3.6-1.2-6-3.5-6-6.8V6l6-2.5Z",
  chart: "M4 16V9m4 7V5m4 11v-4.5M16 16V7",
  doc: "M5.5 3.5h6L15 7v9.5h-9.5v-13ZM11 3.5V7h4",
};

export function Icon({name, size = 18, strokeWidth = 1.6, fill = false}: {
  name: Name; size?: number; strokeWidth?: number; fill?: boolean;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true"
         style={{flex: "none", display: "block"}}>
      <path d={PATHS[name]}
            fill={fill ? "currentColor" : "none"}
            stroke="currentColor"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"/>
    </svg>
  );
}

export type IconName = Name;
