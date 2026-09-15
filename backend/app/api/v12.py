import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.authz import Principal, ROLE_ORDER, enforce_org, require_human, require_role, require_scope
from app.core.tenancy import active_org, ensure_agent, ensure_company, ensure_member, ensure_project
from app.db.session import get_db
from app.models import (
    Approval, Artifact, ArtifactHandoff, DeliveryAutomationRule, DeliveryRun, Deployment,
    DeploymentEnvironment, DeploymentRollback, DevWorkspace, PreviewEnvironment, Release,
    ReleaseArtifact, Repository, RepositoryMergeRequest, SandboxProfile, SandboxRun,
    SecretGrant, SecretReference,
)
from app.schemas.v12 import (
    DeliveryAutomationRuleCreate, DeployRequest, DeploymentEnvironmentCreate, ReleaseCreate,
    RollbackDeploymentRequest, SandboxProfileCreate, SandboxRunCreate, SecretGrantCreate,
    SecretReferenceCreate, WorkspaceCreate,
)
from app.services.dev_cloud import WorkspaceError, destroy_workspace, provision_workspace
from app.services.delivery_automation import auto_delivery_from_handoff
from app.services.releases import ReleaseError, create_preview, deploy_release, deployment_gate, rollback_environment
from app.services.sandbox_runner import SandboxError, execute_sandbox, profile_policy
from app.services.secret_store import secret_metadata

router = APIRouter(prefix="/v12", tags=["v12-secure-dev-cloud"])


def _repo(db: Session, repo_id: int, principal: Principal) -> Repository:
    item = db.get(Repository, repo_id)
    if not item: raise HTTPException(404, "Repository not found")
    enforce_org(item.organization_id, principal); return item


def _workspace(db: Session, workspace_id: int, principal: Principal) -> DevWorkspace:
    item = db.get(DevWorkspace, workspace_id)
    if not item: raise HTTPException(404, "Workspace not found")
    enforce_org(item.organization_id, principal); return item


def _profile(db: Session, profile_id: int, principal: Principal) -> SandboxProfile:
    item = db.get(SandboxProfile, profile_id)
    if not item: raise HTTPException(404, "Sandbox profile not found")
    enforce_org(item.organization_id, principal); return item


def _release(db: Session, release_id: int, principal: Principal) -> Release:
    item = db.get(Release, release_id)
    if not item: raise HTTPException(404, "Release not found")
    enforce_org(item.organization_id, principal); return item


def _environment(db: Session, environment_id: int, principal: Principal) -> DeploymentEnvironment:
    item = db.get(DeploymentEnvironment, environment_id)
    if not item: raise HTTPException(404, "Deployment environment not found")
    enforce_org(item.organization_id, principal); return item


@router.get("/dev-cloud-dashboard")
def dashboard(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    org_id = active_org(principal)
    workspaces = db.query(DevWorkspace).filter(DevWorkspace.organization_id == org_id).order_by(DevWorkspace.id.desc()).limit(8).all()
    runs = db.query(SandboxRun).filter(SandboxRun.organization_id == org_id).order_by(SandboxRun.id.desc()).limit(8).all()
    releases = db.query(Release).filter(Release.organization_id == org_id).order_by(Release.id.desc()).limit(8).all()
    deployments = db.query(Deployment).filter(Deployment.organization_id == org_id).order_by(Deployment.id.desc()).limit(8).all()
    previews = db.query(PreviewEnvironment).filter(PreviewEnvironment.organization_id == org_id, PreviewEnvironment.status == "ready").order_by(PreviewEnvironment.id.desc()).limit(8).all()
    return {
        "metrics": {
            "active_workspaces": db.query(DevWorkspace).filter(DevWorkspace.organization_id == org_id, DevWorkspace.status == "ready").count(),
            "sandbox_running": db.query(SandboxRun).filter(SandboxRun.organization_id == org_id, SandboxRun.status.in_(["queued", "running"])).count(),
            "releases_ready": db.query(Release).filter(Release.organization_id == org_id, Release.status.in_(["ready", "released", "waiting_approval"])).count(),
            "deployments_24h": db.query(Deployment).filter(Deployment.organization_id == org_id, Deployment.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)).count(),
            "preview_environments": len(previews),
            "secret_references": db.query(SecretReference).filter(SecretReference.organization_id == org_id, SecretReference.is_active == True).count(),  # noqa: E712
        },
        "workspaces": workspaces, "sandbox_runs": runs, "releases": releases,
        "deployments": deployments, "previews": previews,
    }


