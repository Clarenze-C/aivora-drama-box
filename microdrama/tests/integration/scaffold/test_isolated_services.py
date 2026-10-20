"""The isolated test servers are real, private and loopback-only."""

from __future__ import annotations

import threading

import psycopg
import pytest
import redis

pytestmark = [pytest.mark.db, pytest.mark.redis]


def test_postgres_is_real_and_loopback_only(pg_server_dsn: str) -> None:
    assert "127.0.0.1" in pg_server_dsn
    with psycopg.connect(pg_server_dsn, autocommit=True) as conn:
        version = conn.execute("show server_version").fetchone()[0]
        assert version.startswith("16")
        listen = conn.execute("show listen_addresses").fetchone()[0]
        assert listen == "127.0.0.1"


def test_postgres_row_locks_block_a_second_transaction(pg_server_dsn: str) -> None:
    """Proves FOR UPDATE really serializes writers (needed by budget tests)."""
    with psycopg.connect(pg_server_dsn, autocommit=True) as admin:
        admin.execute("drop table if exists scaffold_lock_probe")
        admin.execute("create table scaffold_lock_probe (id int primary key, n int not null)")
        admin.execute("insert into scaffold_lock_probe values (1, 0)")

    holder = psycopg.connect(pg_server_dsn)
    holder.execute("select n from scaffold_lock_probe where id = 1 for update")
    blocked = threading.Event()
    finished = threading.Event()

    def contender() -> None:
        with psycopg.connect(pg_server_dsn) as c:
            c.execute("set lock_timeout = '5s'")
            blocked.set()
            c.execute("select n from scaffold_lock_probe where id = 1 for update")
            finished.set()

    t = threading.Thread(target=contender)
    t.start()
    blocked.wait(5)
    assert not finished.wait(0.5), "second FOR UPDATE must wait while the row is locked"
    holder.rollback()
    holder.close()
    t.join(10)
    assert finished.is_set()


def test_redis_is_real_and_loopback_only(redis_url: str) -> None:
    assert "127.0.0.1" in redis_url
    client = redis.Redis.from_url(redis_url)
    assert client.ping()
    assert client.config_get("bind")["bind"] == "127.0.0.1"
    assert client.config_get("save")["save"] == ""
