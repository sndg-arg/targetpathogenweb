from types import SimpleNamespace

from django.test import SimpleTestCase

from human_target.services.human_targets import HUMAN_BIODATABASE_NAME, HUMAN_GENOME_SLUG
from tpweb.services.genome_workspace import user_can_access_genome_name


class HumanStorageAccessTests(SimpleTestCase):
    def test_human_proteins_need_the_human_targets_permission(self):
        # A shared /protein/<id> link to a human protein must not open for
        # someone without Human Targets access.
        user = SimpleNamespace(has_perm=lambda perm: False)
        for name in (HUMAN_GENOME_SLUG, HUMAN_BIODATABASE_NAME):
            self.assertFalse(user_can_access_genome_name(user, name))
