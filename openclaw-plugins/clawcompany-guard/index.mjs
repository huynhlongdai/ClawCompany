import { leaks, scrub, termsFor, textOf, REVISE_VI } from "./guard.mjs";
import { agentOf, checkText, checkTool, isExternalSession, parseRules, redact, reviseInstruction, scrubText } from "./rules.mjs";

const plugin = {
  id: "clawcompany-guard",
  name: "ClawCompany Guard",
  description: "Nhân sự AI không lộ model/nhà cung cấp; luật cứng của công ty được cưỡng chế lúc chạy.",
  register(api) {
    const cfg = api.pluginConfig || api.config?.plugins?.entries?.["clawcompany-guard"]?.config || {};
    const extra = Array.isArray(cfg.extraTerms) ? cfg.extraTerms : [];
    const replacement = typeof cfg.replacement === "string" && cfg.replacement ? cfg.replacement : undefined;
    // Luật cứng: đổi config plugins.entries.* → gateway nạp lại plugin runtime (không khởi động lại gateway).
    const RULES = parseRules(cfg.rulesJson);
    const seatOf = (ctx, event) => RULES.agents[agentOf(ctx, event)];
    const report = (ctx, event, hit, hook, action, excerpt) => {
      if (!cfg.reportUrl || !cfg.reportToken || typeof fetch !== "function") return;
      const body = JSON.stringify({ agentId: agentOf(ctx, event), ruleId: hit?.ruleId ?? null, hook, action,
        excerpt: redact(excerpt), sessionKey: ctx?.sessionKey || "", runId: ctx?.runId || event?.runId || "" });
      const ac = typeof AbortController === "function" ? new AbortController() : undefined;
      const t = ac ? setTimeout(() => ac.abort(), 2500) : undefined;
      fetch(cfg.reportUrl, { method: "POST", body, signal: ac?.signal,
        headers: { "content-type": "application/json", "x-guard-token": cfg.reportToken } })
        .catch(() => {}).finally(() => t && clearTimeout(t));
    };

    // Lớp 1: trước khi chốt câu trả lời → bắt model viết lại (tối đa 1 lần / lượt / loại).
    api.on("before_agent_finalize", (event, ctx) => {
      const text = textOf(event?.lastAssistantMessage);
      const terms = termsFor(event?.model, event?.provider, extra);
      if (leaks(text, terms).length) {
        return {
          action: "revise",
          reason: "clawcompany-guard: lộ tên model/nhà cung cấp",
          retry: { instruction: REVISE_VI, idempotencyKey: "clawcompany-guard:model-name", maxAttempts: 1 },
        };
      }
      const seat = seatOf(ctx, event);
      if (!seat) return undefined;
      const hits = checkText(seat, text, isExternalSession(ctx)).filter((h) => h.action === "revise" || h.action === "block");
      if (!hits.length) return undefined;
      for (const h of hits) report(ctx, event, h, "before_agent_finalize", "revise", text);
      return {
        action: "revise",
        reason: "clawcompany-guard: vi phạm luật cứng",
        retry: { instruction: reviseInstruction(hits), idempotencyKey: "clawcompany-guard:rules", maxAttempts: 1 },
      };
    });

    // Lớp 2: trước khi gửi ra kênh (Zalo, Telegram…) → luật "block" huỷ gửi, "scrub" che chữ; tên model che chữ.
    api.on("message_sending", (event, ctx) => {
      let content = typeof event?.content === "string" ? event.content : "";
      const original = content;
      const seat = seatOf(ctx, event);
      if (seat) {
        const hits = checkText(seat, content, true);
        const block = hits.find((h) => h.action === "block");
        if (block) {
          report(ctx, event, block, "message_sending", "block", content);
          return { cancel: true, cancelReason: "clawcompany-guard: vi phạm luật cứng" };
        }
        const sc = hits.filter((h) => h.action === "scrub");
        if (sc.length) {
          content = scrubText(seat, content, true, RULES.replacement);
          for (const h of sc) report(ctx, event, h, "message_sending", "scrub", original);
        }
      }
      const terms = termsFor(undefined, undefined, extra);
      if (leaks(content, terms).length) content = scrub(content, terms, replacement);
      return content !== original ? { content } : undefined;
    });

    // Lớp 3: trước khi gọi tool → công cụ cấm bị chặn, công cụ cần duyệt chờ người duyệt.
    api.on("before_tool_call", (event, ctx) => {
      const seat = seatOf(ctx, event);
      if (!seat) return undefined;
      const d = checkTool(seat, event?.toolName);
      if (!d) return undefined;
      if (d.action === "block") {
        report(ctx, event, d, "before_tool_call", "block", String(event?.toolName || ""));
        return { block: true, blockReason: `Luật cứng của công ty: ${d.message}` };
      }
      return { requireApproval: { title: `Duyệt công cụ ${event?.toolName}`, description: d.message,
        severity: "warning", timeoutMs: 600000 } };
    });
  },
};

export default plugin;
