"""Single-step retrosynthesis model accuracy on the USPTO-50K test split, as
measured by Gabi (target-human-web's retrosynthesis_benchmark.html, from her
retrosynthesis_uspto50k_accuracies.csv). Static: update here when re-run."""

TEST_REACTIONS = 5005

# (name, toolkit, top-1 %, top-10 %, reactions evaluated, note)
MODELS = [
    ("Graph2SMILES", "ASKCOS", 64.835, 86.933, 5005, ""),
    ("Augmented Transformer", "ASKCOS", 61.678, 86.414, 5005, ""),
    ("Template Relevance", "ASKCOS", 43.976, 72.847, 5005, ""),
    ("RetroSim", "ASKCOS", 17.194, 29.097, 3100, "Partial run"),
]
# Planned but not run: model files no longer downloadable.
UNAVAILABLE = [
    ("Molecular Transformer, MIT mixed (+aug)", "Molecular Transformer"),
    ("Molecular Transformer, STEREO mixed (+aug)", "Molecular Transformer"),
]


def build_benchmark_context():
    models = [
        {
            "name": name,
            "toolkit": toolkit,
            "top1": round(top1, 1),
            "top10": round(top10, 1),
            "evaluated": evaluated,
            "note": note,
        }
        for name, toolkit, top1, top10, evaluated, note in MODELS
    ]
    complete = [m for m in models if m["evaluated"] == TEST_REACTIONS]
    return {
        "test_reactions": TEST_REACTIONS,
        "models": models,
        "unavailable": [{"name": n, "toolkit": t} for n, t in UNAVAILABLE],
        "best_top1": max(complete, key=lambda m: m["top1"]),
        "best_top10": max(complete, key=lambda m: m["top10"]),
    }
