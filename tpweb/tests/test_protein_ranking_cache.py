from types import SimpleNamespace

from django.test import TestCase

from bioseq.models.Bioentry import Bioentry
from tpweb.views.ProteinListView import _ranking_cache_key


class ProteinRankingCacheKeyTests(TestCase):
    def key(self, user_pk=1, names=("b", "a"), sort_dir="desc", queryset=None):
        return _ranking_cache_key(
            SimpleNamespace(pk=user_pk),
            queryset if queryset is not None else Bioentry.objects.filter(accession="X"),
            "",
            {"param": {"yes": 1.0}},
            False,
            "Druggability",
            False,
            sort_dir,
            set(names),
        )

    def test_same_inputs_give_the_same_key_whatever_the_set_order(self):
        self.assertEqual(self.key(names=("a", "b")), self.key(names=("b", "a")))

    def test_any_ranking_input_changes_the_key(self):
        base = self.key()
        self.assertNotEqual(base, self.key(sort_dir="asc"))
        self.assertNotEqual(base, self.key(user_pk=2))
        self.assertNotEqual(base, self.key(names=("a",)))
        self.assertNotEqual(base, self.key(queryset=Bioentry.objects.filter(accession="Y")))

    def test_empty_filter_is_not_cached(self):
        self.assertIsNone(self.key(queryset=Bioentry.objects.filter(pk__in=[])))
