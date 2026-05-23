"""Shared service-layer helpers for tpweb views.

Keep this module import-light. Some pipeline entrypoints import submodules here
before Django app loading has finished, so eager imports can break with
AppRegistryNotReady.
"""

__all__ = [
    "PipelineStatus",
    "get_pipeline_status",
    "get_pipeline_status_dto",
    "annotate_pipeline_status_for_genome",
    "PUBLIC_WORKSPACE_USERNAME",
    "get_public_workspace_user",
    "resolve_workspace_user",
]


def __getattr__(name):
    if name in {
        "PipelineStatus",
        "get_pipeline_status",
        "get_pipeline_status_dto",
        "annotate_pipeline_status_for_genome",
    }:
        from tpweb.services.pipeline_status import (
            PipelineStatus,
            annotate_pipeline_status_for_genome,
            get_pipeline_status,
            get_pipeline_status_dto,
        )

        exports = {
            "PipelineStatus": PipelineStatus,
            "get_pipeline_status": get_pipeline_status,
            "get_pipeline_status_dto": get_pipeline_status_dto,
            "annotate_pipeline_status_for_genome": annotate_pipeline_status_for_genome,
        }
        return exports[name]

    if name in {
        "PUBLIC_WORKSPACE_USERNAME",
        "get_public_workspace_user",
        "resolve_workspace_user",
    }:
        from tpweb.services.workspace import (
            PUBLIC_WORKSPACE_USERNAME,
            get_public_workspace_user,
            resolve_workspace_user,
        )

        exports = {
            "PUBLIC_WORKSPACE_USERNAME": PUBLIC_WORKSPACE_USERNAME,
            "get_public_workspace_user": get_public_workspace_user,
            "resolve_workspace_user": resolve_workspace_user,
        }
        return exports[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
