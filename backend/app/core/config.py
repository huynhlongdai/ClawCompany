from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "ClawCompany API"
    env: str = "development"
    database_url: str = "sqlite:///./clawcompany.db"
    # Cả hai origin: trình duyệt coi http://localhost:3000 và
    # http://127.0.0.1:3000 là KHÁC nhau, nên chỉ khai một cái thì mở UI bằng
    # địa chỉ còn lại sẽ bị chặn CORS mà không có thông báo nào ở phía server.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    app_version: str = "1.26.0"
    openclaw_mode: str = "mock"  # mock | native | gateway (legacy guessed contract)
    openclaw_gateway_ws: str = "ws://127.0.0.1:18789"
    openclaw_gateway_http: str = ""  # defaults to the ws url with an http scheme
    openclaw_api_token: str = ""
    openclaw_timeout_seconds: int = 30
    # v19 native OpenClaw alignment
    openclaw_client_name: str = "clawcompany"
    openclaw_protocol_version: int = 4
    openclaw_auto_dispatch: bool = False  # start an OpenClaw run when a task moves to in_progress
    # v21: re-attach session followers on boot for tasks still in progress.
    openclaw_resume_on_boot: bool = False
    # v21: ask the gateway for operator.approvals so approvals can be answered
    # from ClawCompany. Off by default: it widens what this backend may do.
    openclaw_request_approvals_scope: bool = False
    # v23: verified against the upstream gateway docs ("Operator clients resolve
    # by calling exec.approval.resolve, requires operator.approvals"). This is
    # no longer a guess, so it ships with a default. Override it if your gateway
    # version documents a different name.
    # v21 note kept for history: the RPC used to answer an approval prompt. Left empty on purpose —
    # we will not guess a method name again (that was the v19 bug). Set it to
    # the method your gateway version documents, e.g. "session.approval.respond".
    openclaw_approval_reply_method: str = "exec.approval.resolve"
    # v23: upstream decisions are three-valued, not a boolean. "allow-always"
    # mints a standing grant tied to the exact argv and cwd, so ClawCompany
    # never sends it unless a human explicitly picks it.
    openclaw_approval_allow_always_enabled: bool = False
    # v22: seconds between sweeps that take over sessions no worker is
    # following. 0 disables the sweep; followers are then only re-attached by
    # boot resume or an explicit API call.
    openclaw_claim_sweep_seconds: int = 0

    # v25: reconcile (report the gap, pull pending approvals) whenever a
    # follower attaches to a session. On by default because it is a no-op
    # unless the approvals scope is granted and the runtime supports listing.
    openclaw_auto_reconcile: bool = True
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    app_base_url: str = "http://localhost:8000"
    vector_backend: str = "pgvector"
    embedding_provider: str = "hash384"
    embedding_dim: int = 384
    openclaw_rpc_create_agent: str = "agents.create"
    openclaw_rpc_run_agent: str = "agents.run"
    openclaw_rpc_cancel_run: str = "runs.cancel"
    openclaw_rpc_gateway_status: str = "gateway.status"
    openclaw_rpc_subscribe_run: str = "runs.subscribe"
    openclaw_event_run_id_key: str = "runId"
    openclaw_event_type_key: str = "type"
    customer_portal_token_minutes: int = 720
    artifact_workspace_root: str = "./workspace-artifacts"
    repository_workspace_root: str = "./workspace-repositories"
    repository_test_allowed_executables: str = "python,python3,pytest,npm,pnpm,yarn,node"
    repository_git_timeout_seconds: int = 120
    event_webhook_allowed_hosts: str = "localhost,127.0.0.1"
    event_webhook_timeout_seconds: int = 10
    dev_workspace_root: str = "./workspace-dev"
    deployment_workspace_root: str = "./workspace-deployments"
    sandbox_docker_enabled: bool = False
    sandbox_docker_user: str = "65532:65532"
    sandbox_default_provider: str = "mock"
    sandbox_microvm_gateway_url: str = ""
    engineering_evidence_max_files: int = 5000
    # v14 distributed execution / workload identity
    workload_identity_issuer: str = "http://localhost:8000/api/v14/workload-identity"
    workload_identity_algorithm: str = "HS256"  # development fallback; production should use RS256
    workload_identity_key_id: str = "clawcompany-workload-v14"
    workload_identity_dev_secret: str = "change-workload-identity-secret-in-production"
    workload_identity_private_key_path: str = ""
    workload_identity_public_key_path: str = ""
    traffic_router_config_root: str = "./workspace-traffic"
    traffic_router_allow_external_path: bool = False
    traffic_router_kubernetes_enabled: bool = False
    traffic_router_kubectl_executable: str = "kubectl"
    # v15 production trust / telemetry / secrets federation / paging
    runner_mtls_required: bool = False
    runner_mtls_proxy_shared_secret: str = ""
    telemetry_export_allowed_hosts: str = "localhost,127.0.0.1"
    telemetry_export_timeout_seconds: int = 10
    secret_provider_allowed_hosts: str = "localhost,127.0.0.1"
    secret_provider_timeout_seconds: int = 10
    incident_paging_allowed_hosts: str = "localhost,127.0.0.1"
    incident_paging_timeout_seconds: int = 10
    scheduler_node_key: str = "control-plane-v15"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()