// Lõi thuần (test được bằng node --test): phát hiện + che tên model/nhà cung cấp AI trong câu trả lời.
// Prompt runtime của OpenClaw luôn có "model=<provider/id>" nên dặn trong AGENTS.md là chưa đủ (đo trên VM:
// CSKH 13/14 ca vẫn lộ). Hai lớp: before_agent_finalize yêu cầu model viết lại 1 lần; message_sending che chữ.
export const FAMILIES = [
  "gpt-?\\d(?:[\\w-]|\\.(?=\\w))*", "chatgpt", "openai", "o[134](?:-mini|-pro)?", "claude(?:[\\w-]|\\.(?=\\w))*", "anthropic", "gemini(?:[\\w-]|\\.(?=\\w))*",
  "gemma(?:[\\w-]|\\.(?=\\w))*", "deepseek(?:[\\w-]|\\.(?=\\w))*", "qwen(?:[\\w-]|\\.(?=\\w))*", "llama(?:[\\w-]|\\.(?=\\w))*", "mistral(?:[\\w-]|\\.(?=\\w))*", "mixtral(?:[\\w-]|\\.(?=\\w))*",
  "grok(?:[\\w-]|\\.(?=\\w))*", "xai", "kimi(?:[\\w-]|\\.(?=\\w))*", "moonshot", "glm-?(?:[\\w-]|\\.(?=\\w))*", "zhipu", "minimax(?:[\\w-]|\\.(?=\\w))*", "cometapi",
  "openrouter", "sonnet(?:[\\w-]|\\.(?=\\w))*", "haiku(?:[\\w-]|\\.(?=\\w))*", "opus(?:[\\w-]|\\.(?=\\w))*", "openclaw",
];

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function termsFor(model, provider, extra = []) {
  const t = [...FAMILIES];
  for (const v of [model, provider, ...(extra || [])]) {
    if (!v || typeof v !== "string") continue;
    for (const part of v.split("/")) if (part.trim().length >= 3) t.push(esc(part.trim()));
  }
  return t;
}

export function pattern(terms) {
  return new RegExp(`(?<![\\p{L}\\p{N}])(?:${terms.join("|")})(?![\\p{L}\\p{N}])`, "giu");
}

export function textOf(msg) {
  if (!msg) return "";
  if (typeof msg === "string") return msg;
  if (typeof msg.text === "string") return msg.text;
  const c = msg.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) return c.map((p) => (typeof p === "string" ? p : p?.text || "")).join("\n");
  return "";
}

export function leaks(text, terms) {
  const m = (text || "").match(pattern(terms));
  return m ? [...new Set(m.map((x) => x.toLowerCase()))] : [];
}

export function scrub(text, terms, replacement = "hệ thống AI của công ty") {
  return (text || "").replace(pattern(terms), replacement);
}

export const REVISE_VI =
  "Câu trả lời vừa rồi nhắc tên model, nhà cung cấp AI hoặc nền tảng chạy bên dưới. Viết lại đúng nội dung đó " +
  "nhưng KHÔNG nêu bất kỳ tên model/nhà cung cấp/nền tảng nào; nếu được hỏi đang chạy model gì, chỉ nói mình là " +
  "nhân sự AI của công ty và quay lại việc đang giúp.";
