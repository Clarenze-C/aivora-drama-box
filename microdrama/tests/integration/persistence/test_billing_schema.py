import uuid

import psycopg
import pytest

from microdrama.persistence import migrate

pytestmark = pytest.mark.db


def test_billing_migration_creates_append_only_reconciliation_tables(pg_server_dsn: str) -> None:
    name = f"md_bill_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(pg_server_dsn, dbname=name)
    assert {"0022", "0023"} <= set(migrate(dsn))
    with psycopg.connect(dsn) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }
        assert {
            "runpod_billing_queries",
            "runpod_billing_buckets",
            "runpod_billing_allocations",
            "runpod_billing_invoice_verifications",
            "runpod_billing_budget_postings",
            "runpod_billing_recovery_resolutions",
            "runpod_billing_budget_finalizations",
            "runpod_billing_period_evidence",
            "runpod_billing_query_skipped_buckets",
        } <= tables
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT tgname FROM pg_trigger WHERE tgname LIKE 'runpod_billing_%_append_only'"
            )
        }
        assert len(triggers) == 9
