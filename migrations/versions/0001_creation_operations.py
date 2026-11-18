"""Persist resumable campaign creation operations."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "creation_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_key", sa.String(128), nullable=False, unique=True),
        sa.Column("alias", sa.String(64), nullable=False, unique=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("campaign_id", sa.Integer()),
        sa.Column("geo_stream_id", sa.Integer()),
        sa.Column("offer_stream_id", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("creation_operations")
