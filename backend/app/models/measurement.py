from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer

from app.core.database import Base


class Measurement(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    cpu_usage = Column(Float)
    gpu_usage = Column(Float, nullable=True)
    ram_usage = Column(Float)
    disk_usage = Column(Float)
    recorded_at = Column(DateTime)