@router.post("/workspaces")
def create_workspace(payload: WorkspaceCreate, principal: Principal = Depends(require_scope("company.devcloud:write")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.project_id is not None: ensure_project(db, payload.project_id, principal)
    if payload.repository_id is not None: _repo(db, payload.repository_id, principal)
    if payload.owner_member_id is not None: ensure_member(db, payload.owner_member_id, principal)
    if payload.owner_agent_id is not None: ensure_agent(db, payload.owner_agent_id, principal)
    if principal.auth_type == "api_key" and payload.owner_member_id not in {None, principal.member_id}:
        raise HTTPException(403, "API key cannot create a workspace for another member")
    item = DevWorkspace(
        organization_id=payload.organization_id, company_id=payload.company_id, project_id=payload.project_id,
        repository_id=payload.repository_id, owner_member_id=payload.owner_member_id or principal.member_id,
        owner_agent_id=payload.owner_agent_id, name=payload.name, workspace_key=payload.workspace_key,
        base_ref=payload.base_ref, status="provisioning",
    )
    db.add(item); db.commit(); db.refresh(item)
    try: return provision_workspace(db, item, payload.ttl_minutes)
    except WorkspaceError as exc:
        item.status="failed"; db.add(item); db.commit(); raise HTTPException(400, str(exc))


@router.get("/workspaces")
def list_workspaces(status: str | None = None, principal: Principal = Depends(require_scope("company.devcloud:read")), db: Session = Depends(get_db)):
    q = db.query(DevWorkspace).filter(DevWorkspace.organization_id == active_org(principal))
    if status: q=q.filter(DevWorkspace.status == status)
    return q.order_by(DevWorkspace.id.desc()).limit(250).all()


@router.post("/workspaces/{workspace_id}/destroy")
def destroy_workspace_endpoint(workspace_id: int, principal: Principal = Depends(require_scope("company.devcloud:write")), db: Session = Depends(get_db)):
    item=_workspace(db,workspace_id,principal)
    if principal.auth_type == "api_key" and item.owner_member_id != principal.member_id:
        raise HTTPException(403,"Workspace belongs to another identity")
    try: return destroy_workspace(db,item)
    except WorkspaceError as exc: raise HTTPException(400,str(exc))


@router.post("/sandbox-profiles")
def create_sandbox_profile(payload: SandboxProfileCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id,principal)
    if payload.company_id is not None: ensure_company(db,payload.company_id,principal)
    item=SandboxProfile(
        organization_id=payload.organization_id,company_id=payload.company_id,name=payload.name,image=payload.image,
        provider=payload.provider,cpu_limit=payload.cpu_limit,memory_mb=payload.memory_mb,pids_limit=payload.pids_limit,
        timeout_seconds=payload.timeout_seconds,network_mode=payload.network_mode,read_only_root=payload.read_only_root,
        allowed_commands_json=json.dumps(payload.allowed_commands),enabled=payload.enabled,
    )
    db.add(item);db.commit();db.refresh(item);return {"profile":item,"policy":profile_policy(item)}


@router.get("/sandbox-profiles")
def list_sandbox_profiles(principal: Principal = Depends(require_scope("company.devcloud:read")), db: Session = Depends(get_db)):
    items=db.query(SandboxProfile).filter(SandboxProfile.organization_id==active_org(principal)).order_by(SandboxProfile.id.desc()).all()
    return [{"profile":x,"policy":profile_policy(x)} for x in items]


@router.post("/sandbox-runs")
def create_sandbox_run(payload: SandboxRunCreate, enqueue: bool = Query(default=False), principal: Principal = Depends(require_scope("company.devcloud:execute")), db: Session = Depends(get_db)):
    ws=_workspace(db,payload.workspace_id,principal); profile=_profile(db,payload.profile_id,principal)
    if payload.initiated_by_member_id is not None: ensure_member(db,payload.initiated_by_member_id,principal)
    agent = ensure_agent(db,payload.initiated_by_agent_id,principal) if payload.initiated_by_agent_id is not None else None
    member_id=payload.initiated_by_member_id or principal.member_id
    if agent is not None and member_id is not None and agent.member_id != member_id:
        raise HTTPException(403,"Agent is not bound to the initiating member identity")
    if principal.auth_type=="api_key" and member_id != principal.member_id: raise HTTPException(403,"API key identity mismatch")
    item=SandboxRun(
        organization_id=ws.organization_id,workspace_id=ws.id,profile_id=profile.id,delivery_run_id=payload.delivery_run_id,
        initiated_by_member_id=member_id,initiated_by_agent_id=payload.initiated_by_agent_id,purpose=payload.purpose,
        command_json=json.dumps(payload.command),secret_grant_ids_json=json.dumps(payload.secret_grant_ids),status="queued",
    )
    db.add(item);db.commit();db.refresh(item)
    if enqueue:
        from app.tasks.dev_cloud import run_sandbox_task
        job=run_sandbox_task.delay(item.id); return {"sandbox_run":item,"queued":True,"celery_task_id":job.id}
    try: return execute_sandbox(db,item)
    except SandboxError as exc: raise HTTPException(400,str(exc))


@router.get("/sandbox-runs")
def list_sandbox_runs(status: str | None = None, principal: Principal = Depends(require_scope("company.devcloud:read")), db: Session = Depends(get_db)):
    q=db.query(SandboxRun).filter(SandboxRun.organization_id==active_org(principal))
    if status:q=q.filter(SandboxRun.status==status)
    return q.order_by(SandboxRun.id.desc()).limit(250).all()


@router.post("/secrets")
def create_secret_ref(payload: SecretReferenceCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id,principal)
    if payload.company_id is not None:ensure_company(db,payload.company_id,principal)
    item=SecretReference(**payload.model_dump(),is_active=True);db.add(item);db.commit();db.refresh(item);return secret_metadata(item)


@router.get("/secrets")
def list_secret_refs(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    items=db.query(SecretReference).filter(SecretReference.organization_id==active_org(principal)).order_by(SecretReference.id.desc()).all()
    return [secret_metadata(x) for x in items]


@router.post("/secret-grants")
def create_secret_grant(payload: SecretGrantCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    ref=db.get(SecretReference,payload.secret_reference_id)
    if not ref:raise HTTPException(404,"Secret reference not found")
    enforce_org(ref.organization_id,principal)
    if payload.member_id is not None:ensure_member(db,payload.member_id,principal)
    if payload.agent_id is not None:ensure_agent(db,payload.agent_id,principal)
    if payload.sandbox_profile_id is not None:_profile(db,payload.sandbox_profile_id,principal)
    if payload.environment_id is not None:_environment(db,payload.environment_id,principal)
    item=SecretGrant(organization_id=ref.organization_id,secret_reference_id=ref.id,member_id=payload.member_id,
        agent_id=payload.agent_id,sandbox_profile_id=payload.sandbox_profile_id,environment_id=payload.environment_id,
        mount_name=payload.mount_name,permissions_json=json.dumps(payload.permissions),expires_at=payload.expires_at,is_active=True)
    db.add(item);db.commit();db.refresh(item);return item


@router.get("/secret-grants")
def list_secret_grants(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return db.query(SecretGrant).filter(SecretGrant.organization_id==active_org(principal)).order_by(SecretGrant.id.desc()).limit(250).all()


@router.post("/environments")
def create_environment(payload: DeploymentEnvironmentCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id,principal);repo=_repo(db,payload.repository_id,principal)
    if payload.company_id is not None:ensure_company(db,payload.company_id,principal)
    if payload.project_id is not None:ensure_project(db,payload.project_id,principal)
    item=DeploymentEnvironment(**payload.model_dump(),is_active=True);db.add(item);db.commit();db.refresh(item);return item


@router.get("/environments")
def list_environments(principal: Principal = Depends(require_scope("company.deployments:read")), db: Session = Depends(get_db)):
    return db.query(DeploymentEnvironment).filter(DeploymentEnvironment.organization_id==active_org(principal)).order_by(DeploymentEnvironment.id.desc()).all()


@router.post("/releases")
def create_release(payload: ReleaseCreate, principal: Principal = Depends(require_scope("company.releases:write")), db: Session = Depends(get_db)):
    repo=_repo(db,payload.repository_id,principal)
    if payload.project_id is not None:ensure_project(db,payload.project_id,principal)
    commit_sha=payload.commit_sha
    if payload.merge_request_id is not None:
        mr=db.get(RepositoryMergeRequest,payload.merge_request_id)
        if not mr or mr.organization_id!=repo.organization_id or mr.repository_id!=repo.id:raise HTTPException(400,"Merge request does not match repository")
        if mr.status!="merged" or not mr.merge_commit_sha:raise HTTPException(409,"Merge request must be merged before creating a release")
        commit_sha=commit_sha or mr.merge_commit_sha
    if not commit_sha:raise HTTPException(400,"Release requires a commit SHA or merged merge request")
    # Verify the commit is present in the controlled checkout.
    if repo.local_path:
        import subprocess
        proc=subprocess.run(["git","cat-file","-e",f"{commit_sha}^{{commit}}"],cwd=repo.local_path,capture_output=True)
        if proc.returncode!=0:raise HTTPException(400,"Commit SHA is not present in repository checkout")
    item=Release(organization_id=repo.organization_id,repository_id=repo.id,project_id=payload.project_id or repo.project_id,
        delivery_run_id=payload.delivery_run_id,merge_request_id=payload.merge_request_id,created_by_member_id=principal.member_id,
        version=payload.version,commit_sha=commit_sha,status="ready",release_notes=payload.release_notes,manifest_json=json.dumps(payload.manifest))
    db.add(item);db.commit();db.refresh(item)
    for artifact_id in payload.artifact_ids:
        art=db.get(Artifact,artifact_id)
        if not art or art.organization_id!=repo.organization_id:raise HTTPException(400,f"Artifact {artifact_id} is not in organization")
        db.add(ReleaseArtifact(organization_id=repo.organization_id,release_id=item.id,artifact_id=art.id,purpose="source"))
    db.commit();return item


@router.get("/releases")
def list_releases(status: str | None = None, principal: Principal = Depends(require_scope("company.releases:read")), db: Session = Depends(get_db)):
    q=db.query(Release).filter(Release.organization_id==active_org(principal))
    if status:q=q.filter(Release.status==status)
    return q.order_by(Release.id.desc()).limit(250).all()


@router.get("/releases/{release_id}")
def release_detail(release_id:int,principal:Principal=Depends(require_scope("company.releases:read")),db:Session=Depends(get_db)):
    item=_release(db,release_id,principal)
    return {"release":item,"artifacts":db.query(ReleaseArtifact).filter(ReleaseArtifact.release_id==item.id).all(),
            "deployments":db.query(Deployment).filter(Deployment.release_id==item.id).order_by(Deployment.id.desc()).all()}


@router.get("/releases/{release_id}/gate")
def release_gate(release_id:int,environment_id:int,principal:Principal=Depends(require_scope("company.deployments:read")),db:Session=Depends(get_db)):
    release=_release(db,release_id,principal);env=_environment(db,environment_id,principal)
    try:return deployment_gate(db,release,env,principal.member_id)
    except ReleaseError as exc:raise HTTPException(409,str(exc))


@router.post("/releases/{release_id}/deploy")
def deploy_release_endpoint(release_id:int,payload:DeployRequest,enqueue:bool=Query(default=False),principal:Principal=Depends(require_scope("company.deployments:write")),db:Session=Depends(get_db)):
    if principal.auth_type == "jwt" and ROLE_ORDER.get(principal.role, -1) < ROLE_ORDER["manager"]:
        raise HTTPException(403,"Manager role required for deployment")
    release=_release(db,release_id,principal);env=_environment(db,payload.environment_id,principal)
    requester=payload.requested_by_member_id or principal.member_id
    if payload.requested_by_member_id is not None:ensure_member(db,payload.requested_by_member_id,principal)
    if principal.auth_type=="api_key" and requester!=principal.member_id:raise HTTPException(403,"API key identity mismatch")
    if enqueue:
        # Check gate before queuing so approval-required production deploys do not loop in workers.
        try:gate=deployment_gate(db,release,env,requester)
        except ReleaseError as exc:raise HTTPException(409,str(exc))
        if not gate["allowed"]:raise HTTPException(409,{"detail":"Deployment approval required","gate":gate})
        from app.tasks.dev_cloud import deploy_release_task
        job=deploy_release_task.delay(release.id,env.id,requester);return {"queued":True,"celery_task_id":job.id,"gate":gate}
    try:return deploy_release(db,release,env,requester)
    except ReleaseError as exc:raise HTTPException(409,str(exc))


@router.post("/releases/{release_id}/preview")
def create_preview_endpoint(release_id:int,environment_id:int,ttl_minutes:int=Query(default=1440,ge=10,le=10080),principal:Principal=Depends(require_scope("company.deployments:write")),db:Session=Depends(get_db)):
    release=_release(db,release_id,principal);env=_environment(db,environment_id,principal)
    try:return create_preview(db,release,env,ttl_minutes,principal.member_id)
    except ReleaseError as exc:raise HTTPException(409,str(exc))


@router.get("/deployments")
def list_deployments(environment_id:int|None=None,principal:Principal=Depends(require_scope("company.deployments:read")),db:Session=Depends(get_db)):
    q=db.query(Deployment).filter(Deployment.organization_id==active_org(principal))
    if environment_id is not None:_environment(db,environment_id,principal);q=q.filter(Deployment.environment_id==environment_id)
    return q.order_by(Deployment.id.desc()).limit(250).all()


@router.get("/previews")
def list_previews(principal:Principal=Depends(require_scope("company.deployments:read")),db:Session=Depends(get_db)):
    return db.query(PreviewEnvironment).filter(PreviewEnvironment.organization_id==active_org(principal)).order_by(PreviewEnvironment.id.desc()).limit(250).all()


@router.post("/deployments/{deployment_id}/rollback")
def rollback_deployment(deployment_id:int,payload:RollbackDeploymentRequest,principal:Principal=Depends(require_scope("company.deployments:rollback")),db:Session=Depends(get_db)):
    if principal.auth_type == "jwt" and ROLE_ORDER.get(principal.role, -1) < ROLE_ORDER["manager"]:
        raise HTTPException(403,"Manager role required for rollback")
    item=db.get(Deployment,deployment_id)
    if not item:raise HTTPException(404,"Deployment not found")
    enforce_org(item.organization_id,principal);requester=payload.requested_by_member_id or principal.member_id
    if payload.requested_by_member_id is not None:ensure_member(db,payload.requested_by_member_id,principal)
    try:return rollback_environment(db,item,requester,payload.reason)
    except ReleaseError as exc:raise HTTPException(409,str(exc))


@router.post("/delivery-automation-rules")
def create_automation_rule(payload:DeliveryAutomationRuleCreate,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);repo=_repo(db,payload.repository_id,principal)
    if payload.project_id is not None:ensure_project(db,payload.project_id,principal)
    if payload.target_member_id is not None:ensure_member(db,payload.target_member_id,principal)
    item=DeliveryAutomationRule(**payload.model_dump());db.add(item);db.commit();db.refresh(item);return item


@router.get("/delivery-automation-rules")
def list_automation_rules(principal:Principal=Depends(require_scope("company.devcloud:read")),db:Session=Depends(get_db)):
    return db.query(DeliveryAutomationRule).filter(DeliveryAutomationRule.organization_id==active_org(principal)).order_by(DeliveryAutomationRule.id.desc()).all()


@router.post("/handoffs/{handoff_id}/trigger-delivery")
def trigger_handoff_delivery(handoff_id:int,principal:Principal=Depends(require_scope("company.delivery:write")),db:Session=Depends(get_db)):
    handoff=db.get(ArtifactHandoff,handoff_id)
    if not handoff:raise HTTPException(404,"Handoff not found")
    enforce_org(handoff.organization_id,principal)
    runs=auto_delivery_from_handoff(db,handoff)
    return {"handoff_id":handoff.id,"created_delivery_runs":runs}
