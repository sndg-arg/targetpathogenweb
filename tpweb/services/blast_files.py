"""Where BLAST query and result files are written.

They used to go under MEDIA_ROOT/blast_results. On the cluster MEDIA_ROOT is
the bind-mounted data volume, which the web container's non-root user may not
be able to write to, and the folder was created outside any error handling:
a failure there turned every BLAST search into a 500. These files are
short-lived scratch, so they live in the system temp dir unless
TPW_BLAST_RESULTS_DIR points somewhere else.
"""

import os
import tempfile
from pathlib import Path


def blast_results_dir():
    """Return the folder for BLAST files, creating it if needed. Raises
    OSError when it can't be created; callers report that to the user."""
    configured = os.environ.get("TPW_BLAST_RESULTS_DIR", "").strip()
    path = Path(configured) if configured else Path(tempfile.gettempdir()) / "tpw_blast_results"
    path.mkdir(parents=True, exist_ok=True)
    return path
