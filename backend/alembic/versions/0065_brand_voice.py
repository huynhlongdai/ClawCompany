"""Giọng thương hiệu: brand_voices (phiên bản có duyệt), brand_voice_settings (cưỡng chế), voice_checks (điểm giọng),
voice_profiles (giọng nói TTS), voice_samples (file nghe thử). Chuyển chữ "Giọng thương hiệu" cũ của hiến chương
(company_profiles.brand_voice) thành persona của bản v1 đã ban hành — AGENTS.md giữ đúng nội dung cũ."""
import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0065_brand_voice"
down_revision = "0064_work_wait_parallel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_voices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("change_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submitted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "version_no", name="uq_brand_voice_version"),
    )
    op.create_index("ix_brand_voices_organization_id", "brand_voices", ["organization_id"])
    op.create_index("ix_brand_voices_company_id", "brand_voices", ["company_id"])
    op.create_index("ix_brand_voices_status", "brand_voices", ["status"])
    op.create_table(
        "brand_voice_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, unique=True),
        sa.Column("enforcement", sa.String(12), nullable=False, server_default="flag"),
        sa.Column("min_score", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("model_check", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eval_suite_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_brand_voice_settings_organization_id", "brand_voice_settings", ["organization_id"])
    op.create_index("ix_brand_voice_settings_company_id", "brand_voice_settings", ["company_id"])
    op.create_table(
        "voice_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("task_output_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="try"),
        sa.Column("channel", sa.String(16), nullable=False, server_default="zalo"),
        sa.Column("segment", sa.String(40), nullable=False, server_default=""),
        sa.Column("voice_id", sa.Integer(), nullable=True),
        sa.Column("voice_version", sa.Integer(), nullable=True),
        sa.Column("lease_id", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="1"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("action", sa.String(12), nullable=False, server_default="none"),
        sa.Column("violations", sa.JSON(), nullable=True),
        sa.Column("model_result", sa.JSON(), nullable=True),
        sa.Column("text_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ("organization_id", "company_id", "member_id", "task_id", "created_at"):
        op.create_index(f"ix_voice_checks_{col}", "voice_checks", [col])
    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, unique=True),
        sa.Column("provider", sa.String(24), nullable=False, server_default="cometapi"),
        sa.Column("model", sa.String(64), nullable=False, server_default="gpt-4o-mini-tts"),
        sa.Column("voice_name", sa.String(64), nullable=False, server_default="nova"),
        sa.Column("language", sa.String(16), nullable=False, server_default="vi-VN"),
        sa.Column("speed", sa.Float(), nullable=False, server_default="1"),
        sa.Column("pitch", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("style", sa.Text(), nullable=False, server_default=""),
        sa.Column("greeting_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("closing_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("sample_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_voice_profiles_organization_id", "voice_profiles", ["organization_id"])
    op.create_index("ix_voice_profiles_company_id", "voice_profiles", ["company_id"])
    op.create_table(
        "voice_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False, server_default=""),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("voice_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("text_in", sa.Text(), nullable=False, server_default=""),
        sa.Column("text_spoken", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime", sa.String(40), nullable=False, server_default="audio/mpeg"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("audio", sa.LargeBinary(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ("organization_id", "company_id", "created_at"):
        op.create_index(f"ix_voice_samples_{col}", "voice_samples", [col])

    # dữ liệu: chữ giọng thương hiệu cũ → persona của v1 đã ban hành (giữ nguyên nội dung agent đang thấy)
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT organization_id, company_id, brand_voice FROM company_profiles "
                                "WHERE brand_voice IS NOT NULL AND brand_voice <> ''")).fetchall()
    bv = sa.table("brand_voices", sa.column("organization_id"), sa.column("company_id"), sa.column("version_no"),
                  sa.column("status"), sa.column("spec", sa.JSON()), sa.column("is_demo"), sa.column("change_note"),
                  sa.column("review_note"), sa.column("published_at"), sa.column("created_at"), sa.column("updated_at"))
    now = datetime.utcnow()
    for org_id, co_id, text in rows:
        op.bulk_insert(bv, [{"organization_id": org_id, "company_id": co_id, "version_no": 1, "status": "published",
                             "spec": json.loads(json.dumps({"persona": text.strip()[:2000], "migrated_from_charter": True})),
                             "is_demo": False, "change_note": "Chuyển từ mục \"Giọng thương hiệu\" của hiến chương (0065)",
                             "review_note": "", "published_at": now, "created_at": now, "updated_at": now}])


def downgrade() -> None:
    for t in ("voice_samples", "voice_profiles", "voice_checks", "brand_voice_settings", "brand_voices"):
        op.drop_table(t)
