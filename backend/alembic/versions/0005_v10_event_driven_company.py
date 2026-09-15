"""v10 event-driven autonomous company

Revision ID: 0005_v10_event_driven_company
Revises: 0004_v9_autonomous_ops
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_v10_event_driven_company"
down_revision = "0004_v9_autonomous_ops"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("event_type", sa.String(180), nullable=False),
        sa.Column("source", sa.String(120), nullable=False, server_default="company"),
        sa.Column("aggregate_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("aggregate_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("correlation_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("causation_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("actor_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id", "company_id", "event_type", "correlation_id", "status", "occurred_at"]:
        op.create_index(f"ix_company_events_{col}", "company_events", [col])

    op.create_table(
        "event_triggers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("event_pattern", sa.String(180), nullable=False, server_default="*"),
        sa.Column("condition_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("action_type", sa.String(80), nullable=False, server_default="message"),
        sa.Column("action_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_event_triggers_organization_id", "event_triggers", ["organization_id"])
    op.create_index("ix_event_triggers_company_id", "event_triggers", ["company_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("created_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("created_by_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("runtime_run_id", sa.String(180), nullable=False, server_default=""),
        sa.Column("bundle_key", sa.String(180), nullable=False, server_default=""),
        sa.Column("logical_path", sa.String(500), nullable=False, server_default=""),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False, server_default="deliverable"),
        sa.Column("mime_type", sa.String(120), nullable=False, server_default="text/plain"),
        sa.Column("storage_backend", sa.String(48), nullable=False, server_default="inline"),
        sa.Column("uri", sa.String(1000), nullable=False, server_default=""),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for col in ["organization_id", "company_id", "project_id", "task_id", "runtime_run_id", "bundle_key", "content_sha256", "status", "created_at"]:
        op.create_index(f"ix_artifacts_{col}", "artifacts", [col])

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("thread_key", sa.String(180), nullable=False, server_default=""),
        sa.Column("sender_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("recipient_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("message_type", sa.String(48), nullable=False, server_default="message"),
        sa.Column("subject", sa.String(220), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("priority", sa.String(24), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(32), nullable=False, server_default="sent"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id", "company_id", "thread_key", "sender_member_id", "recipient_member_id", "task_id", "artifact_id", "status", "created_at"]:
        op.create_index(f"ix_agent_messages_{col}", "agent_messages", [col])

    op.create_table(
        "artifact_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("from_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("to_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("purpose", sa.String(80), nullable=False, server_default="continue_work"),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id", "artifact_id", "to_member_id", "task_id", "status"]:
        op.create_index(f"ix_artifact_handoffs_{col}", "artifact_handoffs", [col])

    op.create_table(
        "artifact_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("evaluator_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("evaluator_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("rubric_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("verdict", sa.String(32), nullable=False, server_default="review"),
        sa.Column("findings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ["organization_id", "artifact_id", "verdict", "created_at"]:
        op.create_index(f"ix_artifact_evaluations_{col}", "artifact_evaluations", [col])

    op.create_table(
        "trigger_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("trigger_id", sa.Integer(), sa.ForeignKey("event_triggers.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("company_events.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("result_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("result_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ["organization_id", "trigger_id", "event_id", "status"]:
        op.create_index(f"ix_trigger_executions_{col}", "trigger_executions", [col])

    op.create_table(
        "sla_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False, server_default="task"),
        sa.Column("priority", sa.String(24), nullable=False, server_default="*"),
        sa.Column("response_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("completion_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("escalation_after_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("escalation_target_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sla_profiles_organization_id", "sla_profiles", ["organization_id"])
    op.create_index("ix_sla_profiles_company_id", "sla_profiles", ["company_id"])

    op.create_table(
        "sla_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("sla_profiles.id"), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(160), nullable=False),
        sa.Column("breach_type", sa.String(48), nullable=False, server_default="completion"),
        sa.Column("severity", sa.String(24), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("breached_at", sa.DateTime(), nullable=False),
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id", "profile_id", "resource_type", "resource_id", "status"]:
        op.create_index(f"ix_sla_incidents_{col}", "sla_incidents", [col])

    op.create_table(
        "decision_loops",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False, server_default="Nina Continuous Loop"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="supervised"),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("policy_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_tick_at", sa.DateTime(), nullable=True),
        sa.Column("next_tick_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_decision_loops_organization_id", "decision_loops", ["organization_id"])
    op.create_index("ix_decision_loops_company_id", "decision_loops", ["company_id"])
    op.create_index("ix_decision_loops_next_tick_at", "decision_loops", ["next_tick_at"])

    op.create_table(
        "decision_loop_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("loop_id", sa.Integer(), sa.ForeignKey("decision_loops.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("decisions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ["organization_id", "loop_id", "status", "created_at"]:
        op.create_index(f"ix_decision_loop_runs_{col}", "decision_loop_runs", [col])

    op.create_table(
        "simulation_scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_simulation_scenarios_organization_id", "simulation_scenarios", ["organization_id"])
    op.create_index("ix_simulation_scenarios_company_id", "simulation_scenarios", ["company_id"])

    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("simulation_scenarios.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("input_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ["organization_id", "scenario_id", "status", "created_at"]:
        op.create_index(f"ix_simulation_runs_{col}", "simulation_runs", [col])


def downgrade():
    for table in [
        "simulation_runs", "simulation_scenarios", "decision_loop_runs", "decision_loops",
        "sla_incidents", "sla_profiles", "trigger_executions", "artifact_evaluations",
        "artifact_handoffs", "agent_messages", "artifacts", "event_triggers", "company_events",
    ]:
        op.drop_table(table)
