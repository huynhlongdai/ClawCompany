"""v9 autonomous operations layer

Revision ID: 0004_v9_autonomous_ops
Revises: 0003_v8_operating_system
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_v9_autonomous_ops"
down_revision = "0003_v8_operating_system"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "autonomy_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False, server_default="supervised"),
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("retry_limit", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("max_auto_risk", sa.String(24), nullable=False, server_default="low"),
        sa.Column("daily_budget_limit", sa.Float(), nullable=False, server_default="100"),
        sa.Column("per_action_limit", sa.Float(), nullable=False, server_default="25"),
        sa.Column("pause_on_high_incident", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("require_approval_for_external_publish", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_autonomy_policies_organization_id", "autonomy_policies", ["organization_id"])
    op.create_index("ix_autonomy_policies_company_id", "autonomy_policies", ["company_id"])

    op.create_table(
        "executive_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("expected_outcome", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(24), nullable=False, server_default="high"),
        sa.Column("risk", sa.String(24), nullable=False, server_default="medium"),
        sa.Column("autonomy_mode", sa.String(32), nullable=False, server_default="inherit"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("execution_plan_id", sa.Integer(), sa.ForeignKey("nina_execution_plans.id"), nullable=True),
        sa.Column("deadline", sa.String(48), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_executive_goals_organization_id", "executive_goals", ["organization_id"])
    op.create_index("ix_executive_goals_company_id", "executive_goals", ["company_id"])
    op.create_index("ix_executive_goals_status", "executive_goals", ["status"])
    op.create_index("ix_executive_goals_execution_plan_id", "executive_goals", ["execution_plan_id"])

    op.create_table(
        "budget_envelopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("executive_goals.id"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("currency", sa.String(12), nullable=False, server_default="USD"),
        sa.Column("amount_limit", sa.Float(), nullable=False, server_default="0"),
        sa.Column("amount_reserved", sa.Float(), nullable=False, server_default="0"),
        sa.Column("amount_spent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_budget_envelopes_organization_id", "budget_envelopes", ["organization_id"])
    op.create_index("ix_budget_envelopes_company_id", "budget_envelopes", ["company_id"])
    op.create_index("ix_budget_envelopes_goal_id", "budget_envelopes", ["goal_id"])

    op.create_table(
        "budget_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budget_envelopes.id"), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False, server_default="spend"),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("memo", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_budget_ledger_entries_organization_id", "budget_ledger_entries", ["organization_id"])
    op.create_index("ix_budget_ledger_entries_budget_id", "budget_ledger_entries", ["budget_id"])
    op.create_index("ix_budget_ledger_entries_created_at", "budget_ledger_entries", ["created_at"])

    op.create_table(
        "operating_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("executive_goals.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="supervised"),
        sa.Column("snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("decisions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_operating_cycles_organization_id", "operating_cycles", ["organization_id"])
    op.create_index("ix_operating_cycles_goal_id", "operating_cycles", ["goal_id"])
    op.create_index("ix_operating_cycles_status", "operating_cycles", ["status"])

    op.create_table(
        "delegation_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("operating_cycles.id"), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("executive_goals.id"), nullable=False),
        sa.Column("plan_step_id", sa.Integer(), sa.ForeignKey("nina_plan_steps.id"), nullable=True),
        sa.Column("parent_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("assignee_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("instruction", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("runtime_run_id", sa.String(180), nullable=False, server_default=""),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ["organization_id", "cycle_id", "goal_id", "plan_step_id", "assignee_member_id", "task_id", "status", "runtime_run_id"]:
        op.create_index(f"ix_delegation_assignments_{col}", "delegation_assignments", [col])

    op.create_table(
        "recovery_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("executive_goals.id"), nullable=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("operating_cycles.id"), nullable=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("delegation_assignments.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("runtime_run_id", sa.String(180), nullable=False, server_default=""),
        sa.Column("incident_type", sa.String(80), nullable=False, server_default="runtime_failure"),
        sa.Column("severity", sa.String(24), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    for col in ["organization_id", "goal_id", "cycle_id", "assignment_id", "runtime_run_id", "status"]:
        op.create_index(f"ix_recovery_incidents_{col}", "recovery_incidents", [col])

    op.create_table(
        "organization_memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("memory_type", sa.String(48), nullable=False, server_default="fact"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for col in ["organization_id", "company_id", "department_id", "project_id", "agent_id", "status", "created_at"]:
        op.create_index(f"ix_organization_memories_{col}", "organization_memories", [col])

    op.create_table(
        "recurring_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schedule", sa.String(120), nullable=False, server_default="0 8 * * *"),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("operation_type", sa.String(64), nullable=False, server_default="nina_goal"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_status", sa.String(32), nullable=False, server_default="never"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recurring_operations_organization_id", "recurring_operations", ["organization_id"])
    op.create_index("ix_recurring_operations_company_id", "recurring_operations", ["company_id"])
    op.create_index("ix_recurring_operations_next_run_at", "recurring_operations", ["next_run_at"])


def downgrade():
    for table in [
        "recurring_operations", "organization_memories", "recovery_incidents", "delegation_assignments",
        "operating_cycles", "budget_ledger_entries", "budget_envelopes", "executive_goals", "autonomy_policies",
    ]:
        op.drop_table(table)
