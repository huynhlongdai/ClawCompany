"""Facts about the real OpenClaw Gateway protocol.

Everything in this module was taken from the upstream project
(https://github.com/openclaw/openclaw, docs.openclaw.ai) rather than invented
for ClawCompany. Keeping the constants in one place means that when OpenClaw
changes its contract, one file has to be reviewed instead of the whole backend.

The most important upstream facts, because they shape the adapter:

* The Gateway is a WebSocket control plane on port 18789 by default. Clients
  declare a **role** and **scopes** in a connect frame during handshake.
* There is no ``agents.run`` RPC. Work is driven through **sessions**:
  ``sessions.create`` then ``chat.send``, aborted with ``chat.abort`` /
  ``sessions.abort``, observed with ``sessions.messages.subscribe``.
* ``agents.create`` **does exist** (see WP-1.1 below). Until 2026-09-16 this
  module claimed the opposite, which is why every ClawCompany provisioning
  path assumed a human had to run ``openclaw agents add`` by hand.
* The canonical main session key for an agent is ``agent:<agentId>:main``.
* The same port also serves ``POST /tools/invoke`` for invoking a single tool
  without a full agent turn. Bearer auth there is **full operator access**,
  and a hard deny list blocks the RCE-shaped tools.

WP-1.1 (2026-09-16) — correcting a false claim that shaped the whole backend
-----------------------------------------------------------------------------

This module used to state: *"There is no ``agents.create`` / ``agents.run`` RPC
pair."* The second half is right; the first half is **wrong** for OpenClaw
2026.9.4, and it cost the project a feature. Verified against the docs shipped
inside the package (``openclaw@2026.9.4``, ``docs/gateway/protocol/
rpc-talk-config-and-agents.md``, section "Agent and workspace helpers"):

    "``agents.create``, ``agents.update``, and ``agents.delete`` manage agent
    records and workspace wiring."

So a seat can be created, reconfigured and retired **over the wire**. Combined
with ``config.patch`` and ``agents.files.set``, everything an operator would
otherwise hand-edit in ``openclaw.json`` is reachable from a ClawCompany
screen. Each constant below names the doc file that proves it exists; the probe
log in ``_reports/native-probe-agents.log`` shows the ones we called for real.
"""

from __future__ import annotations

# --- Roles and scopes declared at handshake -------------------------------

# --- Client identity at handshake ----------------------------------------

# ``client.id`` là enum đóng: GATEWAY_CLIENT_IDS trong
# packages/gateway-protocol/src/client-info.ts. Một chuỗi tự đặt bị từ chối ở
# tầng validate, nên ClawCompany khai mình là "gateway-client" -- lớp client
# dành cho backend điều khiển -- và để tên riêng ở client.displayName.
CLIENT_ID = "gateway-client"
CLIENT_MODE = "backend"   # GATEWAY_CLIENT_MODES.BACKEND

ROLE_OPERATOR = "operator"
ROLE_NODE = "node"

OPERATOR_SCOPES = (
    "operator.admin",
    "operator.approvals",
    "operator.pairing",
    "operator.questions",   # v35.1: có trong upstream, hằng số cũ bỏ sót
    "operator.read",
    "operator.talk",        # v35.1: có trong upstream, hằng số cũ bỏ sót
    "operator.talk.secrets",
    "operator.write",
)

# ClawCompany only needs to read state and drive sessions. We deliberately do
# not ask for admin/pairing/secrets scopes: a company backend should not be
# able to reconfigure the operator's gateway.
COMPANY_SCOPES = ("operator.read", "operator.write")

# v21: added to the handshake only when the operator opts in, because it lets
# this backend answer approval prompts on their behalf.
SCOPE_APPROVALS = "operator.approvals"

SCOPE_READ = "operator.read"
SCOPE_WRITE = "operator.write"
# WP-1.1: config writes and agent lifecycle need admin. COMPANY_SCOPES stays
# narrow on purpose, so a deployment that wants the configuration screens has
# to opt in — see CONFIG_SCOPES and settings.openclaw_admin_scope.
SCOPE_ADMIN = "operator.admin"

# Scopes required by the configuration/provisioning surface (WP-1.2).
CONFIG_SCOPES = (SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN)


# --- RPC methods we actually call ----------------------------------------

