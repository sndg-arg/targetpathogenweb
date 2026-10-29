from django.conf import settings
from django.db import models


class RestrictedGenome(models.Model):
    """A genome (by internal Biodatabase name) hidden from users who lack
    the tpweb.can_view_restricted_genomes permission -- see
    tpweb.services.genome_workspace.visible_genome_name_filter and
    user_can_access_genome_name, the two choke points that enforce this,
    and tpweb.services.user_permissions for how the owner grants/revokes
    the permission per user from the /users "Edit" modal.

    Rows are managed by hand via the Django admin (RestrictedGenomeAdmin) --
    e.g. to hide curated research genomes from tester/student accounts
    while regular genomes stay visible to everyone as before.
    """

    genome_name = models.CharField(max_length=255, unique=True)
    note = models.CharField(max_length=255, blank=True, default="")
    restricted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restricted_genomes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.genome_name
