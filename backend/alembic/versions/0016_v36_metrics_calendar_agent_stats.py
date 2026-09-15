"""v36: chuỗi thời gian chỉ số, lịch, số theo ngày của agent, hạn chót dự án

Revision ID: 0016_v36_metrics_calendar
Revises: 0015_v32_department_status_not_null

Bốn thứ bản thiết kế cần mà 159 bảng cũ không có. Mỗi cái mở chỗ cho dữ liệu
thật, không cái nào tự sinh số:

* ``metric_samples`` — lịch sử của ``analytics_metrics``. Bảng cũ giữ hai mốc
  (hiện tại, kỳ trước) nên biểu đồ nhiều kỳ trước đây là bịa.
* ``calendar_events`` — lịch do người/agent tạo. Chưa nối nhà cung cấp nào.
* ``agent_daily_stats`` — số theo ngày cho từng agent, do service dẫn xuất từ
  ``usage_events`` và ``company_events``.
* ``projects.due_date`` — một cột, nullable: "chưa đặt hạn" là câu trả lời
  hợp lệ, khác với một ngày mặc định.

Backfill có chủ đích, chỉ từ số đã có:

* Mỗi hàng ``analytics_metrics`` sinh HAI mẫu — kỳ này và kỳ trước — với
  ``source='analytics_backfill'``. Không nội suy thêm mốc nào ở giữa; hai
  điểm là đúng những gì bảng cũ biết.
* Không backfill ``agent_daily_stats``: nó phải được tính từ usage_events bởi
  service, và làm ở migration thì con số sẽ cũ ngay khi có lượt chạy mới.
"""
from datetime import datetime, timedelta

from alembic import op
import sqlalchemy as sa

revision = "0016_v36_metrics_calendar"
down_revision = "0015_v32_department_status_not_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ---- projects.due_date ------------------------------------------------
    project_columns = {c["name"] for c in inspector.get_columns("projects")}
    if "due_date" not in project_columns:
        op.add_column("projects", sa.Column("due_date", sa.Date(), nullable=True))

    existing = set(inspector.get_table_names())

    # ---- metric_samples ---------------------------------------------------
    if "metric_samples" not in existing:
        op.create_table(
            "metric_samples",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("metric_key", sa.String(length=120), nullable=False, index=True),
            sa.Column("scope_type", sa.String(length=64), nullable=False, server_default="organization"),
            sa.Column("scope_id", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("period", sa.String(length=20), nullable=False, index=True),
            sa.Column("value", sa.Float(), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(length=40), nullable=False, server_default=""),
            sa.Column("source", sa.String(length=64), nullable=False, server_default="manual"),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organization_id", "metric_key", "scope_type", "scope_id",
                                "period", name="uq_metric_samples_point"),
        )

    # ---- calendar_events --------------------------------------------------
    if "calendar_events" not in existing:
        op.create_table(
            "calendar_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"),
                      nullable=True, index=True),
            sa.Column("title", sa.String(length=220), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("starts_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("ends_at", sa.DateTime(), nullable=True),
            sa.Column("location", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("event_type", sa.String(length=32), nullable=False, server_default="meeting"),
            sa.Column("owner_member_id", sa.Integer(), sa.ForeignKey("members.id"), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="scheduled"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    # ---- agent_daily_stats ------------------------------------------------
    if "agent_daily_stats" not in existing:
        op.create_table(
            "agent_daily_stats",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(),
                      sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"),
                      nullable=False, index=True),
            sa.Column("day", sa.Date(), nullable=False, index=True),
            sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tasks_completed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tasks_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
            # NULL = ngày đó không có việc nào kết thúc. "Không đo được" khác "0%".
            sa.Column("success_rate", sa.Float(), nullable=True),
            sa.Column("derived_at", sa.DateTime(), nullable=False),
        )

    # ---- backfill metric_samples từ analytics_metrics ---------------------
    # Hai mẫu cho mỗi chỉ số: kỳ này và kỳ trước. Đó là toàn bộ những gì bảng
    # cũ biết; nội suy thêm mốc giữa sẽ là số bịa.
    now = datetime.utcnow()
    this_period = now.strftime("%Y-%m")
    prev_period = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    rows = list(bind.execute(sa.text(
        "SELECT organization_id, metric_key, scope_type, scope_id, "
        "current_value, previous_value, unit FROM analytics_metrics"
    )))
    for org_id, key, scope_type, scope_id, current, previous, unit in rows:
        for period, value in ((prev_period, previous), (this_period, current)):
            if value is None:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO metric_samples "
                    "(organization_id, metric_key, scope_type, scope_id, period, value, "
                    " unit, source, recorded_at) "
                    "VALUES (:org, :key, :st, :sid, :period, :value, :unit, "
                    "        'analytics_backfill', :now)"
                ),
                {"org": org_id, "key": key, "st": scope_type or "organization",
                 "sid": scope_id or "", "period": period, "value": float(value),
                 "unit": unit or "", "now": now},
            )


def downgrade() -> None:
    op.drop_table("agent_daily_stats")
    op.drop_table("calendar_events")
    op.drop_table("metric_samples")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("due_date")
