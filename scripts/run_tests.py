import os
import sys
import unittest
from pathlib import Path


class DisableMigrations(dict):
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


def _run_pipeline_tests(project_root: Path) -> bool:
    """Run the plain-unittest suite under pipeline/tests.

    pipeline/ is not a Django app (no __init__.py, no models) -- it's a
    standalone script directory invoked as a subprocess by the orchestrator,
    so its modules import each other by bare name (`from run_pipeline import
    ...`). Tests need pipeline/ itself on sys.path to import the same way.
    """
    pipeline_dir = project_root / "pipeline"
    if str(pipeline_dir) not in sys.path:
        sys.path.insert(0, str(pipeline_dir))

    suite = unittest.TestLoader().discover(
        start_dir=str(pipeline_dir / "tests"),
        pattern="test_*.py",
        top_level_dir=str(pipeline_dir),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tpwebconfig.settings")

    import django
    from django.conf import settings
    from django.test.utils import get_runner

    settings.MIGRATION_MODULES = DisableMigrations()
    django.setup()
    runner_class = get_runner(settings)
    # interactive=False: this runs unattended (CI, `docker exec`, pre-push
    # hook) with no tty to answer Django's "drop and recreate?" prompt --
    # without it, a leftover test DB from a killed prior run hangs forever
    # waiting on stdin. keepdb=True reuses that DB instead of dropping it,
    # which is also just faster on repeat runs.
    test_runner = runner_class(verbosity=2, interactive=False, keepdb=True)
    failures = test_runner.run_tests(["tpweb"])
    if failures:
        return 1

    return 0 if _run_pipeline_tests(project_root) else 1


if __name__ == "__main__":
    raise SystemExit(main())