M_STATUS = "status"
M_SESSIONS_LIST = "sessions.list"
M_SESSIONS_CREATE = "sessions.create"
M_SESSIONS_DESCRIBE = "sessions.describe"
M_SESSIONS_ABORT = "sessions.abort"
M_SESSIONS_MESSAGES_SUBSCRIBE = "sessions.messages.subscribe"
M_SESSIONS_MESSAGES_UNSUBSCRIBE = "sessions.messages.unsubscribe"
M_CHAT_SEND = "chat.send"
M_CHAT_ABORT = "chat.abort"
M_CHAT_HISTORY = "chat.history"


# --- WP-1.1: the control surface we had never opened ----------------------
#
# Source for this whole block: docs/gateway/protocol/rpc-talk-config-and-agents.md
# ("Agent and workspace helpers" + the config bullets),
# docs/gateway/configuration/config-rpc.md,
# docs/gateway/protocol/operator-methods.md,
# docs/gateway/protocol/rpc-system-and-channels.md.

# Agent records. "agents.create, agents.update, and agents.delete manage agent
# records and workspace wiring."
M_AGENTS_LIST = "agents.list"
M_AGENTS_CREATE = "agents.create"
M_AGENTS_UPDATE = "agents.update"
M_AGENTS_DELETE = "agents.delete"

# Bootstrap workspace files — IDENTITY.md / SOUL.md / AGENTS.md / USER.md /
# MEMORY.md. get/set return the content `hash` (SHA-256 hex of the on-disk
# bytes); set takes an optional `expectedHash` for compare-and-set.
M_AGENTS_FILES_LIST = "agents.files.list"
M_AGENTS_FILES_GET = "agents.files.get"
M_AGENTS_FILES_SET = "agents.files.set"

# Read-only, paginated workspace browsing (operator.read). Workspace-relative
# paths only; symlink/hardlink escapes rejected; no write methods exist here.
# This is how ClawCompany reads DREAMS.md and memory/YYYY-MM-DD.md.
M_AGENTS_WORKSPACE_LIST = "agents.workspace.list"
M_AGENTS_WORKSPACE_GET = "agents.workspace.get"

M_AGENT_IDENTITY_GET = "agent.identity.get"
M_AGENT_WAIT = "agent.wait"

# Config plane.
M_CONFIG_GET = "config.get"
M_CONFIG_SET = "config.set"
M_CONFIG_PATCH = "config.patch"
M_CONFIG_APPLY = "config.apply"
M_CONFIG_SCHEMA = "config.schema"
M_CONFIG_SCHEMA_LOOKUP = "config.schema.lookup"

# Catalogues and money.
M_MODELS_LIST = "models.list"
M_USAGE_COST = "usage.cost"
M_SESSIONS_USAGE = "sessions.usage"
M_TOOLS_CATALOG = "tools.catalog"
M_TOOLS_EFFECTIVE = "tools.effective"
M_SKILLS_STATUS = "skills.status"

# Scope needed per method, so a caller can fail fast with a real reason instead
# of reading a bare authorization error. Only methods whose scope the docs state
# explicitly are listed; absence here means "not documented", not "no scope".
METHOD_SCOPES = {
    M_AGENTS_WORKSPACE_LIST: SCOPE_READ,
    M_AGENTS_WORKSPACE_GET: SCOPE_READ,
    M_TOOLS_CATALOG: SCOPE_READ,
    M_TOOLS_EFFECTIVE: SCOPE_READ,
    M_SKILLS_STATUS: SCOPE_READ,
}
# exec.approval.resolve is added below, where its constant is defined.

# Control-plane writes are rate limited: "30 requests per 60 seconds, per
# method, per deviceId+clientIp" (config-rpc.md). A UI that patches on every
# keystroke will be throttled, so the service coalesces instead.
CONTROL_PLANE_WRITE_METHODS = frozenset({M_CONFIG_PATCH, M_CONFIG_APPLY, "update.run"})
CONTROL_PLANE_RATE_LIMIT = (30, 60)   # (requests, seconds)

# config.schema.lookup returns this for the requested path. "reloadKind is one
# of restart, hot, or none (src/config/schema.ts)".
RELOAD_RESTART = "restart"
RELOAD_HOT = "hot"
RELOAD_NONE = "none"
RELOAD_KINDS = frozenset({RELOAD_RESTART, RELOAD_HOT, RELOAD_NONE})

# agents.files.set refuses a stale write with INVALID_REQUEST whose
# details.type is this, carrying details.currentHash to rebase against.
ERR_AGENT_FILE_CONFLICT = "agent_file_conflict"

