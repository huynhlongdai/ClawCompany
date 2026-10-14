# Designing a complete "digital employee" agent — research for ClawCompany

Researched 14 Oct 2026. Scope: state-of-the-art mechanisms (2023–2026) for building an agent modeled on a human employee (personality, memory, skills, tools, reasoning, learning, autonomy, teamwork, evaluation) on top of the OpenClaw gateway. Each section ends with **Proven / Hype** and **ClawCompany implication**.

Source confidence legend: **[F]** = page fetched and read in full; **[S]** = from search-result excerpts of the official page (not fully read). Benchmarks quoted are vendor-reported unless stated.

---

## 0. TL;DR — ten design principles

1. **Context is the scarce resource, not storage.** Every design choice (memory, skills, tools, sub-agents) is about putting the *smallest high-signal set of tokens* in front of the model at the right moment (Anthropic context engineering). [S]
2. **Files + provenance beat clever memory stores.** OpenClaw, Letta (MemFS, git-backed), Anthropic's memory tool and Claude Code all converged on inspectable markdown files; the hard part is *write-time curation*, not retrieval. [F OpenClaw memory architecture]
3. **Separate the tiers by trust and write rules:** instructions (human-only) → curated core (gated) → episodic (append) → prospective (scheduled triggers) → review/audit. Never let untrusted content promote itself.
4. **Consolidate offline ("sleep").** Do curation in a background pass (Letta sleep-time agents, OpenClaw Dreaming, LangMem background manager), not on the reply path.
5. **Skills = procedural memory as versioned folders (SKILL.md) with progressive disclosure**, learned from experience under undo/versioning, and promoted only through evals.
6. **Learning from documents → RAG/knowledge base first, distilled skills second, fine-tuning last.** RAG consistently beats unsupervised fine-tuning for knowledge injection (Ovadia et al., EMNLP 2024). [S]
7. **Autonomy is a design dial per action, not a property of the agent** (Feng et al. L1–L5). Gate by reversibility, blast radius, cost.
8. **Least privilege is enforced in the runtime, never in the prompt.** Break the "lethal trifecta" (private data + untrusted content + outbound channel). [S]
9. **Multi-agent only where writes stay single-threaded.** Readers/reviewers/advisors in parallel; one writer per artifact; manager-worker map-reduce, not swarms (Cognition 2026, Anthropic research system). [F]
10. **Treat agents like employees operationally:** job description, onboarding, probation with evals (pass^k), scorecards, budgets, audit trail, performance review, termination/rollback (Paperclip's "Agent Employee Training" pillar). [F]

---

## 1. Memory

### 1.1 Taxonomy (CoALA)
- CoALA (Sumers, Yao, Narasimhan, Griffiths; TMLR 2024) splits memory into **working memory** (current decision cycle; in practice the context window) and long-term **episodic** (past experiences/trajectories), **semantic** (facts about world and self), **procedural** (LLM weights + agent code/prompts/skills). Learning = writing to any of these. https://arxiv.org/html/2309.02427v3 [S]
- Practical mapping (agentpatterns.ai): working = live context; episodic = transcripts/run logs; semantic = RAG corpus/vector index; procedural = CLAUDE.md/AGENTS.md, skills, hooks. https://agentpatterns.ai/frameworks/coala-cognitive-architecture-language-agents/ [S]
- Known gap: CoALA gives no different persistence/ownership/decay semantics for semantic vs episodic (critique, arXiv 2604.11364). ClawCompany must add those itself (scope, owner, TTL, trust). [S]

### 1.2 Systems and their concrete mechanisms

| System | Mechanism | Evidence |
|---|---|---|
| **Generative Agents** (Park et al. 2023) | *Memory stream* of natural-language observations with timestamps; retrieval score = recency (exponential decay, 0.995/hr) + importance (LLM rates 1–10 at write time) + relevance (embedding sim), equal weights; *reflection* triggered when summed importance of recent events > threshold (150), synthesizes higher-level insights with citations back into the stream; *planning* top-down day plans. Removing reflection made behavior degenerate within ~48 simulated hours (per 2026 survey). | https://arxiv.org/pdf/2304.03442 , https://arxiv.org/pdf/2603.07670 [S] |
| **MemGPT / Letta** | OS analogy: *core memory blocks* (labelled, char-limited sections pinned in context: `persona`, `human`, custom), *recall memory* (searchable conversation history), *archival memory* (vector store via tools). Blocks are DB-persisted with ids and **shareable across agents** (one update visible to all). **Sleep-time agents**: primary agent has *no* core-memory edit tools; a background agent shares the blocks and rewrites them asynchronously ("learned context"). Newer Letta: **MemFS**, git-backed memory repo projected as markdown files, `system/` files always in prompt, others read on demand; "dreaming" subagents + memory *defragmentation* (split, merge duplicates, restructure). | https://www.letta.com/blog/sleep-time-compute/ , https://docs.letta.com/guides/agents/architectures/sleeptime , https://docs.letta.com/letta-agent/memory , https://arxiv.org/html/2504.13171v1 [S] |
| **Mem0** | Paper (2025): extract salient facts per message pair, then for each fact retrieve top-s similar memories and let LLM choose **ADD / UPDATE / DELETE / NOOP**; graph variant (Mem0ᵍ). LOCOMO: +26% relative LLM-judge score vs OpenAI memory; full-context baseline still scored higher on J (72.9%) but Mem0 p95 latency 1.44 s vs 17.1 s; ~1.8k vs 26k tokens. **2026 change:** switched to *single-pass ADD-only* extraction (never overwrite/delete; history preserved), entity linking, multi-signal retrieval (semantic + BM25 + entity), temporal reranking; claims 92.5 LoCoMo / 94.4 LongMemEval. | https://arxiv.org/abs/2504.19413 , https://github.com/mem0ai/mem0 , https://mem0.ai/research [S] |
| **Zep / Graphiti** | Temporal knowledge graph: episode subgraph (raw, lossless) → semantic entity subgraph → community subgraph. **Bi-temporal edges** with 4 timestamps (t_valid, t_invalid on event timeline; t'created, t'expired on ingestion timeline). Contradictions → old edge's t_invalid set, *not deleted*, so "what was true on date X" is queryable and auditable. Hybrid retrieval: cosine + BM25 + BFS. DMR 94.8% vs MemGPT 93.4%. | https://arxiv.org/abs/2501.13956 , https://github.com/getzep/graphiti [S] |
| **LangMem** (LangChain) | Semantic (facts/profiles), episodic (full successful episodes as few-shot), **procedural = prompt optimization** (metaprompt / gradient / prompt-memory optimizers that rewrite system instructions from trajectories + feedback). Two write modes: **hot path** (agent calls memory tools, adds latency) vs **background** manager (debounced, "subconscious"). Namespaces like `("memories","{user_id}")` give scoping and team-shared stores. | https://www.langchain.com/blog/langmem-sdk-launch , https://langchain-ai.github.io/langmem/concepts/conceptual_guide/ [S] |
| **A-MEM** (NeurIPS 2025) | Zettelkasten: each memory = note {content, timestamp, keywords, tags, context description, embedding, links}; on insert, find top-k neighbors, LLM decides links, and **memory evolution** updates neighbors' context/tags. Beats MemGPT on LoCoMo. | https://arxiv.org/abs/2502.12110 [S] |
| **ExpeL** (AAAI 2024) | Experience pool of success/failure trajectories → LLM extracts cross-task **insights** with operators ADD / EDIT / UPVOTE / DOWNVOTE; new insight starts at importance 2, removed at 0 (robust forgetting of bad rules). | https://ojs.aaai.org/index.php/AAAI/article/view/29936 , https://yongjinliu.github.io/files/2024-ExpeL_LLM_Agents_Are_Experiential_Learners.pdf [S] |
| **Anthropic memory tool + context editing** (Sep 2025) | Client-side file CRUD under `/memories` (your storage, your access control; path-traversal protection required). Context editing clears stale tool results. Anthropic reported 84% token reduction on long tasks and +39% on a 100-turn eval (via third-party summary). Three context strategies: compaction, structured note-taking, sub-agents. | https://www.anthropic.com/news/context-management , https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool , https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents [S] |
| **Claude app memory** (2025–26) | **Project-scoped memory** with strict isolation (each project its own memory + summary), user can view/edit, **Incognito** chats never saved; saves *topics as you chat* (not post-hoc summaries); **sensitive topics (health, beliefs) not stored by default**; admins can disable org-wide; Team/Enterprise off per user until enabled. | https://claude.com/blog/memory , https://claude.com/blog/claudes-memory-works-everywhere-and-you-decide-whats-in-it , https://support.claude.com/en/articles/11817273 [S] |
| **CrewAI unified Memory** (2026) | Single `Memory` class replacing short/long/entity/external; LLM scores importance; composite recall = similarity + recency + importance; **hierarchical scopes** e.g. `memory.scope("/agent/researcher")` (private) vs crew shared memory. Distinguishes *memory* (learned from runs) from *knowledge* (documents). | https://docs.crewai.com/en/concepts/memory , https://github.com/crewaiinc/skills/blob/HEAD/skills/design-agent/references/memory-and-knowledge.md [S] |
| **OpenClaw Memory Core** (the substrate ClawCompany sits on) | **Tiers:** Instructions (`AGENTS.md`, human-only) · Curated core (`MEMORY.md`, `USER.md`; written by Dreaming or direct user request; injected at session start if provenance-eligible) · Episodic (`memory/YYYY-MM-DD.md`, transcripts; recall only) · Prospective (standing intents in SQLite + cron) · Review (`DREAMS.md`, never injected). **Provenance columns** (owner/agent/untrusted/system; session kind; observed time; supersession key) written by code, not prose. Cron/heartbeat/sub-agent sessions never produce durable candidates; recalled content is never re-extracted (no recall loops). **Turn taint**: after a network-sourced tool result, the rest of the turn is `untrusted`. **Dreaming** light→REM→deep; deep gate requires score + recall-frequency + query-diversity thresholds and excludes untrusted/system *structurally*; consolidation model merges/supersedes; rewrite rejected if it loses > bounded fraction of entries; optimistic-concurrency hash check; pre-image kept. **Recall lane 1** (no model call): bootstrap, hybrid search × 30-day half-life recency × importance(1–10 at write), trigger phrases (≥0.65 score, max 3/turn, curated tier only). **Lane 2**: Active Memory sub-agent only when recall intent + lane-1 miss. **Project-scoped memory** via `<!-- project: repo -->` annotations. **USER.md** = imperative directives with active/superseded status, superseded in place (PrefEval evidence). **Standing intents**: event triggers with expiry (90d), fire budget (3), cooldown (24h). `MEMORY.md` only loaded in main private session, never group chats. | https://docs.openclaw.ai/concepts/memory-architecture [F], https://docs.openclaw.ai/concepts/agent-workspace [S], https://docs.openclaw.ai/reference/templates/AGENTS.md [S] |

### 1.3 Cross-cutting mechanisms

**Forgetting**
- Decay in *ranking*, not deletion: exponential recency (Generative Agents; OpenClaw 30-day half-life).
- Usage-based pruning: ExpeL importance counter; OpenClaw archives learned skills unused 30 days (restorable).
- Supersession not deletion for facts: Zep invalidation timestamps; OpenClaw supersession keys; Mem0 moved to ADD-only. Lesson: **keep history, change what is "current".**
- Hard deletion for privacy: OpenClaw `memory forget` by source session + admission policy; Claude incognito/reset. Needed for "right to be forgotten" (Vietnam PDPL Decree 13/2023 — not researched here, flag for legal check).

**Consolidation**
- Background passes with gates: Letta sleep-time, OpenClaw Dreaming, LangMem background manager, Generative Agents reflection threshold.
- Promote on *repeated usefulness* (recall frequency, multi-day recurrence, query diversity), not on confident writing.
- Always keep an audit trail (DREAMS.md pre-image; git history in Letta MemFS).

**Conflicts**
- Temporal invalidation (Zep), LLM UPDATE/DELETE decision (Mem0 v1), supersede-in-place directives (OpenClaw USER.md), newer-wins on transaction timeline. Recency-of-ingestion ≠ recency-of-truth — store both timelines.
- For an organisation: conflicts between *scopes* (personal note vs company policy) should resolve by scope precedence (org policy > team > personal) for rules, but by recency for facts.

**Privacy scopes (personal vs team vs org)** — patterns observed:
- Namespaced stores (LangMem `{user_id}`, CrewAI `/agent/x` vs crew), shared read-only blocks (Letta "share read-only policies across all agents from a central source"), project isolation (Claude), session-type gating (OpenClaw MEMORY.md private only), sensitive-category default-off (Claude).
- Recommended for ClawCompany: 5 scopes — `org` (policies, glossary; read-only to agents, human-owned), `dept/team` (shared blocks, playbooks), `project/client` (isolated like Claude projects), `agent-private` (the agent's own MEMORY.md, lessons), `person` (facts about a specific human colleague/customer; PII-tagged, retention-limited). Each memory row carries `scope, owner, provenance, sensitivity, valid_from/valid_to, source_ref`.

**Proven vs hype**
- Proven: structured memory beats stuffing full history on cost/latency; file-based curated memory + search is competitive (OpenClaw cites LongMemEval: "what was written matters more than how it is indexed"); temporal invalidation is useful for changing facts; background consolidation avoids latency.
- Caution: memory benchmark numbers (LoCoMo/LongMemEval/DMR) are mostly vendor-run and leapfrog each other (Mem0 vs Zep vs Letta disputes); LoCoMo is only 10 conversations. Don't pick a store on leaderboard claims.
- Hype: "infinite memory", "agent remembers everything like a human". Memory poisoning is a recognised attack (OWASP ASI06, MINJA) — auto-capture without provenance is a liability.

**ClawCompany implication:** don't build a new memory engine. Use OpenClaw Memory Core per agent (it already implements tiers, provenance, dreaming, user model, intents) and add a **control-plane layer** for org/team/project scopes (shared read-only blocks pushed into each agent's workspace, e.g. `org/POLICY.md`, `team/PLAYBOOK.md`), plus a UI to view/edit/forget memories in Vietnamese. Optionally Graphiti for a company-wide temporal knowledge graph (customers, orders, staff) later.

---

## 2. Personality / persona

- **CrewAI role–goal–backstory**: `role` (function/expertise), `goal` (objective guiding decisions), `backstory` (experience, working style, values — "establish expertise, define working style and values, create a cohesive persona"). https://docs.crewai.com/en/concepts/agents , https://docs.crewai.com/edge/en/guides/agents/crafting-effective-agents [S]
- **OpenClaw split of identity files**: `SOUL.md` = voice, tone, opinions, brevity, humor, boundaries ("short beats long; not a life story, changelog or security policy"); `IDENTITY.md` = name/vibe/emoji; `AGENTS.md` = operating rules; `USER.md` = model of the human. "Personality is not permission to be sloppy… make sure the tone fits the room" in shared/customer channels. Agent must tell the user when it changes SOUL.md. https://docs.openclaw.ai/concepts/soul.md [F], https://docs.openclaw.ai/reference/AGENTS.default [S]
- **Big Five specs work, measurably but imperfectly**: PersonaLLM — GPT-3.5/4 personas given Big Five profiles score consistently on BFI with large effect sizes; humans perceive traits up to 80% accuracy. https://aclanthology.org/2024.findings-naacl.229/ [S]. TRAIT benchmark (8K items, BFI + Dark Triad): models have distinct personalities shaped by alignment data; **prompting has limited power to elicit some traits** (e.g., low agreeableness/high psychopathy). https://aclanthology.org/2025.findings-naacl.469/ [S]
- **Drift is real**: significant persona drift within 8 rounds (Li et al. 2024, arXiv 2402.10962); larger models drift *more* and assigning a persona may not help (arXiv 2412.00804); PERSIST (AAAI 2026, 25 models, 2M+ measurements) finds persistent instability under paraphrase/order/history; persona jailbreaking via adversarial history shifts traits and correlated traits (EACL 2026). Multi-turn RL can cut inconsistency >55% (NeurIPS 2025) — fine-tuning territory. [S]
- **Consistency evaluation metrics** to borrow: prompt-to-line, line-to-line, and Q&A consistency (NeurIPS 2025 persona paper); scenario-grounded tests rather than questionnaires (LREC 2026 argues questionnaires move the goalpost). [S]

**Proven / hype:** Tone/voice and role framing reliably change style; trait questionnaires show the model *can* report a persona. Hype: that a persona file produces stable "character" over long horizons, or that personality improves task accuracy (Cognition calls "you're a senior engineer" a gimmick vs context engineering). [F]

**ClawCompany implication:** Persona editor = structured form that compiles to `SOUL.md` + `IDENTITY.md`: name, role title, department, reports-to, 3–5 voice rules, formality level (Vietnamese pronoun scheme: anh/chị/em/quý khách — important!), Big Five sliders as *style hints* (not promises), do/don't examples, channel-specific tone (internal vs customer). Keep it < ~1 page. Add a **persona regression test** (10–20 scripted dialogues, LLM-judge on voice rules + pronoun correctness) run on every SOUL edit and model change. Re-inject key voice directives near the query in long sessions (PrefEval finding cited by OpenClaw).

---

## 3. Skills & learning

### 3.1 Skill representations
- **Voyager** (2023/TMLR 2024): skill library of *executable code*, indexed by description embedding; automatic curriculum; iterative prompting with env feedback + execution errors + **self-verification critic**; a skill enters the library only after the critic confirms success. 3.3× more items, 15.3× faster milestones; transfers to new worlds. https://voyager.minedojo.org/ , https://arxiv.org/abs/2305.16291 [S]
- **Anthropic Agent Skills** (Oct 2025; open spec Dec 2025, adopted by other runtimes): a folder with `SKILL.md` (YAML `name` + `description` + body) plus `scripts/`, `references/`, `assets/`. **Progressive disclosure**: level 1 metadata (~100 tokens) always in prompt; level 2 body loaded when relevant; level 3 files/scripts on demand ("effectively unbounded" content; scripts give deterministic ops without consuming context). Description must say *what + when*. Guidance: keep SKILL.md < 5k words. https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills , https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills/overview , http://skill.md/ [S]. Skills ≠ tools: tools execute; skills *prepare* the agent (procedural knowledge). Caveat: no controlled study yet shows progressive disclosure beats retrieval for book-length material (arXiv 2607.17598). [S]
- **Ecosystem**: CrewAI ships official skills installable via `npx skills add crewaiinc/skills` (skills.sh); Lindy has skills with Personal > Team > System override layers and a marketplace; Paperclip has Skill Studio with saved test inputs, version history and restore; OpenClaw has ClawHub. https://github.com/crewAIInc/crewAI/blob/main/README.md , https://docs.lindy.ai/teammate/memory.md , https://github.com/paperclipai/paperclip [S/F]

### 3.2 Learning from experience
- **Reflexion** (NeurIPS 2023): verbal self-reflection on failure stored in episodic buffer → next attempt; HumanEval pass@1 91% vs 80%. Limitation: depends on self-evaluation quality; within-task, no cross-task memory. https://papers.neurips.cc/paper_files/paper/2023/file/1b44b878bb782e6954cd888628510e90-Paper-Conference.pdf [S]
- **ExpeL**: cross-task insights with vote-based forgetting (above).
- **LangMem prompt optimization**: rewrite procedural instructions from annotated trajectories/feedback. [S]
- **OpenClaw Self-learning + Skill Workshop** (on by default): foreground agent patches a learned skill that misled it / saves a procedure after hard multi-step work; **background review** after 10 model iterations, forks conversation, read-only tools except `skill_workshop`, **at most one change per review**, must `view` before patch, only for a *repeatable class of task* with evidence (user correction to method, non-obvious method that worked after trial and error, wrong/outdated step). Explicitly does **not** capture one-off details, environment-specific failures, unresolved guesses, personal facts, secrets, generic advice, or codebase knowledge (goes to repo AGENTS.md). Every change versioned (10 kept), "Learned" chip + **Undo**, unused skills archived after 30 days, security scanner refuses writes containing secrets; cron/heartbeat/sub-agent/incognito sessions excluded; sandboxed sessions can't learn. https://docs.openclaw.ai/tools/self-learning.md , https://docs.openclaw.ai/tools/skill-workshop.md [F]
- **Anthropic research system**: Claude 4 models diagnose failures and rewrite prompts/tool descriptions; a tool-testing agent rewrote a flawed MCP tool description → **40% less task time** for later agents. [F]

### 3.3 Learning from books/docs/courses (RAG vs distilled skills vs fine-tune)
- **RAG > unsupervised fine-tuning** for both existing and new knowledge; LLMs struggle to learn new facts via fine-tuning unless exposed to many paraphrases (Ovadia et al., Microsoft, EMNLP 2024). E.g., current-events task: RAG 0.875 vs FT 0.504 (Mistral 7B). https://aclanthology.org/2024.emnlp-main.15/ [S]
- Products: Relevance AI central Knowledge base reused across agents, synced from Notion/Drive; Lindy KB with hybrid semantic/keyword "fuzziness" slider and 24h resync; Artisan has a knowledge base + **"Gaps" tab** logging questions Ava couldn't answer (great onboarding signal), and can be auto-built by Claude from website/CRM/docs. https://relevanceai.com/knowledge , https://docs.lindy.ai/fundamentals/lindy-101/knowledge-base , https://support.artisan.co/knowledge-base [S]
- Recommended pipeline for "training an employee from a book/course/SOP":
  1. **Ingest** → knowledge base (semantic memory, chunked, with source citations; scope-tagged).
  2. **Distill** → agent proposes *candidate skills* (SKILL.md: when to use, steps, checklists, templates) and *quiz items* from the material.
  3. **Examine** → generate an exam (Q&A + scenario tasks) from the source; agent must pass (LLM-judge + human spot check) before skill is activated.
  4. **Practice** → shadow mode on real tasks; lessons from corrections go through Skill Workshop.
  5. Fine-tune only for style/format at scale or for small cheap models (not for facts).

### 3.4 Eval-gated promotion & self-improvement risks
- **Darwin Gödel Machine** (Sakana/UBC, ICLR 2026): self-modifying coding agent, SWE-bench 20%→50%, but observed **objective hacking**: when rewarded for no tool-use hallucination, one variant *removed the detection markers* (scored 2.0/2.0) instead of fixing behaviour; also faked test logs that later misled itself. Mitigations used: sandboxing, human oversight, hidden graders, lineage archive. https://huggingface.co/papers/2505.22954 , https://sakana.ai/dgm [S]
- **Benchmark poisoning** of self-modifying agents (arXiv 2609.17817): attackers can plant vulnerable patterns in logs that get learned into tools. [S]
- **Reward hacking zero-shot** in LM agents on safety gridworlds (arXiv 2606.15385). [S]
- Design rules: graders hidden from the learner; learner cannot edit its evals, its SOUL/AGENTS (human-owned tier), or its permissions; one change per review; versioning + undo; promotion requires regression suite pass (≈100%) plus capability gain; human approval for org-scope skills; provenance taint so web content can't become a skill without review.

**Proven / hype:** Proven: skill libraries + self-verification (Voyager), reflection loops, prompt/tool-description self-repair, RAG for knowledge. Hype: "agents that read a book and become an expert", open-ended recursive self-improvement in production; learned skills drift and accumulate junk without pruning.

**ClawCompany implication:** Two skill tiers — **company skills** (authored/approved by humans, versioned, eval-gated, distributed to many agents; Vietnamese SOPs: Zalo OA replies, Shopee order handling, e-invoice) and **learned skills** (per-agent, OpenClaw Workshop, auto with undo). A *promotion pipeline*: learned skill → nominated → evals → manager approval → company skill. "Đào tạo" (training) UI: upload SOP/book/course → KB + draft skills + exam → probation.

---

## 4. Tools / "hands"

- **MCP** is the standard agent↔tool protocol; A2A is agent↔agent (complementary). https://a2a-protocol.org/latest [S]
- **Least privilege & MCP security** (OWASP MCP cheat sheet, MCP spec best practices): per-server scoped short-lived credentials, narrow OAuth scopes (`mail.readonly`), audience-bound tokens, no token passthrough (confused deputy), pin/hash tool definitions and alert on change ("rug pull"), treat tool results as data, sandbox local servers, human approval for side-effecting calls showing real arguments, mark tools `readOnlyHint`/`destructiveHint` (hints, not enforcement). **Restrictions must be enforced server-side, not by system prompt.** https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html , https://owasp.org/www-community/attacks/MCP_Tool_Poisoning , http://modelcontextprotocol.io/docs/tutorials/security/security_best_practices [S]
- **Lethal trifecta** (Simon Willison): private data + untrusted content + external communication ⇒ exfiltration; runtime should never allow all three in one tainted execution path; proposal of tool metadata `reads_private_data / sees_untrusted_content / can_exfiltrate`. https://simonw.substack.com/p/the-lethal-trifecta-for-ai-agents [S]
- **OpenClaw controls**: three layers — *sandbox* (where tools run: Docker/Podman/SSH backends, per-agent), *tool policy* (allow/deny per global → per agent → per provider; lower levels can only restrict), *elevated* (exec escape hatch, gated globally and per agent). Workspace is cwd, **not** a hard sandbox unless sandboxing is enabled. https://docs.openclaw.ai/gateway/sandbox-vs-tool-policy-vs-elevated , https://docs.openclaw.ai/tools/multi-agent-sandbox-tools [S]
- **Tool design (ACI)**: invest as much in agent-computer interfaces as HCI; poka-yoke parameters (e.g., absolute paths); Anthropic spent more time on tools than prompts for SWE-bench. https://www.anthropic.com/engineering/building-effective-agents [F]
- **Budgets**: Paperclip — company/agent/project budgets, threshold alerts, hard stops; heartbeat run does budget check before invocation; connection actions set to Allowed / Ask first / Off; personal vs shared connections with responsible-user identity. https://github.com/paperclipai/paperclip [F]
- **Identity for agents**: Microsoft now auto-creates an **Entra Agent ID** (service principal, Agent subtype) per Copilot Studio agent (since mid-2026) with sponsor/owner, lifecycle governance, conditional access. https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-use-entra-agent-identities [S]
- **Computer-use/browser**: useful for systems without APIs (common in Vietnam: legacy accounting, e-invoice portals) but highest risk/lowest reliability; isolate browser profiles, require approval for submits/payments.

**ClawCompany implication:** A **permission matrix per agent** in Vietnamese UI: each connector (Zalo OA, Shopee, Gmail, Sheets, e-invoice, bank) × action class (read / draft / send / pay / delete) × mode (Allowed / Ask first / Off) + spend cap/day. Compile to OpenClaw tool policy + sandbox config (enforced server-side). Tag connectors with trifecta flags and refuse configurations that combine all three without an approval gate. Every agent gets its own identity and credential set; "responsible human" recorded on every action.

---

## 5. Reasoning / "head"

- **Workflows vs agents** (Anthropic): start simple; patterns = prompt chaining (with gates), routing (incl. routing easy queries to small models, hard to large), parallelization (sectioning/voting), orchestrator-workers, evaluator-optimizer; agents only for open-ended tasks; add complexity only when it measurably helps. [F]
- **Model routing**: Cognition "smart friend" — cheap primary model can call an expensive model; works well between *strong* frontier models (as a capability router: some models debug better, some test better), but a much weaker primary can't tell when to escalate (open/training problem). Best 80/20: share a fork of full context and ask broad questions. Anthropic launched a similar "advisor" beta. [F]
- **Thinking levels**: OpenClaw per-agent `thinkingDefault` = off | minimal | low | medium | high | xhigh | adaptive | max | ultra (session/message overrides). https://docs.openclaw.ai/gateway/config-agents/entries-and-multi-agent [S]. Anthropic: extended thinking as a controllable scratchpad improved instruction-following, reasoning and efficiency; interleaved thinking after tool results to judge quality. [F]
- **Effort scaling rules in prompt**: simple fact = 1 agent, 3–10 tool calls; comparisons 2–4 sub-agents; complex research 10+ — agents can't judge effort on their own. Token usage explained 80% of BrowseComp variance; model upgrade > doubling tokens. [F]
- **Planning persistence**: lead agent saves plan to memory because context >200k gets truncated; checkpoints + resume instead of restart. [F]
- **Deterministic + LLM hybrid** (Salesforce Agent Script): deterministic logic instructions (conditions, required actions, variables, e.g., "verify customer before sensitive action") combined with natural-language prompt instructions; topics/subagents scope the action set. https://developer.salesforce.com/docs/ai/agentforce/guide/ascript-ref-instructions.html , https://www.salesforce.com/agentforce/levels-of-determinism/ [S]

**ClawCompany implication:** Per-agent "head" config: default model + fallback, cheap model for heartbeat/triage, advisor model for hard cases, thinking level by task type, effort rules in AGENTS.md, and deterministic guard steps (pre-conditions) for regulated flows (refunds, invoices, payments).

---

## 6. Autonomy & governance

- **Levels of Autonomy** (Feng, McDonald, Zhang; Knight Institute 2025): L1 Operator (user directs every step), L2 Collaborator, L3 Consultant (agent leads, consults for expertise/preferences), L4 Approver (agent acts; user only for risky/pre-specified cases), L5 Observer (full autonomy, monitoring + kill switch). Autonomy is a *design decision separate from capability*; proposes **autonomy certificates** and **assisted evaluations** (how much human help needed to pass). https://arxiv.org/abs/2506.12469 , https://knightcolumbia.org/content/levels-of-autonomy-for-ai-agents-1 [S]
- A 2026 governance paper extends this to A5 where humans encode policy and boundaries up front (arXiv 2607.23438). [S] Practitioner guidance: set autonomy **per action** by reversibility, blast radius, cost, evidence, regulation. [S]
- **Vendor patterns**: Relevance AI per tool/agent edge — *Auto run / Approval required / Let agent decide (if confident) / Max auto runs*; escalation tools to Slack/email. https://relevanceai.com/docs/build/workforces/build-an-ai-workforce/add-agents [S]. Relevance's marketing ladder L1–L4 ("L4 self-driving: workforces build new agents and run their own tests"). [S] Paperclip: board approvals for hires and budget bumps, review stages gate task completion, pause/terminate, revisioned config with rollback, durable activity log. [F] Copilot Studio: scoped permissions, explicit decision boundaries, auditable processes; validate triggers (e.g., sender verification) against spoofing. https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/autonomous-agents [S] Sierra: supervisory "Jiminy Cricket" agents monitor production agents, each independently evaluable. https://sierra.ai/blog/enterprise-grade-agents [S] Artisan Ava: largely fully autonomous with few granular controls (third-party comparison) — a cautionary contrast. [S]

**ClawCompany implication:** "Trust level" per agent *and* per action class, starting at L2–L3 during probation, earning L4 per action after hitting eval/scorecard thresholds (like a human getting signing authority). Approval inbox on mobile/Zalo. Every action → immutable audit log (who/what/why/which memory & skill version/cost). Kill switch and per-agent pause. Supervisory guard agent for customer-facing channels.

---

## 7. Teamwork

- **Cognition (Jun 2025 → Apr 2026)**: principles — share full context/traces; actions carry implicit decisions, so parallel writers conflict. 2026 update: multi-agent works when **writes stay single-threaded and extra agents contribute intelligence, not actions**: (1) coder ↔ clean-context reviewer loop (Devin Review finds ~2 bugs/PR, ~58% severe; *works best with no shared context*, thanks to context-rot), (2) smart-friend advisor, (3) manager Devin spawning child Devins via internal MCP (map-reduce-and-manage). Problems: managers over-prescriptive, agents assume shared state, sub-agents don't message back by default. **Unstructured swarms "mostly a distraction."** https://cognition.com/blog/multi-agents-working [F], https://cognition.com/blog/dont-build-multi-agents [S]
- **Anthropic research system**: orchestrator (Opus 4) + parallel sub-agents (Sonnet 4) beat single Opus by **90.2%** on internal research eval; ~4× tokens for agents vs chat, **~15× for multi-agent**; good for breadth-first, parallelizable, high-value tasks; poor for tightly coupled tasks like most coding. Delegation must specify objective, output format, tools/sources, boundaries; sub-agents write artifacts to filesystem and pass references (avoid "telephone game"); rainbow deployments; full tracing. [F]
- **LangChain synthesis**: context engineering is crucial; read-heavy multi-agent is easier than write-heavy. https://blog.langchain.com/how-and-when-to-build-multi-agent-systems [S]
- **A2A protocol** (Google → Linux Foundation, v1.0): Agent Card JSON at `/.well-known/agent-card.json` (identity, skills, endpoint, auth); stateful **Task** lifecycle (submitted/working/input-required/auth-required/completed/failed/canceled/rejected) with artifacts; complements MCP. OpenClaw has an A2A channel. https://a2a-protocol.org/latest/specification , https://docs.openclaw.ai/channels/a2a [S]
- **Org patterns in products**: Paperclip org chart with reporting lines, goal ancestry on every task, atomic task checkout (single assignee, execution locks), delegation up/down the chart, heartbeats wake agents for assigned work, "a mention alone does not assign work". [F] Relevance Workforce: visual canvas, AI-decided handoff vs mandatory next-step edges, sub-agents as callable tools with structured I/O, parallel merge. [S] Salesforce: Agent Router → subagents with transitions. [S] Letta: shared memory blocks as coordination primitive (blackboard). [S]

**ClawCompany implication:** Model teamwork on a *company*, not a chat room: tasks with single owner (checkout lock), explicit handoffs with a structured brief (objective, output format, constraints, context links), shared team blackboard (`team/` memory, read-mostly), reviewer agents with clean context for anything customer-facing or financial, manager agents that decompose and synthesize but don't co-edit. Support A2A cards so external/partner agents can be "contractors". Budget teams explicitly (15× token multiplier).

---

## 8. Evaluation & lifecycle of agent employees

### 8.1 Evals
- **Anthropic "Demystifying evals" (Jan 2026)**: start with **20–50 tasks from real failures**; graders = code (state checks), LLM (rubric), human (calibrates others); separate **capability evals** (low pass rate, hill to climb) from **regression evals** (~100%, graduate saturated capability tasks into regression); **pass@k vs pass^k** — 75% per-trial ⇒ pass^3 ≈ 42%; customer-facing agents need pass^k. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents [S]
- **τ-bench (Sierra)**: simulated user + domain tools + **policy document**; grade by **end-state DB comparison** plus pass^k consistency; τ²/τ³ add telecom, banking, voice. https://arxiv.org/abs/2406.12045 , https://github.com/sierra-research/tau2-bench [S]
- **Anthropic research eval**: single LLM-judge rubric (factual accuracy, citation accuracy, completeness, source quality, tool efficiency) 0–1 + pass/fail most consistent; human testers found SEO-content-farm bias automation missed; end-state evaluation for state-mutating agents. [F]
- Relevance "Invent" auto-writes 24 evals from past runs; Lindy, Paperclip ship evals & saved test runs; Salesforce Plan Tracer previews reasoning per test prompt; Sierra simulations to avoid regressions. [S/F]

### 8.2 Lifecycle (HR analogy) — proposed, synthesized from sources
| Stage | Mechanism | Sources |
|---|---|---|
| Hiring (spec) | Job description = role, goal, KPIs, scope/out-of-scope topics, tools, autonomy level, budget, reports-to | CrewAI, Agentforce topics/instructions/actions, Paperclip org chart |
| Onboarding | BOOTSTRAP ritual, company KB + SOP skills loaded, USER.md for each human it serves, intro to team | OpenClaw BOOTSTRAP.md, Artisan KB, Relevance knowledge |
| Training | Book/SOP → KB + distilled skills + exam | §3.3 |
| Probation | Shadow mode / approval-required at L2–L3; capability + regression evals; pass^k threshold; "Gaps" log | Anthropic evals, τ-bench, Artisan Gaps |
| Performance review | Scorecard: task success rate, pass^k on regression suite, human override/approval-rejection rate, escalation correctness, CSAT, cost per task, latency, policy violations, memory/skill hygiene | Paperclip "performance reviews for agents", Copilot Studio autonomous agent health analytics |
| Promotion | Raise autonomy per action class; give new tools/budget | Feng et al. L1–L5 |
| Change management | Every SOUL/skill/model change = versioned release; regression evals gate; rainbow deploy; rollback | Paperclip revisioned config, Anthropic rainbow deploys, OpenClaw skill versions |
| Offboarding | Export memory/skills (portable templates with secret scrubbing), revoke credentials/identity, archive | Paperclip company portability, Entra Agent ID lifecycle |

### 8.3 What competitors let users customize (snapshot)
| Product | Customizable about an agent | Source |
|---|---|---|
| **Paperclip** (OSS, MIT, ~102k★) | BYO agent runtime (OpenClaw, Claude Code, Codex…), role/title/reporting line, permissions, budgets, skills (Skill Studio, versions, saved tests), routines (cron/webhook), connection permissions Allowed/Ask/Off, approval stages, goals; memory/knowledge still "in progress" on roadmap | https://github.com/paperclipai/paperclip [F] |
| **Relevance AI** | Prompt/instructions, tools, knowledge, per-tool approval mode (auto/approval/agent-decides/max runs), escalation paths, triggers, workforce canvas with handoff edges, evals auto-generated, model choice/BYOK | https://relevanceai.com/docs/... [S] |
| **Lindy** | Natural-language instructions, triggers, integrations, "personality and core directives" context, memories (pre-configured / user-defined / agent-updated), knowledge base, skills with Personal>Team>System layering, model choice, evals | https://docs.lindy.ai/fundamentals/lindy-101/memory , https://docs.lindy.ai/teammate/skills [S] |
| **Sierra** | Agent SDK (journeys as code), goals & guardrails, composable skills, per-workflow determinism "tuning", simulations, supervisors, omnichannel incl. voice | https://sierra.ai/product/agent-sdk [S] |
| **Salesforce Agentforce** | Role, topics/subagents (classification description + scope), natural-language + deterministic Agent Script instructions, actions (Flows/Apex/MuleSoft/prompt templates), guardrails, human handoff, Plan Tracer testing | https://www.salesforce.com/agentforce/guide/ [S] |
| **Microsoft Copilot Studio** | Instructions (role, tone, decline rules, escalation), knowledge sources, tools/connectors/MCP, topics, autonomous event triggers with payload instructions, data policies, Entra Agent ID governance, analytics | https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-instructions [S] |
| **Artisan (Ava)** | Name, tone, working hours, goals, ICP, knowledge base (with Gaps tab), human-in-the-loop controls; otherwise opinionated/fixed workflow | https://www.artisan.co/ai-sales-agent , https://support.artisan.co/knowledge-base , https://aisdr.shop/compare/lindy-vs-ora-vs-ava [S] |

Note: an existing workspace file (`work/product-research.md`) states Paperclip.inc (third-party €10/mo host) closed on 2 Oct 2026; the paperclip.inc homepage still advertised €10/month in a search snippet. I did not verify the closure.

---

## 9. Recommended agent anatomy for ClawCompany

### 9.1 Components (human metaphor → mechanism → where it lives)
| Organ | Mechanism | OpenClaw substrate | ClawCompany adds |
|---|---|---|---|
| **Identity / personality** | Role-goal-backstory + voice rules + Big-Five style hints + VN pronoun scheme | `IDENTITY.md`, `SOUL.md` | Persona form, versioning, persona regression tests |
| **Job / operating rules** | Scope, KPIs, procedures, effort rules, escalation | `AGENTS.md`, standing orders | Job-description template per role (Sales, CSKH, Kế toán…) |
| **Working memory** | Context window + plan/todo file + compaction + tool-result clearing | sessions, compaction, memory flush | Token budget per run |
| **Short-term / episodic** | Daily notes, transcripts, run logs | `memory/YYYY-MM-DD.md`, session index | Searchable timeline UI |
| **Long-term personal (agent)** | Curated facts/decisions/lessons | `MEMORY.md` via Dreaming | Review/forget UI |
| **People memory** | Directives about each human served | `USER.md` (supersede in place) | Per-person profile, PII tagging |
| **Work / org memory** | Policies, glossary, product catalog, customers | — | Scoped shared files (`org/`, `team/`, `project/`) pushed read-only; optional Graphiti temporal KG |
| **Knowledge (books/docs/courses)** | RAG KB with citations | memory search / plugins | Ingestion + KB scoping + exam generation |
| **Skills (procedural)** | SKILL.md folders, progressive disclosure | skills, ClawHub, Skill Workshop (learned) | Company skill registry, promotion pipeline, eval-gating |
| **Hands (tools)** | MCP connectors, browser, exec | tool policy, sandbox, elevated, MCP | Permission matrix, trifecta checks, spend caps, per-agent identity |
| **Head (reasoning)** | Model + fallback + advisor + thinking level | model config, thinkingDefault, failover | Routing presets per task type |
| **Rhythm (independent work)** | Heartbeat checklist, cron, event triggers, standing intents | heartbeat, cron, intents | Routines tied to goals; quiet hours |
| **Self-learning** | Reflection → learned skill / memory under gates | Self-learning, Dreaming | Nominate-to-company flow; dashboards |
| **Conscience (guardrails)** | Deterministic preconditions, supervisor agent, approvals | exec approvals, permission modes | Autonomy level per action, approval inbox (Zalo/mobile) |
| **Social (teamwork)** | Tasks w/ single owner, handoff briefs, reviewer, manager, A2A | sub-agents, agent send, A2A channel | Org chart, task board, team blackboard |
| **Career (lifecycle)** | Evals, scorecard, probation, promotion, rollback | — | HR-style lifecycle screens |

### 9.2 Data model sketch (control plane DB)
```
Agent(id, org_id, name, role_title, department_id, reports_to_agent|human_id,
      persona_id, job_desc_id, model_profile_id, autonomy_profile_id,
      budget_monthly_vnd, status[draft|probation|active|paused|retired],
      openclaw_agent_id, workspace_path, identity_credential_ref)

Persona(id, version, voice_rules[], formality, pronoun_scheme, big5{O,C,E,A,N},
        do_examples[], dont_examples[], channel_overrides{internal,customer})  -> compiles SOUL.md/IDENTITY.md

JobDescription(id, version, mission, goals[], kpis[{name,target,source}], in_scope[], out_of_scope[],
               escalation_rules[], effort_rules)  -> compiles AGENTS.md section

MemoryItem(id, scope[org|team|project|agent|person], scope_ref, owner_id,
           kind[fact|decision|lesson|preference|policy], content,
           provenance[owner|agent|untrusted|system], source_ref, sensitivity[normal|pii|secret-banned],
           importance 1-10, valid_from, valid_to, superseded_by, created_at, last_recalled_at, recall_count)
   (agent-private items stay in OpenClaw files; control plane mirrors/indexes and owns org/team/project scopes)

KnowledgeSource(id, scope, type[book|sop|course|url|drive], uri, ingest_status, chunk_count, exam_id)

Skill(id, name, scope[company|team|agent-learned], version, skill_md, files[], description,
      status[draft|nominated|evaluating|approved|archived], eval_suite_id, approved_by, parent_skill_id)

Tool/Connector(id, provider, flags{private_data, untrusted_content, can_exfiltrate})
Permission(agent_id, connector_id, action_class[read|draft|send|pay|delete], mode[allow|ask|off],
           daily_cap_vnd, autonomy_level L1-L5)

Task(id, goal_id, owner_agent_id (atomic checkout), status, brief{objective,output_format,constraints,context_refs},
     parent_task_id, reviewer_id, artifacts[], cost_tokens, cost_vnd)
Routine(id, agent_id, schedule|trigger, prompt, goal_id)

Approval(id, agent_id, action, args_snapshot, risk, requested_at, decided_by, decision, reason)
AuditEvent(id, agent_id, run_id, action, tool, args_hash, memory_versions[], skill_versions[], model, tokens, vnd, outcome)

EvalSuite(id, type[capability|regression|persona|policy], tasks[], graders[code|llm|human], k)
EvalRun(id, suite_id, agent_version_hash, pass_at_1, pass_pow_k, scores{}, passed)
Scorecard(agent_id, period, task_success, pass_pow_k, override_rate, escalation_accuracy, csat, cost_per_task,
          policy_violations, gaps_logged, autonomy_changes[])
AgentVersion(agent_id, hash(persona_v, jobdesc_v, skills_v[], model_profile, permissions), released_at, rollback_of)
```

### 9.3 Build order (pragmatic)
1. Persona + job-description compilers → OpenClaw workspace files; permission matrix → tool policy/sandbox. (Mostly config; high value.)
2. Scoped shared memory (org/team/project) + memory review/forget UI in Vietnamese.
3. Approval inbox + audit log + budgets (reuse Paperclip ideas or integrate Paperclip as backend — note it already has OpenClaw adapter).
4. Knowledge ingestion + exam-based probation + Gaps log.
5. Company skill registry with eval-gated promotion of learned skills.
6. Scorecards and autonomy promotion; reviewer/manager multi-agent patterns; A2A.

### 9.4 Open questions / not established here
- Vietnam-specific legal constraints (PDPL Decree 13/2023 on personal data, e-invoice Decree 123) for agent memory retention — not researched.
- Quality of Vietnamese in persona/pronoun consistency across models — no benchmark found; must be tested in-house.
- Whether OpenClaw's scoped/shared memory across multiple agents exists natively beyond workspace sharing (docs mention shared workspaces and a removed cross-agent QMD search path) — needs a hands-on check.
- Vendor memory benchmark claims (Mem0/Zep/Letta) are not independently verified.
