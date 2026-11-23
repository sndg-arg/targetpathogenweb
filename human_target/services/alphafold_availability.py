"""Classify AFDB metadata conservatively before any model is downloaded."""


def classify_predictions(accession, sequence, payload):
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        return {"status": "invalid_response", "models": []}
    if not payload:
        return {"status": "not_found", "models": []}
    models = []
    for item in payload:
        remote_sequence = item.get("uniprotSequence")
        matches = (
            remote_sequence == sequence
            if sequence and isinstance(remote_sequence, str) and remote_sequence
            else None
        )
        full_length = (
            (item.get("uniprotStart") == 1 and item.get("uniprotEnd") == len(sequence))
            if sequence
            else False
        )
        models.append(
            {
                "entry_id": item.get("entryId"),
                "accession": item.get("uniprotAccession"),
                "version": item.get("latestVersion"),
                "cif_url": item.get("cifUrl"),
                "sequence_matches": matches,
                "full_length": full_length,
                "eligible": bool(
                    item.get("uniprotAccession") == accession
                    and matches is True
                    and full_length
                    and item.get("cifUrl")
                ),
            }
        )
    if any(model["eligible"] for model in models):
        status = "available_matching"
    elif all(model["sequence_matches"] is False for model in models):
        status = "sequence_mismatch"
    else:
        status = "needs_review"
    return {"status": status, "models": models}
