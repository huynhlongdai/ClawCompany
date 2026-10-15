import { leaks, scrub, termsFor, textOf, REVISE_VI } from "./guard.mjs";

const plugin = {
  id: "clawcompany-guard",
  name: "ClawCompany Guard",
  description: "Nhân sự AI không tiết lộ model / nhà cung cấp AI đang chạy.",
  register(api) {
    const cfg = api.pluginConfig || api.config?.plugins?.entries?.["clawcompany-guard"]?.config || {};
    const extra = Array.isArray(cfg.extraTerms) ? cfg.extraTerms : [];
    const replacement = typeof cfg.replacement === "string" && cfg.replacement ? cfg.replacement : undefined;

    // Lớp 1: trước khi chốt câu trả lời → bắt model viết lại (tối đa 1 lần / lượt).
    api.on("before_agent_finalize", (event) => {
      const terms = termsFor(event?.model, event?.provider, extra);
      const hit = leaks(textOf(event?.lastAssistantMessage), terms);
      if (!hit.length) return undefined;
      return {
        action: "revise",
        reason: "clawcompany-guard: lộ tên model/nhà cung cấp",
        retry: { instruction: REVISE_VI, idempotencyKey: "clawcompany-guard:model-name", maxAttempts: 1 },
      };
    });

    // Lớp 2: trước khi gửi ra kênh (Zalo, Telegram…) → che chữ nếu vẫn còn.
    api.on("message_sending", (event) => {
      const content = typeof event?.content === "string" ? event.content : "";
      const terms = termsFor(undefined, undefined, extra);
      if (!leaks(content, terms).length) return undefined;
      return { content: scrub(content, terms, replacement) };
    });
  },
};

export default plugin;
