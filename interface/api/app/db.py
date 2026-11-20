import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ctrlf:ctrlf@localhost:5432/ctrlf")

pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False, kwargs={"row_factory": dict_row})
