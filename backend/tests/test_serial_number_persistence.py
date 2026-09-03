from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base, IpRecord


def test_serial_number_is_not_globally_unique_in_model_schema():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    try:
        session.add_all(
            [
                IpRecord(id="rec-1", ip_type="DESIGN_REGISTRATION", uploader_id="user-1", serial_number="208486"),
                IpRecord(id="rec-2", ip_type="DESIGN_REGISTRATION", uploader_id="user-1", serial_number="208486"),
            ]
        )
        session.commit()
    finally:
        session.close()

    with engine.connect() as conn:
        rows = conn.execute(IpRecord.__table__.select().where(IpRecord.serial_number == "208486")).fetchall()
        assert len(rows) == 2
