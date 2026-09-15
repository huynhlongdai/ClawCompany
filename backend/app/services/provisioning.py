import json, re, uuid
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import (
    Agent, AgentProvisioningJob, Company, CompanyProvisioningJob, Department,
    MarketplaceTemplate, Member
)
from app.runtime.factory import get_runtime
from app.services.audit import log_event


def _json(value: str | None) -> dict:
    try: return json.loads(value or "{}")
    except Exception: return {}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "agent"


def resolve_manifest(db: Session, organization_id: int, template_id: int | None, inline: dict | None) -> dict:
    manifest = dict(inline or {})
    if template_id:
        template = db.get(MarketplaceTemplate, template_id)
        if not template or template.organization_id != organization_id:
            raise ValueError("Template not found in organization")
        base = _json(template.manifest_json)
        base.update(manifest)
        manifest = base
    return manifest


async def provision_agent(
    db: Session, *, organization_id: int, company_id: int | None, department_id: int | None,
    name: str, role: str, model: str = "", runtime_agent_id: str = "", manager_member_id: int | None = None,
    template_id: int | None = None, manifest: dict | None = None, requested_by_user_id: int | None = None,
) -> AgentProvisioningJob:
    manifest = resolve_manifest(db, organization_id, template_id, manifest)
    runtime_agent_id = runtime_agent_id or manifest.get("runtime_agent_id") or f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
    model = model or manifest.get("model", "")
    role = role or manifest.get("role", "AI Employee")
    job = AgentProvisioningJob(
        organization_id=organization_id, company_id=company_id, department_id=department_id,
        template_id=template_id, requested_by_user_id=requested_by_user_id, name=name, role=role,
        runtime_agent_id=runtime_agent_id, model=model, status="provisioning",
        manifest_json=json.dumps(manifest, ensure_ascii=False),
    )
    db.add(job); db.commit(); db.refresh(job)
    try:
        member = Member(
            organization_id=organization_id, company_id=company_id, department_id=department_id,
            name=name, member_type="agent", role=role, manager_id=manager_member_id, status="active",
        )
        db.add(member); db.flush()
        agent = Agent(
            member_id=member.id, runtime_provider="openclaw", runtime_agent_id=runtime_agent_id,
            lifecycle="provisioning", model=model, risk=manifest.get("risk", "low"),
        )
        db.add(agent); db.flush()
        job.member_id = member.id; job.agent_id = agent.id; db.commit()

        runtime_config = {
            "name": name, "role": role, "model": model,
            "system_prompt": manifest.get("system_prompt", ""),
            "skills": manifest.get("skills", []), "tools": manifest.get("tools", []),
            "channels": manifest.get("channels", []), "policy": manifest.get("policy", {}),
        }
        runtime_result = await get_runtime().create_agent(runtime_agent_id, runtime_config)
        agent.lifecycle = "active"
        job.status = "ready"; job.completed_at = datetime.utcnow()
        job.result_json = json.dumps({"agent_id": agent.id, "member_id": member.id, "runtime": runtime_result}, ensure_ascii=False, default=str)
        db.add_all([agent, job]); db.commit(); db.refresh(job)
        log_event(db, organization_id, "agent.hire", "agents", agent.id, actor_name="provisioning", payload={"job_id": job.id, "runtime_agent_id": runtime_agent_id})
        return job
    except Exception as exc:
        # The registry rows are intentionally committed before the external runtime call
        # so a failed provision remains visible and recoverable. Mark both the AI
        # employee and its member record explicitly instead of leaving a misleading
        # "provisioning/active" state after a runtime failure.
        db.rollback()
        job = db.get(AgentProvisioningJob, job.id)
        if job:
            if job.agent_id:
                failed_agent = db.get(Agent, job.agent_id)
                if failed_agent:
                    failed_agent.lifecycle = "runtime_error"
                    db.add(failed_agent)
            if job.member_id:
                failed_member = db.get(Member, job.member_id)
                if failed_member:
                    failed_member.status = "provisioning_failed"
                    db.add(failed_member)
            job.status = "failed"
            job.error = str(exc)
            job.completed_at = datetime.utcnow()
            db.add(job)
            db.commit()
            db.refresh(job)
            log_event(
                db, organization_id, "agent.hire.failed", "agent_provisioning_jobs", job.id,
                actor_name="provisioning",
                payload={"runtime_agent_id": runtime_agent_id, "error": str(exc)},
            )
        return job


async def provision_company(
    db: Session, *, organization_id: int, company_name: str, industry: str = "", template_id: int | None = None,
    manifest: dict | None = None, requested_by_user_id: int | None = None,
) -> CompanyProvisioningJob:
    manifest = resolve_manifest(db, organization_id, template_id, manifest)
    job = CompanyProvisioningJob(
        organization_id=organization_id, template_id=template_id, requested_by_user_id=requested_by_user_id,
        company_name=company_name, status="provisioning", manifest_json=json.dumps(manifest, ensure_ascii=False),
    )
    db.add(job); db.commit(); db.refresh(job)
    created_agents = []
    try:
        company = Company(organization_id=organization_id, name=company_name, industry=industry or manifest.get("industry", ""), status="active")
        db.add(company); db.commit(); db.refresh(company); job.company_id = company.id; db.add(job); db.commit()
        department_map: dict[str, int] = {}
        for dep_spec in manifest.get("departments", []):
            dep = Department(company_id=company.id, name=dep_spec.get("name", "Department"), access_level=dep_spec.get("access_level", "restricted"))
            db.add(dep); db.commit(); db.refresh(dep); department_map[dep.name] = dep.id
            for agent_spec in dep_spec.get("agents", []):
                a_job = await provision_agent(
                    db, organization_id=organization_id, company_id=company.id, department_id=dep.id,
                    name=agent_spec.get("name", "AI Employee"), role=agent_spec.get("role", "AI Employee"),
                    model=agent_spec.get("model", ""), runtime_agent_id=agent_spec.get("runtime_agent_id", ""),
                    manager_member_id=None, template_id=None, manifest=agent_spec,
                    requested_by_user_id=requested_by_user_id,
                )
                created_agents.append({"job_id": a_job.id, "agent_id": a_job.agent_id, "status": a_job.status})
        job.status = "ready" if all(x["status"] == "ready" for x in created_agents) else "partial"
        job.result_json = json.dumps({"company_id": company.id, "departments": department_map, "agents": created_agents}, ensure_ascii=False)
        job.completed_at = datetime.utcnow(); db.add(job); db.commit(); db.refresh(job)
        log_event(db, organization_id, "company.factory.install", "companies", company.id, actor_name="provisioning", payload={"job_id": job.id})
        return job
    except Exception as exc:
        db.rollback(); job = db.get(CompanyProvisioningJob, job.id)
        if job:
            job.status = "failed"; job.error = str(exc); job.completed_at = datetime.utcnow(); db.add(job); db.commit(); db.refresh(job)
        return job
