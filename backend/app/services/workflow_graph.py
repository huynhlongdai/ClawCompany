import json
from sqlalchemy.orm import Session
from app.models import Workflow, WorkflowGraphVersion


def _topological_order(graph: dict) -> list[str]:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    ids = [str(n.get("id")) for n in nodes]
    known = set(ids)
    adjacency = {x: [] for x in known}
    indegree = {x: 0 for x in known}
    for edge in edges:
        src, dst = str(edge.get("source")), str(edge.get("target"))
        adjacency[src].append(dst)
        indegree[dst] += 1
    queue = [node_id for node_id in ids if indegree[node_id] == 0]
    ordered = []
    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)
        for nxt in adjacency[node_id]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return ordered


def validate_graph(graph: dict) -> None:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Workflow graph requires nodes[] and edges[]")
    ids = [str(n.get("id")) for n in nodes]
    if any(x in {"", "None"} for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("Workflow nodes must have unique ids")
    known = set(ids)
    for edge in edges:
        src, dst = str(edge.get("source")), str(edge.get("target"))
        if src not in known or dst not in known:
            raise ValueError("Workflow edge references an unknown node")
    if len(_topological_order(graph)) != len(ids):
        raise ValueError("Workflow graph must be acyclic")


def compile_graph(graph: dict, workflow: Workflow) -> list[dict]:
    """Compile the visual DAG into the v7 executable `steps` contract.

    Visual-only trigger nodes are omitted. Agent nodes must be bound to an
    `agent_id` before a graph can be published. This avoids publishing a graph
    that would deterministically fail at runtime.
    """
    validate_graph(graph)
    by_id = {str(node.get("id")): node for node in graph.get("nodes", [])}
    steps: list[dict] = []
    for node_id in _topological_order(graph):
        node = by_id[node_id]
        typ = str(node.get("type") or "note")
        name = str(node.get("label") or node.get("name") or node_id)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        merged = {**data, **node}
        if typ == "trigger":
            continue
        if typ == "agent":
            agent_id = merged.get("agent_id")
            if not agent_id:
                raise ValueError(f"Agent node '{node_id}' must be bound to agent_id before publish")
            steps.append({
                "type": "agent", "name": name, "agent_id": int(agent_id),
                "input": str(merged.get("input") or merged.get("prompt") or workflow.name),
            })
        elif typ == "approval":
            steps.append({
                "type": "approval", "name": name,
                "action": str(merged.get("action") or workflow.name),
                "risk": str(merged.get("risk") or "medium"),
                "policy_key": str(merged.get("policy_key") or "workflow-step"),
                "evidence": str(merged.get("evidence") or ""),
            })
        elif typ == "tool":
            steps.append({
                "type": "tool", "name": name,
                "tool": str(merged.get("tool") or "noop"),
                "args": merged.get("args") if isinstance(merged.get("args"), dict) else {},
            })
        else:
            steps.append({"type": "note", "name": name})
    return steps


def save_graph(db: Session, workflow: Workflow, graph: dict, publish: bool, user_id: int | None):
    validate_graph(graph)
    executable = compile_graph(graph, workflow) if publish else None
    last = db.query(WorkflowGraphVersion).filter(WorkflowGraphVersion.workflow_id == workflow.id).order_by(WorkflowGraphVersion.version.desc()).first()
    item = WorkflowGraphVersion(
        workflow_id=workflow.id,
        version=(last.version + 1 if last else 1),
        graph_json=json.dumps(graph, ensure_ascii=False),
        published=publish,
        created_by_user_id=user_id,
    )
    if publish:
        db.query(WorkflowGraphVersion).filter(WorkflowGraphVersion.workflow_id == workflow.id).update({WorkflowGraphVersion.published: False})
        workflow.definition_json = json.dumps({"graph": graph, "steps": executable}, ensure_ascii=False)
        db.add(workflow)
    db.add(item); db.commit(); db.refresh(item)
    return item
