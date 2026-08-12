"""
diabetic/storage/vessel_registry.py

Service layer for bio-cultural data management.
Provides async CRUD operations for the Vessel Registry schema.
"""
import logging
import os
from typing import Optional
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diabetic.storage.engine import get_session_factory
from diabetic.storage.models import BioTraits, CulturalMarkers, MedicalStates, User

logger = logging.getLogger("Bio-Quant.VesselRegistry")

# Single source of truth for trait fields a client (TWA GUI) may write.
# Anything outside this set is dropped before it reaches the ORM — the
# mass-assignment guard for update_user_traits().
_ALLOWED_TRAIT_FIELDS = frozenset(
    {"age", "height_cm", "weight_kg", "diabetes_type", "diagnosis_year"}
)


class VesselRegistry:
    """
    Async service for the current Telegram-keyed profile records.
    Registry membership is not authorization or clinical runtime isolation.
    All methods are non-blocking — safe to call from the coordinator event loop.
    """

    def _session(self) -> AsyncSession:
        return get_session_factory()()

    # -------------------------------------------------------------------------
    # User Identity
    # -------------------------------------------------------------------------

    async def upsert_user(self, telegram_id: int, name: str = "Unknown") -> User:
        """Register a new user or update their display name."""
        async with self._session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user is None:
                user = User(telegram_id=telegram_id, name=name)
                session.add(user)
                logger.info("[Registry] Registered new user: %s (%s)", name, telegram_id)
            else:
                user.name = name
            await session.commit()
            await session.refresh(user)
            return user

    async def get_user(self, telegram_id: int) -> Optional[User]:
        """Retrieve a user record by Telegram ID."""
        async with self._session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # Bio Traits
    # -------------------------------------------------------------------------

    async def update_biometrics(
        self,
        telegram_id: int,
        age: Optional[float] = None,
        height_cm: Optional[float] = None,
        weight_kg: Optional[float] = None,
        diabetes_type: Optional[str] = None,
        diagnosis_year: Optional[int] = None,
    ) -> Optional[BioTraits]:
        """Upsert biometric data for a user. Only provided fields are updated."""
        async with self._session() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                logger.warning("[Registry] update_biometrics: User %s not found.", telegram_id)
                return None

            traits_result = await session.execute(
                select(BioTraits).where(BioTraits.user_id == user.id)
            )
            traits = traits_result.scalar_one_or_none()
            if traits is None:
                traits = BioTraits(user_id=user.id)
                session.add(traits)

            if age is not None:
                traits.age = age
            if height_cm is not None:
                traits.height_cm = height_cm
            if weight_kg is not None:
                traits.weight_kg = weight_kg
            if diabetes_type is not None:
                traits.diabetes_type = diabetes_type
            if diagnosis_year is not None:
                traits.diagnosis_year = diagnosis_year

            await session.commit()
            await session.refresh(traits)
            logger.info("[Registry] Biometrics updated for user %s (BMI: %s)", telegram_id, traits.bmi)
            return traits

    async def get_biometrics(self, telegram_id: int) -> Optional[BioTraits]:
        """Retrieve bio-trait profile for a user."""
        async with self._session() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                return None
            result = await session.execute(
                select(BioTraits).where(BioTraits.user_id == user.id)
            )
            return result.scalar_one_or_none()

    async def update_user_traits(self, telegram_id: int, traits: dict) -> bool:
        """
        Whitelisted bio-trait update from the TWA GUI. Filters `traits` to known
        BioTraits columns (drops unknown keys and None values — no mass-assignment),
        then delegates to update_biometrics. Returns True iff something was written.
        """
        filtered = {
            k: v for k, v in (traits or {}).items()
            if k in _ALLOWED_TRAIT_FIELDS and v is not None
        }
        if not filtered:
            return False
        result = await self.update_biometrics(telegram_id, **filtered)
        return result is not None

    # -------------------------------------------------------------------------
    # Medical States
    # -------------------------------------------------------------------------

    async def set_sick_mode(self, telegram_id: int, active: bool, expires_at: Optional[datetime] = None) -> None:
        """Toggle sick mode for dynamic insulin sensitivity adjustment."""
        async with self._session() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()
            if user is None:
                return

            state_result = await session.execute(select(MedicalStates).where(MedicalStates.user_id == user.id))
            state = state_result.scalar_one_or_none()
            if state is None:
                state = MedicalStates(user_id=user.id)
                session.add(state)

            state.sick_mode_active = active
            state.sick_mode_expires_at = expires_at
            await session.commit()
            logger.info("[Registry] Sick mode set to %s for user %s", active, telegram_id)


    async def get_medical_state(self, telegram_id: int) -> Optional[MedicalStates]:
        """Retrieve dynamic medical state for a user."""
        async with self._session() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()
            if user is None:
                return None
            result = await session.execute(
                select(MedicalStates).where(MedicalStates.user_id == user.id)
            )
            return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # Legacy Migration from .env
    # -------------------------------------------------------------------------

    async def migrate_from_env(self) -> None:
        """
        One-time migration: Read legacy .env bio-traits and upsert into SQL registry.
        Runs at startup. Safe to call repeatedly — checks for existing records.
        """
        telegram_id_str = os.environ.get("TELEGRAM_CHAT_ID")
        if not telegram_id_str:
            logger.debug("[Registry] No TELEGRAM_CHAT_ID in .env — skipping migration.")
            return

        telegram_id = int(telegram_id_str)

        # Check if already migrated
        async with self._session() as session:
            from sqlalchemy.orm import selectinload
            result = await session.execute(
                select(User).options(selectinload(User.bio_traits)).where(User.telegram_id == telegram_id)
            )
            existing = result.scalar_one_or_none()
            
        if existing and existing.bio_traits:
            logger.debug("[Registry] User %s already in registry — skipping migration.", telegram_id)
            return

        # Register from .env
        await self.upsert_user(telegram_id=telegram_id, name="Primary Vessel")

        # Migrate any bio-traits that were previously hardcoded
        await self.update_biometrics(
            telegram_id=telegram_id,
            age=float(os.environ.get("PATIENT_AGE", 0)) or None,
            weight_kg=float(os.environ.get("PATIENT_WEIGHT_KG", 0)) or None,
            height_cm=float(os.environ.get("PATIENT_HEIGHT_CM", 0)) or None,
            diabetes_type=os.environ.get("PATIENT_DIABETES_TYPE", "T1D"),
        )
        logger.info("[Registry] Legacy .env user migrated to SQL for telegram_id=%s", telegram_id)
