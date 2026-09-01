import unittest
import os
import shutil
import tempfile
import asyncio
from diabetic.utils.ip_resolver import normalize_ip, matches_ip_rule
from diabetic.storage.engine import init_db, close_db
from diabetic.storage.vessel_registry import VesselRegistry


class TestTenantDualStackIP(unittest.TestCase):
    def test_ip_normalization(self):
        # IPv4
        self.assertEqual(str(normalize_ip("192.168.4.150")), "192.168.4.150")
        self.assertEqual(str(normalize_ip("100.79.196.24")), "100.79.196.24")

        # IPv6 / Tailscale ULA
        self.assertEqual(str(normalize_ip("fd7a:115c:a1e0::432c:a224")), "fd7a:115c:a1e0::432c:a224")
        self.assertEqual(str(normalize_ip("[fd7a:115c:a1e0::432c:a224]")), "fd7a:115c:a1e0::432c:a224")
        self.assertEqual(str(normalize_ip("fd7a:115c:a1e0::432c:a224%tailscale0")), "fd7a:115c:a1e0::432c:a224")
        self.assertEqual(str(normalize_ip("::1")), "::1")

        # Invalid
        self.assertIsNone(normalize_ip("not-an-ip"))
        self.assertIsNone(normalize_ip(""))

    def test_ip_matching_rules(self):
        # Exact IPv4 match
        self.assertTrue(matches_ip_rule("192.168.4.150", "192.168.4.150"))
        self.assertFalse(matches_ip_rule("192.168.4.151", "192.168.4.150"))

        # CIDR IPv4 Subnet
        self.assertTrue(matches_ip_rule("192.168.4.150", "192.168.4.0/24"))
        self.assertTrue(matches_ip_rule("100.79.196.55", "100.64.0.0/10"))
        self.assertFalse(matches_ip_rule("192.168.5.150", "192.168.4.0/24"))

        # Exact IPv6 / Tailscale ULA
        self.assertTrue(matches_ip_rule("fd7a:115c:a1e0::432c:a224", "fd7a:115c:a1e0::432c:a224"))
        self.assertTrue(matches_ip_rule("[fd7a:115c:a1e0::432c:a224%eth0]", "fd7a:115c:a1e0::432c:a224"))

        # CIDR IPv6 Subnet
        self.assertTrue(matches_ip_rule("fd7a:115c:a1e0::432c:a224", "fd7a:115c:a1e0::/48"))
        self.assertFalse(matches_ip_rule("2001:db8::1", "fd7a:115c:a1e0::/48"))


class TestDeviceBindingRegistry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_vessel.db")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{self.db_path}"
        await init_db()
        self.registry = VesselRegistry()

    async def asyncTearDown(self):
        await close_db()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_device_binding_and_resolution(self):
        # Register user
        user = await self.registry.upsert_user(telegram_id=123456789, name="Duong Minh Tam")

        # Bind Tailscale IPv6 device
        binding = await self.registry.bind_device(
            telegram_id=123456789,
            device_name="Tam Phone",
            custom_url_slug="tam",
            ip_address="fd7a:115c:a1e0::432c:a224",
        )
        self.assertIsNotNone(binding)
        self.assertEqual(binding.custom_url_slug, "tam")

        # Resolve by slug
        resolved_by_slug = await self.registry.resolve_tenant_by_slug("tam")
        self.assertIsNotNone(resolved_by_slug)
        self.assertEqual(resolved_by_slug.telegram_id, 123456789)

        # Resolve by Tailscale IPv6
        resolved_by_ip = await self.registry.resolve_tenant_by_ip("fd7a:115c:a1e0::432c:a224%tailscale0")
        self.assertIsNotNone(resolved_by_ip)
        self.assertEqual(resolved_by_ip.telegram_id, 123456789)

        # Non-matching IP returns None
        self.assertIsNone(await self.registry.resolve_tenant_by_ip("192.168.1.99"))


if __name__ == "__main__":
    unittest.main()
