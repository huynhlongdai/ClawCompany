import json
from sqlalchemy.orm import Session
from app.models import Artifact, ArtifactEvaluation
from app.services.company_event_bus import emit_event


def evaluate_artifact(db: Session, artifact: Artifact, *, evaluator_member_id: int | None = None,
                      evaluator_agent_id: int | None = None, rubric: dict | None = None) -> ArtifactEvaluation:
    rubric = rubric or {}
    content = artifact.content_text or ""
    findings = []
    score = 100.0
    min_chars = int(rubric.get("min_chars", 20))
    if len(content.strip()) < min_chars:
        score -= 45; findings.append({"severity":"high","code":"too_short","message":f"Content is shorter than {min_chars} characters."})
    required_terms = [str(x) for x in rubric.get("required_terms", [])]
    missing = [x for x in required_terms if x.lower() not in content.lower()]
    if missing:
        score -= min(40, 10 * len(missing)); findings.append({"severity":"medium","code":"missing_terms","missing":missing})
    forbidden_terms = [str(x) for x in rubric.get("forbidden_terms", [])]
    found = [x for x in forbidden_terms if x.lower() in content.lower()]
    if found:
        score -= min(50, 15 * len(found)); findings.append({"severity":"high","code":"forbidden_terms","found":found})
    if rubric.get("require_sha256", True) and not artifact.content_sha256 and content:
        score -= 5; findings.append({"severity":"low","code":"checksum_missing"})
    score = max(0.0, min(100.0, score))
    pass_score = float(rubric.get("pass_score", 80))
    verdict = "approved" if score >= pass_score else "changes_requested"
    item = ArtifactEvaluation(
        organization_id=artifact.organization_id, artifact_id=artifact.id, evaluator_member_id=evaluator_member_id,
        evaluator_agent_id=evaluator_agent_id, rubric_json=json.dumps(rubric, ensure_ascii=False), score=score,
        verdict=verdict, findings_json=json.dumps(findings, ensure_ascii=False), status="completed",
    )
    artifact.status = "approved" if verdict == "approved" else "changes_requested"
    db.add_all([item, artifact]); db.commit(); db.refresh(item); db.refresh(artifact)
    emit_event(
        db, organization_id=artifact.organization_id, company_id=artifact.company_id,
        event_type=f"artifact.evaluation.{verdict}", source="quality_gate", aggregate_type="artifact",
        aggregate_id=str(artifact.id), actor_member_id=evaluator_member_id,
        payload={"artifact_id": artifact.id, "evaluation_id": item.id, "score": score, "verdict": verdict, "findings": findings},
    )
    return item
