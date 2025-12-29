"""Add audit log table for compliance.

This migration adds an immutable audit log table with hash chain
for tamper detection, supporting CJIS and SOC 2 compliance requirements.

Revision ID: a1b2c3d4e5f6
Revises: 5e05da7b7d89
Create Date: 2025-12-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB

# revision identifiers
revision = "a1b2c3d4e5f6"
down_revision = "5e05da7b7d89"
branch_labels = None
depends_on = None


def upgrade():
    # Create audit_log table
    op.create_table(
        "audit_log",
        # Identity
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Timestamp
        sa.Column(
            "event_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Actor identification
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("user_role", sa.String(50), nullable=True),
        sa.Column("agency_id", UUID(as_uuid=True), nullable=True),
        sa.Column("api_key_id", sa.String(64), nullable=True),
        # Action details
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        # Request context
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("request_id", UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        # Outcome
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("outcome_reason", sa.Text, nullable=True),
        # Data changes
        sa.Column("previous_state", JSONB, nullable=True),
        sa.Column("new_state", JSONB, nullable=True),
        # Tamper detection
        sa.Column("sequence_number", sa.BigInteger, nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=True),
        sa.Column("record_hash", sa.String(64), nullable=False),
        # Metadata
        sa.Column("metadata", JSONB, nullable=True),
    )

    # Create indexes for common queries
    op.create_index(
        "idx_audit_log_timestamp",
        "audit_log",
        ["event_timestamp"],
    )
    op.create_index(
        "idx_audit_log_user",
        "audit_log",
        ["user_id"],
    )
    op.create_index(
        "idx_audit_log_resource",
        "audit_log",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "idx_audit_log_action",
        "audit_log",
        ["action"],
    )
    op.create_index(
        "idx_audit_log_agency",
        "audit_log",
        ["agency_id"],
    )
    op.create_index(
        "idx_audit_log_outcome_failures",
        "audit_log",
        ["outcome"],
        postgresql_where=sa.text("outcome != 'success'"),
    )
    op.create_index(
        "idx_audit_log_sequence",
        "audit_log",
        ["sequence_number"],
        unique=True,
    )

    # Create trigger to prevent modifications
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Audit log records cannot be modified or deleted';
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER audit_log_immutable
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_modification();
    """)

    # Add retention columns to transcription_jobs for soft delete support
    op.add_column(
        "transcription_jobs",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "transcription_jobs",
        sa.Column("deletion_policy", sa.String(100), nullable=True),
    )
    op.add_column(
        "transcription_jobs",
        sa.Column("legal_hold_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "transcription_jobs",
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
    )

    # Create legal_holds table
    op.create_table(
        "legal_holds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("case_number", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
    )

    # Index for soft delete queries
    op.create_index(
        "idx_jobs_not_deleted",
        "transcription_jobs",
        ["created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Index for retention enforcement
    op.create_index(
        "idx_jobs_retention",
        "transcription_jobs",
        ["completed_at", "deleted_at", "legal_hold_id"],
    )


def downgrade():
    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_modification()")

    # Drop indexes
    op.drop_index("idx_jobs_retention", table_name="transcription_jobs")
    op.drop_index("idx_jobs_not_deleted", table_name="transcription_jobs")

    # Drop columns from transcription_jobs
    op.drop_column("transcription_jobs", "retention_until")
    op.drop_column("transcription_jobs", "legal_hold_id")
    op.drop_column("transcription_jobs", "deletion_policy")
    op.drop_column("transcription_jobs", "deleted_at")

    # Drop legal_holds table
    op.drop_table("legal_holds")

    # Drop audit_log indexes
    op.drop_index("idx_audit_log_sequence", table_name="audit_log")
    op.drop_index("idx_audit_log_outcome_failures", table_name="audit_log")
    op.drop_index("idx_audit_log_agency", table_name="audit_log")
    op.drop_index("idx_audit_log_action", table_name="audit_log")
    op.drop_index("idx_audit_log_resource", table_name="audit_log")
    op.drop_index("idx_audit_log_user", table_name="audit_log")
    op.drop_index("idx_audit_log_timestamp", table_name="audit_log")

    # Drop audit_log table
    op.drop_table("audit_log")
