"""Prepara uma base de dados de teste à parte (<base>_test), importa a amostra em tests/fixture
e arranca a API em memória. Não toca na base de dados normal.

Dentro do Docker:  docker compose exec api pytest -q
"""
import os
import shutil
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

HERE = os.path.dirname(__file__)
BASE_URL = os.environ.get("DATABASE_URL", "postgresql://ctrlf:ctrlf@localhost:5432/ctrlf")
DB_INIT_DIR = os.environ.get("DB_INIT_DIR", os.path.join(HERE, "..", "..", "db", "init"))


def with_db(url: str, name: str) -> str:
    u = urlsplit(url)
    return urlunsplit((u.scheme, u.netloc, "/" + name, u.query, u.fragment))


TEST_DB = urlsplit(BASE_URL).path.lstrip("/") + "_test"
TEST_URL = with_db(BASE_URL, TEST_DB)


def _create_database():
    with psycopg.connect(with_db(BASE_URL, "postgres"), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        for f in sorted(os.listdir(DB_INIT_DIR)):
            if f.endswith(".sql"):
                conn.execute(open(os.path.join(DB_INIT_DIR, f), encoding="utf-8").read())


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory):
    media = tmp_path_factory.mktemp("media")
    shutil.copytree(os.path.join(HERE, "fixture", "entrega"), media / "entrega")
    return media


@pytest.fixture(scope="session")
def client(media_dir):
    _create_database()
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["MEDIA_DIR"] = str(media_dir)
    os.environ["UPLOAD_DIR"] = str(media_dir / "uploads")
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    from app import importar
    importar.run(str(media_dir / "entrega"), database_url=TEST_URL)

    from fastapi.testclient import TestClient
    from app.main import app
    # o cliente de teste entra como técnico; os testes do perfil público tiram o token
    with TestClient(app, headers={"X-Tecnico-Token": "demo-ana"}) as c:
        c.media_dir = media_dir
        yield c
