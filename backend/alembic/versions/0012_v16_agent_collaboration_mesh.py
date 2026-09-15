"""v16 agent collaboration fabric and shared knowledge mesh

Revision ID: 0012_v16_agent_collaboration_mesh
Revises: 0011_v15_production_trust_sre
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_v16_agent_collaboration_mesh"
down_revision = "0011_v15_production_trust_sre"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("agent_teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("team_key", sa.String(120), nullable=False), sa.Column("name", sa.String(180), nullable=False),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("lead_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("collaboration_mode", sa.String(32), nullable=False),
        sa.Column("cross_company", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("disbanded_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "team_key", name="uq_agent_team_org_key"))
    op.create_index("ix_agent_teams_organization_id", "agent_teams", ["organization_id"])

    op.create_table("agent_team_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("agent_teams.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("team_role", sa.String(32), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("turn_order", sa.Integer(), nullable=False),
        sa.Column("allocation_percent", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("left_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("team_id", "member_id", name="uq_agent_team_member"))
    op.create_index("ix_agent_team_members_team_id", "agent_team_members", ["team_id"])

    op.create_table("collaboration_rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("agent_teams.id"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("room_key", sa.String(120), nullable=False), sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False), sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("turn_cursor", sa.Integer(), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("created_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "room_key", name="uq_collab_room_org_key"))
    op.create_index("ix_collaboration_rooms_organization_id", "collaboration_rooms", ["organization_id"])

    op.create_table("room_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("collaboration_rooms.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("participant_role", sa.String(32), nullable=False),
        sa.Column("seat_order", sa.Integer(), nullable=False),
        sa.Column("can_post", sa.Boolean(), nullable=False), sa.Column("can_decide", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("room_id", "member_id", name="uq_room_participant"))
    op.create_index("ix_room_participants_room_id", "room_participants", ["room_id"])

    op.create_table("room_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("collaboration_rooms.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("turn_type", sa.String(32), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("references_json", sa.Text(), nullable=False),
        sa.Column("knowledge_entry_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("room_id", "sequence", name="uq_room_turn_sequence"))
    op.create_index("ix_room_turns_room_id", "room_turns", ["room_id"])

    op.create_table("delegation_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("collaboration_rooms.id"), nullable=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("agent_teams.id"), nullable=True),
        sa.Column("from_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("to_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False), sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("max_cost_usd", sa.Float(), nullable=False), sa.Column("deadline_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("delivery_artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=False), sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True), sa.Column("closed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_delegation_contracts_organization_id", "delegation_contracts", ["organization_id"])
    op.create_index("ix_delegation_contracts_status", "delegation_contracts", ["status"])

    op.create_table("shared_knowledge_spaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("owner_company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("slug", sa.String(120), nullable=False), sa.Column("name", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("default_permission", sa.String(24), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_knowledge_space_org_slug"))
    op.create_index("ix_shared_knowledge_spaces_organization_id", "shared_knowledge_spaces", ["organization_id"])

    op.create_table("knowledge_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("shared_knowledge_spaces.id"), nullable=False),
        sa.Column("grantee_type", sa.String(24), nullable=False), sa.Column("grantee_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(24), nullable=False),
        sa.Column("granted_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.create_index("ix_knowledge_grants_space_id", "knowledge_grants", ["space_id"])

    op.create_table("shared_knowledge_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("shared_knowledge_spaces.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_documents.id"), nullable=True),
        sa.Column("memory_id", sa.Integer(), sa.ForeignKey("organization_memories.id"), nullable=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("collaboration_rooms.id"), nullable=True),
        sa.Column("title", sa.String(300), nullable=False), sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(48), nullable=False), sa.Column("source_id", sa.String(180), nullable=False),
        sa.Column("contributed_by_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_entry_id", sa.Integer(), sa.ForeignKey("shared_knowledge_entries.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_shared_knowledge_entries_space_id", "shared_knowledge_entries", ["space_id"])

    op.create_table("knowledge_access_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("shared_knowledge_spaces.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("action", sa.String(24), nullable=False), sa.Column("permission_used", sa.String(24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False), sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_knowledge_access_logs_space_id", "knowledge_access_logs", ["space_id"])


def downgrade():
    for table in ("knowledge_access_logs", "shared_knowledge_entries", "knowledge_grants",
                  "shared_knowledge_spaces", "delegation_contracts", "room_turns", "room_participants",
                  "collaboration_rooms", "agent_team_members", "agent_teams"):
        op.drop_table(table)
