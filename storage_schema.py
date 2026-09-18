# -*- coding: utf-8 -*-
"""Idempotent database migration for hybrid media storage."""
import os
import psycopg

DATABASE_URL = os.environ.get('DATABASE_URL', '')


def ensure_storage_schema(connection=None):
    own = connection is None
    c = connection or psycopg.connect(DATABASE_URL)
    try:
        c.execute("alter table assets add column if not exists storage_key text")
        c.execute("alter table assets add column if not exists storage_backend text not null default 'database'")
        c.execute("alter table assets add column if not exists checksum_sha256 text")
        c.execute("alter table assets alter column data drop not null")
        c.execute("create index if not exists idx_assets_storage_key on assets(storage_key) where storage_key is not null")
        if own:
            c.commit()
    finally:
        if own:
            c.close()
