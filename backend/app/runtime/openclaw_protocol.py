"""Facts about the real OpenClaw Gateway protocol.

Everything in this module was taken from the upstream project
(https://github.com/openclaw/openclaw, docs.openclaw.ai) rather than invented
for ClawCompany. Keeping the constants in one place means that when OpenClaw
changes its contract, one file has to be reviewed instead of the whole backend.

The most important upstream facts, because they shape the adapter:

* The Gateway is a WebSocket control plane on port 18789 by default. Clients
  declare a **role** and **scopes** in a connect frame during handshake.
* There is no ``agents.create`` / ``agents.run`` RPC pair. Agents are config
  entries (``agents.entries.<id>``) created by the operator via
  ``openclaw agents add``. Work is driven through **sessions**:
  ``sessions.create`` then ``chat.send``, aborted with ``chat.abort`` /
  ``sessions.abort``, observed with ``sessions.messages.subscribe``.
* The canonical main session key for an agent is ``agent:<agentId>:main``.
* The same port also serves ``POST /tools/invoke`` for invoking a single tool
  without a full agent turn. Bearer auth there is **full operator access**,
  and a hard deny list blocks the RCE-shaped tools.
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
    "agents.create": {
        "upstream": None,
        "note": "OpenClaw agents are config entries (agents.entries.<id>), created by the operator with `openclaw agents add`. There is no create-agent RPC, so ClawCompany registers an agent seat by binding to an existing agentId.",
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
)
