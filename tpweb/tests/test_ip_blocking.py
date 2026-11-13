from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tpweb.models.BlockedIP import BlockedIP
from tpweb.services.ip_blocking import block_ip, is_ip_blocked, unblock_ip


class IpBlockingTests(TestCase):
    def setUp(self):
        # LocMemCache is process-global, not reset between tests the way the
        # DB transaction is -- clear it so a prior test's cached blocked-set
        # can't leak into this one.
        cache.clear()

    def test_block_ip_makes_is_ip_blocked_true(self):
        self.assertFalse(is_ip_blocked("203.0.113.5"))

        block_ip("203.0.113.5")

        self.assertTrue(is_ip_blocked("203.0.113.5"))

    def test_unblock_ip_makes_is_ip_blocked_false_again(self):
        block_ip("203.0.113.6")
        self.assertTrue(is_ip_blocked("203.0.113.6"))

        unblock_ip("203.0.113.6")

        self.assertFalse(is_ip_blocked("203.0.113.6"))

    def test_block_ip_is_idempotent_and_updates_reason(self):
        owner = get_user_model().objects.create_user(
            username="ip-block-owner", password="x", is_superuser=True
        )
        block_ip("203.0.113.8", blocked_by=owner, reason="first pass")

        block_ip("203.0.113.8", blocked_by=owner, reason="second pass")

        self.assertEqual(BlockedIP.objects.filter(ip="203.0.113.8").count(), 1)
        self.assertEqual(BlockedIP.objects.get(ip="203.0.113.8").reason, "second pass")

    def test_unblock_ip_returns_false_for_an_ip_that_was_never_blocked(self):
        self.assertFalse(unblock_ip("203.0.113.9"))

    def test_is_ip_blocked_is_false_for_empty_or_missing_ip(self):
        self.assertFalse(is_ip_blocked(""))
        self.assertFalse(is_ip_blocked(None))


class BlockedIPAdminDeleteTests(TestCase):
    """The admin is the only place left to unblock an IP (the dashboard's
    Unblock button is gone -- blocking is fully automatic). Deleting a
    BlockedIP row through the plain ORM/admin path would bypass the
    middleware's cached blocked-IP set, leaving it wrongly 403'd for up to
    BLOCKED_IPS_CACHE_TTL_SECONDS -- BlockedIPAdmin routes delete through
    unblock_ip() specifically to avoid that."""

    def setUp(self):
        cache.clear()
        from django.contrib.admin.sites import AdminSite

        from tpweb.admin.BlockedIPAdmin import BlockedIPAdmin

        self.admin = BlockedIPAdmin(BlockedIP, AdminSite())

    def test_delete_model_invalidates_the_cache(self):
        block_ip("203.0.113.40")
        self.assertTrue(is_ip_blocked("203.0.113.40"))
        obj = BlockedIP.objects.get(ip="203.0.113.40")

        self.admin.delete_model(None, obj)

        self.assertFalse(BlockedIP.objects.filter(ip="203.0.113.40").exists())
        self.assertFalse(is_ip_blocked("203.0.113.40"))

    def test_delete_queryset_invalidates_the_cache_for_every_row(self):
        block_ip("203.0.113.41")
        block_ip("203.0.113.42")
        qs = BlockedIP.objects.filter(ip__in=["203.0.113.41", "203.0.113.42"])

        self.admin.delete_queryset(None, qs)

        self.assertFalse(is_ip_blocked("203.0.113.41"))
        self.assertFalse(is_ip_blocked("203.0.113.42"))