# The bootstrap files an agent's identity is made of, in the order a reviewer
# should read them. Đo được trên gateway 2026.9.4 (WP-2.1), không chỉ đọc docs.
AGENT_BOOTSTRAP_FILES = ("IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md", "MEMORY.md")

# WP-2.1: `agents.files.list` và tập file `agents.files.get` đọc được **không
# trùng nhau** trên cùng một gateway. Đã đo:
#
# * list trả 5 mục: AGENTS.md, SOUL.md, USER.md, BOOTSTRAP.md, MEMORY.md
# * nhưng `get` với IDENTITY.md vẫn trả nội dung thật (1722 byte)
# * còn DREAMS.md bị từ chối: `unsupported file "DREAMS.md"`
#
# Nên: đừng lấy `files.list` làm danh sách file có thể sửa — nó bỏ sót
# IDENTITY.md. Và đừng mong đọc DREAMS.md qua namespace này; nó thuộc
# `agents.workspace.get` (WP-2.4).
AGENT_FILES_LIST_OMITS = ("IDENTITY.md",)
AGENT_FILES_UNSUPPORTED = ("DREAMS.md",)

# Đường dẫn vượt ra ngoài workspace bị chặn: `agents.files.get` với
# "../../etc/passwd" trả `unsupported file`. Tức namespace này là allowlist
# theo tên, không phải resolve đường dẫn — một chốt thật, đã kiểm.
AGENT_FILES_PATH_ESCAPE_BLOCKED = True

# Giới hạn của `expectedHash`: đúng 64 ký tự hex (SHA-256), theo
# AgentsFilesSetParamsSchema đọc từ dist của package.
AGENT_FILE_HASH_LENGTH = 64

# Budgets from docs/gateway/config-agents/workspace-and-bootstrap.md. Exceeding
# them truncates the file **silently** inside the prompt, so the UI must count
# characters rather than discover the loss later.
BOOTSTRAP_MAX_CHARS = 20_000          # agents.defaults.bootstrapMaxChars
BOOTSTRAP_TOTAL_MAX_CHARS = 60_000    # agents.defaults.bootstrapTotalMaxChars
USER_MD_MAX_CHARS = 4_000             # USER.md has its own, smaller budget


# --- Event families we consume -------------------------------------------

E_SESSION_MESSAGE = "session.message"
E_SESSION_OPERATION = "session.operation"
E_SESSION_TOOL = "session.tool"
E_SESSIONS_CHANGED = "sessions.changed"
E_CHAT = "chat"
# Upstream asks the operator for permission through these; v20 turns them into
# rows in the company approval queue instead of letting them expire unseen.
E_SESSION_APPROVAL = "session.approval"
E_EXEC_APPROVAL_REQUESTED = "exec.approval.requested"
E_EXEC_APPROVAL_RESOLVED = "exec.approval.resolved"
APPROVAL_EVENTS = frozenset({E_SESSION_APPROVAL, E_EXEC_APPROVAL_REQUESTED, E_EXEC_APPROVAL_RESOLVED})

# v23 — verified against the upstream gateway docs, not inferred.
# "Operator clients resolve by calling exec.approval.resolve (requires
# operator.approvals)", and a client should call exec.approval.list on connect
# to backfill requests that predate the connection.
M_EXEC_APPROVAL_RESOLVE = "exec.approval.resolve"
M_EXEC_APPROVAL_LIST = "exec.approval.list"

METHOD_SCOPES[M_EXEC_APPROVAL_RESOLVE] = SCOPE_APPROVALS

# The upstream decision vocabulary is three-valued, not a boolean.
# allow-always mints a standing grant tied to the command's exact argv and cwd,
# so it is a materially different act from allowing one run.
D_ALLOW_ONCE = "allow-once"
D_ALLOW_ALWAYS = "allow-always"
D_DENY = "deny"
APPROVAL_DECISIONS = frozenset({D_ALLOW_ONCE, D_ALLOW_ALWAYS, D_DENY})

# Upstream chat events carry a coarse lifecycle state rather than our old
# invented "run.completed" event names.
TERMINAL_STATES = frozenset({"complete", "completed", "error", "aborted", "cancelled", "canceled"})
ERROR_STATES = frozenset({"error"})


# --- Tool policy ----------------------------------------------------------

# Gateway HTTP applies this deny list by default even when session policy would
# allow the tool. We mirror it so ClawCompany fails fast with a clear reason
# instead of surfacing a bare 404 from the gateway.
HTTP_DENIED_TOOLS = frozenset(
    {
        "exec",
        "spawn",
        "shell",
        "fs_write",
        "fs_delete",
        "fs_move",
        "apply_patch",
        "sessions_spawn",
        "sessions_send",
        "cron",
        "gateway",
        "nodes",
    }
)

