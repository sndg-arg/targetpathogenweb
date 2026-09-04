from django.contrib.auth.models import AbstractUser
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from .CelularLocalization import CelularLocalization
from .CustomParamFile import CustomParam
from .Binders import Binders
from .BioentryStructure import BioentryStructure, ExperimentalStructureXref
from .CuratedImportJob import CuratedImportJob
from .HumanProtein import HumanProtein
from .GenomeUpload import GenomeUpload
from .PipelineRun import PipelineRun, PipelineStageEvent
from .FilterPreset import FilterPreset
from .AgentChatSession import AgentChatSession
from .RequestLog import RequestLog
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
    "AgentChatSession",
    "Binders",
    "BioentryStructure",
    "CelularLocalization",
    "CustomParam",
    "CuratedImportJob",
    "ExperimentalStructureXref",
    "FilterPreset",
    "GeneReactionLink",
    "GenomeUpload",
    "HumanProtein",
    "MetabolicImportRun",
    "MetabolicPathway",
    "MetabolicReaction",
    "MetabolicReactionEdge",
    "MetabolicSpecies",
    "PipelineRun",
    "PipelineStageEvent",
    "ReactionParticipant",
    "RequestLog",
    "TPUser",
]


class TPUser(AbstractUser):
    """
    Default custom user model for SNDG.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    #: First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore
    last_name = None  # type: ignore

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
        ]

    def get_absolute_url(self):
        """Get url for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})
