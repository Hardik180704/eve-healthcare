import logging


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Reduce SQLAlchemy engine noise; keep statement errors visible.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