# Owner-only even outside the deny list.
OWNER_ONLY_TOOLS = frozenset({"cron", "gateway", "nodes"})


# --- Session keys ---------------------------------------------------------


def main_session_key(agent_id: str) -> str:
    """The agent's canonical main session (``agent:<agentId>:main``)."""
    return f"agent:{agent_id}:main"


def task_session_key(agent_id: str, task_id: int | str) -> str:
    """A dedicated session per company task.

    Using one session per task keeps task transcripts separate instead of
    dumping every company task into the agent's main conversation, which is
    what the operator uses from chat channels.
    """
    return f"agent:{agent_id}:company-task-{task_id}"


def agent_id_from_session_key(session_key: str) -> str | None:
    parts = (session_key or "").split(":")
    if len(parts) >= 3 and parts[0] == "agent":
        return parts[1]
    return None


# --- Compatibility matrix -------------------------------------------------

# Legacy adapter method name -> real upstream contract. Exposed through the API
# so an operator can see exactly where ClawCompany's older assumptions were
# wrong, instead of discovering it at runtime against a live gateway.
LEGACY_CONTRACT_MAP = {
    # WP-1.1 correction. This entry used to say upstream=None ("there is no
    # create-agent RPC"), which was wrong and made seat provisioning a manual
    # CLI step for the operator. The method exists; what does not exist is
    # `agents.run`.
    "agents.create": {
        "upstream": M_AGENTS_CREATE,
        "note": "Exists upstream: agents.create/update/delete 'manage agent records and workspace wiring' (docs/gateway/protocol/rpc-talk-config-and-agents.md). Creating a seat still writes a config entry (agents.entries.<id>) — the difference is that the Gateway does the write, so ClawCompany no longer needs an operator to run `openclaw agents add` by hand.",
        "corrected_on": "2026-09-16",
        "previous_claim": "no upstream equivalent",
    },
    "agents.run": {
        "upstream": f"{M_SESSIONS_CREATE} + {M_CHAT_SEND}",
        "note": "Work is driven through sessions, not a one-shot run call.",
    },
    "runs.cancel": {
        "upstream": f"{M_CHAT_ABORT} / {M_SESSIONS_ABORT}",
        "note": "Abort is scoped by session key plus optional runId.",
    },
    "gateway.status": {
        "upstream": M_STATUS,
        "note": "System and identity family.",
    },
    "runs.subscribe": {
        "upstream": M_SESSIONS_MESSAGES_SUBSCRIBE,
        "note": "Subscription is per session, not per run; filter events by runId client-side.",
    },
}

PROTOCOL_NOTES = (
    "Gateway WS + HTTP are multiplexed on one port (default 18789).",
    "Handshake declares role and scopes; ClawCompany connects as operator with operator.read + operator.write.",
    "Bearer auth on /tools/invoke is full operator access for the whole gateway, so the token must never leave the ClawCompany backend.",
    "Session keys are agent-qualified: agent:<agentId>:main is the canonical main session.",
    "Multi-agent isolation is per agentId: separate workspace, agentDir and session store.",
    "Cross-agent delegation is governed upstream by tools.agentToAgent and agents.<id>.subagents.allowAgents.",
    "Agent records, bootstrap files and config are writable over the wire: agents.create/update/delete, agents.files.set (expectedHash compare-and-set), config.patch (baseHash + replacePaths). No file editing on the host is required.",
    "config.schema.lookup reports reloadKind (restart|hot|none) per path, so a UI can warn about a restart before the operator saves rather than after.",
    "Control-plane writes (config.patch, config.apply, update.run) are rate limited to 30 per 60s per method per deviceId+clientIp.",
)

# Where the docs disagree with each other. Recording it here because picking the
# wrong one silently destroys data.
DOC_CONFLICTS = (
    {
        "topic": "replacePaths wildcards",
        "a": "rpc-talk-config-and-agents.md: 'nested arrays under array entries use [] paths such as agents.entries.*.skills'",
        "b": "config-rpc.md: 'Use exact record keys, such as agents.entries.main.skills. ... Parent paths and * wildcards do not authorize descendant arrays.'",
        "resolution": "Follow (b), the stricter and more specific text: emit exact record keys. A wildcard that the gateway does not honour means the write is rejected — which is the safe failure — but believing (a) would make a UI promise an update it cannot perform.",
    },
)
