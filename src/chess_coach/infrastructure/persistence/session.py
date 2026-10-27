from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Call factory.begin() for an atomic unit of work owned by the caller.

    Successful context exit commits; exceptional exit rolls back. Both close
    the session. A plain factory() session requires an explicit commit.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)
