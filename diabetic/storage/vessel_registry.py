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
from diabetic.storage.models import BioTraits, CulturalMarkers, MedicalStates, User, DeviceBinding
from diabetic.utils.ip_resolver import matches_ip_rule, normalize_ip

logger = logging.getLogger("Bio-Quant.VesselRegistry")

# Single source of truth for trait fields a client (TWA GUI) may write.
# Anything outside this set is dropped before it reaches the ORM — the
# mass-assignment guard for update_user_traits().
_ALLOWED_TRAIT_FIELDS = frozenset(
    {"age", "height_cm", "weight_kg", "diabetes_type", "diagnosis_year"}
)


class VesselRegistry:
    """
    Async service for managing per-user metabolic profiles.
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
    # Device Binding & Multi-Tenant Ingress Mapping
    # -------------------------------------------------------------------------

    async def bind_device(
        self,
        telegram_id: int,
        device_name: str,
        custom_url_slug: str,
        ip_address: Optional[str] = None,
        api_secret_hash: Optional[str] = None,
    ) -> Optional[DeviceBinding]:
        """
        Binds a physical device / dual-stack IP address and custom slug to a user tenant.
        """
        async with self._session() as session:
            user_result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                logger.warning("[Registry] bind_device: User %s not found.", telegram_id)
                return None

            # Check if custom slug is already claimed by another device
            slug_clean = custom_url_slug.strip().lower()
            existing_slug_res = await session.execute(
                select(DeviceBinding).where(DeviceBinding.custom_url_slug == slug_clean)
            )
            binding = existing_slug_res.scalar_one_or_none()

            if binding is None:
                binding = DeviceBinding(
                    user_id=user.id,
                    device_name=device_name,
                    custom_url_slug=slug_clean,
                    ip_address=ip_address.strip() if ip_address else None,
                    api_secret_hash=api_secret_hash,
                )
                session.add(binding)
            else:
                if binding.user_id != user.id:
                    raise ValueError(f"Custom URL slug '{slug_clean}' is already assigned to another user.")
                binding.device_name = device_name
                binding.ip_address = ip_address.strip() if ip_address else None
                if api_secret_hash:
                    binding.api_secret_hash = api_secret_hash
                binding.is_active = True

            await session.commit()
            await session.refresh(binding)
            logger.info(
                "[Registry] Bound device '%s' (slug: %s, ip: %s) to user %s",
                device_name,
                slug_clean,
                ip_address,
                telegram_id,
            )
            return binding

    async def resolve_tenant_by_slug(self, custom_url_slug: str) -> Optional[User]:
        """Resolves User tenant record by custom URL slug."""
        if not custom_url_slug:
            return None
        slug_clean = custom_url_slug.strip().lower()
        async with self._session() as session:
            result = await session.execute(
                select(User)
                .join(DeviceBinding, DeviceBinding.user_id == User.id)
                .where(DeviceBinding.custom_url_slug == slug_clean, DeviceBinding.is_active == True)
            )
            return result.scalar_one_or_none()

    async def resolve_tenant_by_ip(self, client_ip: str) -> Optional[User]:
        """
        Resolves User tenant record by inspecting client IP against all active device bindings.
        Supports dual-stack IPv4 (LAN, Tailscale) and IPv6 ULA matching.
        """
        if not client_ip:
            return None

        async with self._session() as session:
            result = await session.execute(
                select(DeviceBinding, User)
                .join(User, DeviceBinding.user_id == User.id)
                .where(DeviceBinding.is_active == True, DeviceBinding.ip_address.is_not(None))
            )
            rows = result.all()
            for binding, user in rows:
                if binding.ip_address and matches_ip_rule(client_ip, binding.ip_address):
                    return user
            return None


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
