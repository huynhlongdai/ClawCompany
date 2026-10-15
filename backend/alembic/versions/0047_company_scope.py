"""M2e.1 — phạm vi công ty: sops.company_id, inbox_items.company_id (+ backfill).

Backfill SOP: phòng ban → công ty; người sở hữu → công ty; bước quy trình dùng SOP → công ty của quy trình.
Backfill hộp việc: task → dự án → công ty; phê duyệt → company_id / công ty người xin; báo cáo giao ban → công ty
của báo cáo; nhắc tuân thủ → công ty của hạn; còn lại → công ty người nhận. Không suy ra được thì để NULL."""
import sqlalchemy as sa
from alembic import op

revision = "0047_company_scope"
down_revision = "0046_holiday_legal_due"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for t in ("sops", "inbox_items"):
        with op.batch_alter_table(t) as batch:
            batch.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{t}_company_id", "companies", ["company_id"], ["id"])
            batch.create_index(f"ix_{t}_company_id", ["company_id"])
    b = op.get_bind()
    b.execute(sa.text("UPDATE sops SET company_id = (SELECT d.company_id FROM departments d WHERE d.id = sops.department_id) "
                      "WHERE company_id IS NULL AND department_id IS NOT NULL"))
    b.execute(sa.text("UPDATE sops SET company_id = (SELECT p.company_id FROM process_steps s JOIN processes p ON p.id = s.process_id "
                      "WHERE s.sop_id = sops.id ORDER BY s.id LIMIT 1) WHERE company_id IS NULL"))
    b.execute(sa.text("UPDATE sops SET company_id = (SELECT m.company_id FROM members m WHERE m.id = sops.owner_member_id) "
                      "WHERE company_id IS NULL AND owner_member_id IS NOT NULL"))
    b.execute(sa.text("UPDATE inbox_items SET company_id = (SELECT p.company_id FROM tasks t JOIN projects p ON p.id = t.project_id "
                      "WHERE t.id = inbox_items.task_id) WHERE company_id IS NULL AND task_id IS NOT NULL"))
    b.execute(sa.text("UPDATE inbox_items SET company_id = (SELECT r.company_id FROM rhythm_reports r WHERE CAST(r.id AS VARCHAR) = inbox_items.related_id) "
                      "WHERE company_id IS NULL AND related_type = 'rhythm_report'"))
    b.execute(sa.text("UPDATE inbox_items SET company_id = (SELECT d.company_id FROM compliance_deadlines d WHERE CAST(d.id AS VARCHAR) = inbox_items.related_id) "
                      "WHERE company_id IS NULL AND related_type = 'compliance_deadline'"))
    b.execute(sa.text("UPDATE inbox_items SET company_id = (SELECT COALESCE(a.company_id, m.company_id) FROM approvals a "
                      "LEFT JOIN members m ON m.id = a.requester_member_id WHERE CAST(a.id AS VARCHAR) = inbox_items.related_id) "
                      "WHERE company_id IS NULL AND related_type = 'approval'"))
    b.execute(sa.text("UPDATE inbox_items SET company_id = (SELECT m.company_id FROM members m WHERE m.id = inbox_items.recipient_member_id) "
                      "WHERE company_id IS NULL AND recipient_member_id IS NOT NULL"))


def downgrade() -> None:
    for t in ("sops", "inbox_items"):
        with op.batch_alter_table(t) as batch:
            batch.drop_index(f"ix_{t}_company_id")
            batch.drop_constraint(f"fk_{t}_company_id", type_="foreignkey")
            batch.drop_column("company_id")
