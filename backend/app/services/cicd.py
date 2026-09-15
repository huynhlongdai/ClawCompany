import json
import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from app.models import (
    BuildRecord, CICDEdge, CICDNode, CICDNodeRun, CICDPipelineGraph, CICDRun,
    DevWorkspace, Release, Repository, SandboxProfile, SandboxRun, SecurityReview,
)
from app.services.build_evidence import BuildEvidenceError, generate_build_evidence, resolve_commit
from app.services.company_event_bus import emit_event
from app.services.sandbox_runner import execute_sandbox
from app.services.security_review import SecurityReviewError, scan_repository_commit


class CICDError(RuntimeError):
    pass


def graph_nodes(db: Session, graph_id: int) -> list[CICDNode]:
    return db.query(CICDNode).filter(CICDNode.graph_id == graph_id).order_by(CICDNode.order_hint, CICDNode.id).all()


def graph_edges(db: Session, graph_id: int) -> list[CICDEdge]:
    return db.query(CICDEdge).filter(CICDEdge.graph_id == graph_id).order_by(CICDEdge.id).all()


def validate_graph(db: Session, graph: CICDPipelineGraph) -> dict:
    nodes = graph_nodes(db, graph.id)
    edges = graph_edges(db, graph.id)
    if not nodes:
        raise CICDError("CI/CD graph has no nodes")
    ids = {n.id for n in nodes}
    indegree = {n.id: 0 for n in nodes}
    outgoing = {n.id: [] for n in nodes}
    for edge in edges:
        if edge.from_node_id not in ids or edge.to_node_id not in ids:
            raise CICDError("CI/CD edge references a node outside the graph")
        if edge.from_node_id == edge.to_node_id:
            raise CICDError("CI/CD graph contains a self-cycle")
        indegree[edge.to_node_id] += 1
        outgoing[edge.from_node_id].append(edge.to_node_id)
    queue = sorted([n.id for n in nodes if indegree[n.id] == 0])
    ordered: list[int] = []
    while queue:
        current = queue.pop(0); ordered.append(current)
        for nxt in outgoing[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt); queue.sort()
    if len(ordered) != len(nodes):
        raise CICDError("CI/CD graph contains a cycle")
    by_id = {n.id: n for n in nodes}
    return {"valid": True, "node_count": len(nodes), "edge_count": len(edges),
            "order": [by_id[x].node_key for x in ordered], "node_ids": ordered}


def create_graph(db: Session, *, organization_id: int, repository_id: int, name: str, nodes: list[dict], edges: list[dict],
                 company_id: int | None = None, project_id: int | None = None, trigger: dict | None = None,
                 status: str = "active", created_by_member_id: int | None = None) -> CICDPipelineGraph:
    graph = CICDPipelineGraph(
        organization_id=organization_id, company_id=company_id, project_id=project_id, repository_id=repository_id,
        name=name, trigger_json=json.dumps(trigger or {}), status=status, created_by_member_id=created_by_member_id,
    )
    db.add(graph); db.commit(); db.refresh(graph)
    mapping: dict[str, CICDNode] = {}
    for raw in nodes:
        key = raw["key"]
        if key in mapping:
            raise CICDError(f"Duplicate node key: {key}")
        node = CICDNode(
            organization_id=organization_id, graph_id=graph.id, node_key=key, node_type=raw.get("type", "noop"),
            name=raw.get("name") or key, config_json=json.dumps(raw.get("config") or {}),
            required=bool(raw.get("required", True)), order_hint=int(raw.get("order_hint", 0)),
        )
        db.add(node); db.flush(); mapping[key] = node
    for raw in edges:
        source = mapping.get(raw["source"]); target = mapping.get(raw["target"])
        if not source or not target:
            raise CICDError("CI/CD edge references an unknown node key")
        db.add(CICDEdge(
            organization_id=organization_id, graph_id=graph.id, from_node_id=source.id, to_node_id=target.id,
            condition_json=json.dumps(raw.get("condition") or {}),
        ))
    db.commit()
    try:
        validate_graph(db, graph)
    except Exception:
        # The graph remains visible as invalid/draft for diagnosis, but cannot execute.
        graph.status = "draft"; db.add(graph); db.commit()
        raise
    return graph


