from django.contrib.auth.models import AbstractUser
from django.db.models import BooleanField, CharField, TextChoices
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from .CelularLocalization import CelularLocalization
from .CustomParamFile import CustomParam
from .Binders import Binders
from .BioentryStructure import BioentryStructure, ExperimentalStructureXref
from .CuratedImportJob import CuratedImportJob
from .BlockedIP import BlockedIP
from .GenomeUpload import GenomeUpload
from .PipelineRun import PipelineRun, PipelineStageEvent
from .FilterPreset import FilterPreset
from .AgentChatSession import AgentChatSession
from .AgentChatMessageLog import AgentChatMessageLog
from .RequestLog import RequestLog
from .RestrictedGenome import RestrictedGenome
from .Metabolism import (
    MetabolicPathway,
    MetabolicReaction,
    GeneReactionLink,
    MetabolicReactionEdge,
    MetabolicImportRun,
    MetabolicSpecies,
    ReactionParticipant,
)

__all__ = [
    "AgentChatMessageLog",
    "AgentChatSession",
    "Binders",
    "BioentryStructure",
    "BlockedIP",
    "CelularLocalization",
    "CustomParam",
    "CuratedImportJob",
    "ExperimentalStructureXref",
    "FilterPreset",
    "GeneReactionLink",
    "GenomeUpload",
    "MetabolicImportRun",
    "MetabolicPathway",
    "MetabolicReaction",
    "MetabolicReactionEdge",
    "MetabolicSpecies",
    "PipelineRun",
    "PipelineStageEvent",
    "ReactionParticipant",
    "RequestLog",
    "RestrictedGenome",
    "TPUser",
]


class TPUser(AbstractUser):
    """
    Default custom user model for SNDG.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    class Role(TextChoices):
        # Keys deliberately match tpweb.services.user_permissions.PROFILE_PRESETS'
        # keys 1:1 -- picking a role in /users applies that preset's permission
        # bundle and this label together. Admin ("puedo hacer todo") isn't a
        # choice here -- that's is_superuser, which already bypasses every
        # has_perm() check regardless of role.
        BASIC = "basic", _("Basic")
        GATES_COLLABORATOR = "gates_collaborator", _("Gates collaborator")
        GATES_CONSUMER = "gates_consumer", _("Gates consumer")
        STUDENT = "student", _("Alumnos / testers")

    #: First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore
    last_name = None  # type: ignore
    role = CharField(_("Role"), max_length=32, choices=Role.choices, default=Role.BASIC)
    # Set at signup by the "Solicitar acceso de colaborador" checkbox
    # (tpweb.forms.UserSignupForm) -- surfaces a chip on /users so the owner
    # can spot who's asking for a role upgrade among self-serve Basic
    # signups. Cleared automatically once the owner moves role off BASIC
    # (see UserManagementView.post's update_permissions branch).
    wants_collaborator_access = BooleanField(_("Requested collaborator access"), default=False)

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        # Named capabilities an approved (is_staff) collaborator can be
        # individually granted, on top of the baseline "can upload a
        # genome" everyone approved gets automatically -- toggled per user
        # via the "user permissions" widget already on the Django admin's
        # user change form (tpweb/admin/UserAdmin.py), no extra UI needed.
        # A superuser passes every permission check automatically
        # (Django's ModelBackend.has_perm()), so the owner is unaffected.
        permissions = [
            ("can_upload_genome", "Can upload a new genome"),
            ("can_view_activity", "Can view the Activity dashboard"),
            (
                "can_curated_import",
                "Can run curated external imports and upload large files",
            ),
            ("can_manage_formulas", "Can create, edit, and delete scoring formulas"),
            ("can_run_blast", "Can run BLAST searches"),
            ("can_manage_custom_params", "Can create and edit custom evidence parameters"),
            ("can_use_agent_chat", "Can use the AI assistant"),
            (
                "can_view_restricted_genomes",
                "Can view genomes marked as restricted (curated/research)",
            ),
            ("can_view_human_targets", "Can view the Human Targets section"),
        ]

    def get_absolute_url(self):
        """Get url for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})
