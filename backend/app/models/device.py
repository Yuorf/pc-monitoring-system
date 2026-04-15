from sqlalchemy import Column, DateTime, Integer, String

from app.core.database import Base


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    cpu = Column(String)
    gpu = Column(String)
    created_at = Column(DateTime)
