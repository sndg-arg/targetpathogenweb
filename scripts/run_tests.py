import os
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tpwebconfig.settings")

    import django
    from django.conf import settings
    from django.test.utils import get_runner

    django.setup()
    runner_class = get_runner(settings)
    test_runner = runner_class(verbosity=2)
    failures = test_runner.run_tests(["tpweb.tests"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
