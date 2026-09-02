import asyncio
from sqlalchemy import select
from diabetic.storage.engine import get_session_factory
from diabetic.storage.models import User, DeviceBinding

async def main():
    factory = get_session_factory()
    async with factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        print("USERS:", [(u.id, u.telegram_id, u.name) for u in users])
        devices = (await session.execute(select(DeviceBinding))).scalars().all()
        print("DEVICES:", [(d.id, d.user_id, d.device_name, d.custom_url_slug, d.api_secret_hash, d.is_active) for d in devices])

if __name__ == '__main__':
    asyncio.run(main())
