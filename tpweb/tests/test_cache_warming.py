from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from tpweb.services import assembly_workspace

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@override_settings(CACHES=LOCMEM)
class RefreshGenomeOverviewCachesTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_overwrites_stale_entries_read_by_the_overview(self):
        cache.set(assembly_workspace._metrics_cache_key("G"), {"stale": True})
        cache.set(assembly_workspace._rankings_cache_key("G", 5), ("stale", "stale"))
        with (
            mock.patch.object(
                assembly_workspace, "_build_assembly_workspace_metrics", return_value={"m": 1}
            ),
            mock.patch.object(assembly_workspace, "_score_proteins", return_value=[]) as score,
            mock.patch.object(
                assembly_workspace, "_overview_target_rankings", return_value=("top", "new")
            ),
        ):
            assembly_workspace.refresh_genome_overview_caches("G")
            self.assertEqual(assembly_workspace.build_assembly_workspace_metrics("G"), {"m": 1})
            self.assertEqual(
                assembly_workspace.get_overview_target_rankings("G", None, limit=5),
                ("top", "new"),
            )
            self.assertEqual(assembly_workspace._cached_score_proteins("G"), [])
        score.assert_called_once_with("G")
