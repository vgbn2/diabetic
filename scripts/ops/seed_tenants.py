import asyncio
from diabetic.storage.vessel_registry import VesselRegistry

async def main():
    reg = VesselRegistry()
    # 1. Duc Anh
    user_da = await reg.upsert_user(telegram_id=999002, name="Duc Anh")
    await reg.bind_device(
        telegram_id=999002,
        device_name="iphone12-promax",
        custom_url_slug="ducanh",
        api_secret_hash="5aff4eb03c7be0cecd038d60e620a23850920cbf"
    )
    print("Seeded Duc Anh (iphone12-promax, slug=ducanh)")

    # 2. Tam
    user_tam = await reg.upsert_user(telegram_id=7291809157, name="Tam")
    await reg.bind_device(
        telegram_id=7291809157,
        device_name="tam-cgm",
        custom_url_slug="tam",
        api_secret_hash="7ff4199c0da9ce17c0c1b82cb97cf336e4f3583c"
    )
    print("Seeded Tam (slug=tam)")

if __name__ == '__main__':
    asyncio.run(main())
