from sqlalchemy import create_engine

DB_URL = "postgresql://guillermo:mfte@10.121.161.225:5432/mfte_crm"

_engine = create_engine(DB_URL, pool_pre_ping=True)

def get_engine():
    return _engine