def start_run(db: Session, graph: CICDPipelineGraph, *, ref: str = "main", commit_sha: str = "",
              member_id: int | None = None, agent_id: int | None = None) -> CICDRun:
    if graph.status != "active":
        raise CICDError("CI/CD graph is not active")
    validate_graph(db, graph)
    repo = db.get(Repository, graph.repository_id)
    if not repo or repo.organization_id != graph.organization_id:
        raise CICDError("Repository is unavailable")
    commit = resolve_commit(repo, commit_sha or ref)
    item = CICDRun(
        organization_id=graph.organization_id, graph_id=graph.id, repository_id=repo.id, project_id=graph.project_id,
        initiated_by_member_id=member_id, initiated_by_agent_id=agent_id, ref=ref, commit_sha=commit,
        status="queued", correlation_id=uuid.uuid4().hex,
    )
    db.add(item); db.commit(); db.refresh(item)
    emit_event(
        db, organization_id=item.organization_id, company_id=graph.company_id, event_type="cicd.run.created",
        source="engineering_org", aggregate_type="cicd_run", aggregate_id=str(item.id), actor_member_id=member_id,
        correlation_id=item.correlation_id, payload={"ci_run_id": item.id, "graph_id": graph.id, "commit_sha": commit},
    )
    return item


def _config(node: CICDNode) -> dict:
    try:
        value = json.loads(node.config_json or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _execute_node(db: Session, run: CICDRun, node: CICDNode) -> tuple[dict, int | None]:
    config = _config(node)
    repo = db.get(Repository, run.repository_id)
    if not repo:
        raise CICDError("Repository is unavailable")
    if node.node_type == "noop":
        return {"message": config.get("message", "noop completed")}, None
    if node.node_type == "gate":
        if not bool(config.get("allow", True)):
            raise CICDError(config.get("reason", "CI/CD gate rejected execution"))
        return {"allowed": True, "reason": config.get("reason", "gate passed")}, None
    if node.node_type == "evidence":
        build = generate_build_evidence(
            db, repo, run.commit_sha, ci_run_id=run.id,
            producer_member_id=run.initiated_by_member_id, producer_agent_id=run.initiated_by_agent_id,
        )
        return {"build_id": build.id, "source_digest": build.source_digest}, None
    if node.node_type == "security":
        block_on = config.get("block_on") or ["critical", "high"]
        review = scan_repository_commit(
            db, repo, run.commit_sha, ci_run_id=run.id, reviewer_member_id=run.initiated_by_member_id,
            reviewer_agent_id=run.initiated_by_agent_id, block_on=block_on,
        )
        output = {"security_review_id": review.id, "verdict": review.verdict, "score": review.score}
        if review.verdict == "blocked" and node.required:
            raise CICDError(f"Security review blocked pipeline (review {review.id})")
        return output, None
    if node.node_type == "sandbox":
        workspace_id = int(config.get("workspace_id") or 0); profile_id = int(config.get("profile_id") or 0)
        command = config.get("command") or []
        workspace = db.get(DevWorkspace, workspace_id); profile = db.get(SandboxProfile, profile_id)
        if not workspace or workspace.organization_id != run.organization_id:
            raise CICDError("Sandbox node workspace is unavailable")
        if not profile or profile.organization_id != run.organization_id:
            raise CICDError("Sandbox node profile is unavailable")
        sandbox = SandboxRun(
            organization_id=run.organization_id, workspace_id=workspace.id, profile_id=profile.id,
            initiated_by_member_id=run.initiated_by_member_id, initiated_by_agent_id=run.initiated_by_agent_id,
            purpose=config.get("purpose", "test"), command_json=json.dumps(command),
            secret_grant_ids_json=json.dumps(config.get("secret_grant_ids") or []), status="queued",
        )
        db.add(sandbox); db.commit(); db.refresh(sandbox); execute_sandbox(db, sandbox)
        if sandbox.status != "passed" and node.required:
            raise CICDError(sandbox.error or f"Sandbox node failed with exit code {sandbox.exit_code}")
        return {"sandbox_run_id": sandbox.id, "status": sandbox.status, "exit_code": sandbox.exit_code}, sandbox.id
    if node.node_type == "release":
        version = str(config.get("version") or f"ci-{run.id}-{run.commit_sha[:8]}")[:120]
        build = db.query(BuildRecord).filter(BuildRecord.ci_run_id == run.id, BuildRecord.status == "completed").order_by(BuildRecord.id.desc()).first()
        release = Release(
            organization_id=run.organization_id, repository_id=run.repository_id, project_id=run.project_id,
            created_by_member_id=run.initiated_by_member_id, version=version, commit_sha=run.commit_sha,
            status="ready", release_notes=str(config.get("release_notes") or f"Created by CI/CD run {run.id}"),
            manifest_json=json.dumps({"ci_run_id": run.id, "build_id": build.id if build else None,
                                      "source_digest": build.source_digest if build else ""}),
        )
        db.add(release); db.commit(); db.refresh(release)
        run.release_id = release.id; db.add(run); db.commit(); db.refresh(run)
        return {"release_id": release.id, "version": release.version}, None
    raise CICDError(f"Unsupported CI/CD node type: {node.node_type}")


def execute_run(db: Session, run: CICDRun) -> CICDRun:
    graph = db.get(CICDPipelineGraph, run.graph_id)
    if not graph or graph.organization_id != run.organization_id:
        raise CICDError("CI/CD graph is unavailable")
    order = validate_graph(db, graph)["node_ids"]
    run.status = "running"; run.started_at = datetime.utcnow(); run.error = ""; db.add(run); db.commit(); db.refresh(run)
    completed: list[dict] = []
    for node_id in order:
        node = db.get(CICDNode, node_id)
        node_run = CICDNodeRun(
            organization_id=run.organization_id, ci_run_id=run.id, node_id=node.id, status="running",
            started_at=datetime.utcnow(),
        )
        db.add(node_run); db.commit(); db.refresh(node_run)
        try:
            output, sandbox_id = _execute_node(db, run, node)
            node_run.status = "succeeded"; node_run.output_json = json.dumps(output, default=str)
            node_run.sandbox_run_id = sandbox_id; completed.append({"node": node.node_key, "status": "succeeded", **output})
        except (CICDError, BuildEvidenceError, SecurityReviewError, Exception) as exc:
            node_run.status = "failed"; node_run.error = str(exc)[:8000]
            node_run.completed_at = datetime.utcnow(); db.add(node_run); db.commit()
            run.status = "failed"; run.error = f"{node.node_key}: {exc}"[:8000]; run.completed_at = datetime.utcnow()
            run.summary_json = json.dumps({"nodes": completed, "failed_node": node.node_key})
            db.add(run); db.commit(); db.refresh(run)
            emit_event(
                db, organization_id=run.organization_id, company_id=graph.company_id, event_type="cicd.run.failed",
                source="engineering_org", aggregate_type="cicd_run", aggregate_id=str(run.id),
                actor_member_id=run.initiated_by_member_id, correlation_id=run.correlation_id,
                payload={"ci_run_id": run.id, "node": node.node_key, "error": run.error},
            )
            return run
        node_run.completed_at = datetime.utcnow(); db.add(node_run); db.commit()
    run.status = "succeeded"; run.completed_at = datetime.utcnow(); run.summary_json = json.dumps({"nodes": completed})
    db.add(run); db.commit(); db.refresh(run)
    emit_event(
        db, organization_id=run.organization_id, company_id=graph.company_id, event_type="cicd.run.succeeded",
        source="engineering_org", aggregate_type="cicd_run", aggregate_id=str(run.id),
        actor_member_id=run.initiated_by_member_id, correlation_id=run.correlation_id,
        payload={"ci_run_id": run.id, "release_id": run.release_id, "commit_sha": run.commit_sha},
    )
    return run
