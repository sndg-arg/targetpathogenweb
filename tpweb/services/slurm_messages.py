import re


_RESOURCE_WAIT_REASONS = (
    "resources",
    "priority",
    "reqnodenotavail",
    "qos",
    "assocgrp",
    "assocmax",
    "partition",
    "licenses",
)

_RESOURCE_FAILURE_PATTERNS = (
    "job violates accounting/qos policy",
    "requested node configuration is not available",
    "nodes required for job are down, drained or reserved",
    "not enough resources",
    "requested partition configuration not available",
    "qos",
    "assocgrp",
    "association",
)


def classify_slurm_resource_message(text, *, running=False):
    raw = str(text or "").strip()
    if not raw:
        return None

    lowered = raw.lower()
    normalized = re.sub(r"[^a-z0-9]+", "", lowered)

    if any(reason in normalized for reason in _RESOURCE_WAIT_REASONS):
        if running:
            return "InterProScan is waiting for resources on the remote cluster."
        return "The remote cluster is currently full or resource-constrained."

    if any(pattern in lowered for pattern in _RESOURCE_FAILURE_PATTERNS):
        return "The remote cluster could not accept the InterProScan job because resources are not currently available."

    return None
