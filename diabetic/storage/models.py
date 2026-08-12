"""
diabetic/storage/models.py

SQLAlchemy ORM models for the Bio-Quant Vessel Registry.
Defines the current Telegram-keyed singleton profile schema: User, BioTraits,
CulturalMarkers, and MedicalStates. This schema is not a patient-isolation boundary.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    """Current profile record keyed by Telegram ID, not canonical patient identity."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="Unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bio_traits: Mapped[Optional["BioTraits"]] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    cultural_markers: Mapped[Optional["CulturalMarkers"]] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    medical_states: Mapped[Optional["MedicalStates"]] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id} name={self.name!r}>"


class BioTraits(Base):
    """Clinical biometrics for personalized inference."""
    __tablename__ = "bio_traits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    age: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    height_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    diabetes_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # "T1D", "T2D", "LADA"
    diagnosis_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    @property
    def bmi(self) -> Optional[float]:
        if self.height_cm and self.weight_kg and self.height_cm > 0:
            return round(self.weight_kg / ((self.height_cm / 100) ** 2), 1)
        return None

    user: Mapped["User"] = relationship(back_populates="bio_traits")


class CulturalMarkers(Base):
    """Bio-cultural context for adaptive dosing models."""
    __tablename__ = "cultural_markers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    nationality_iso: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)  # ISO 3166-1 alpha-3
    religion: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fasting_protocols: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="cultural_markers")


class MedicalStates(Base):
    """Transient clinical flags that affect prediction sensitivity."""
    __tablename__ = "medical_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    sick_mode_active: Mapped[bool] = mapped_column(Boolean, default=False)
    sick_mode_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dawn_phenomenon_active: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="medical_states")
