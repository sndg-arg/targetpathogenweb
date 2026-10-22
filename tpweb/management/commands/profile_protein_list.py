"""Profile one render of the protein table (read-only) to find where the time goes.

Renders ProteinListView in-process for a genome, as a given user, under cProfile,
and prints total time, SQL query count/time, and the slowest functions.
Nothing is written.

Usage:
    python manage.py profile_protein_list <genome_slug> [--user EMAIL] [--query "page=2"] [--top 30]
"""

import cProfile
import io
import pstats
import time

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, reset_queries
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from tpweb.views.ProteinListView import ProteinListView


class Command(BaseCommand):
    help = "Profile one protein-table render (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("genome", help="Genome slug as in the URL, e.g. GCA_030061715.1")
        parser.add_argument(
            "--user", default="", help="Email/username to render as (default: anonymous)."
        )
        parser.add_argument("--query", default="", help='Query string, e.g. "page=2&sort=..."')
        parser.add_argument("--top", type=int, default=30, help="Functions to list (default 30).")

    def handle(self, *args, **options):
        user = AnonymousUser()
        if options["user"]:
            User = get_user_model()
            user = (
                User.objects.filter(email=options["user"]).first()
                or User.objects.filter(username=options["user"]).first()
            )
            if user is None:
                raise CommandError(f"No user {options['user']}.")

        path = f"/genome/{options['genome']}/proteins"
        if options["query"]:
            path += "?" + options["query"]
        request = RequestFactory().get(path)
        request.user = user
        SessionMiddleware(lambda r: None).process_request(request)

        view = ProteinListView.as_view()
        reset_queries()
        profiler = cProfile.Profile()
        with CaptureQueriesContext(connection) as queries:
            started = time.perf_counter()
            profiler.enable()
            response = view(request, genome=options["genome"])
            if hasattr(response, "render"):
                response.render()
            profiler.disable()
            elapsed = time.perf_counter() - started

        sql_time = sum(float(q.get("time") or 0) for q in queries.captured_queries)
        self.stdout.write(
            f"status {response.status_code}  total {elapsed:.2f}s  "
            f"SQL {len(queries.captured_queries)} queries / {sql_time:.2f}s"
        )
        slowest = sorted(
            queries.captured_queries, key=lambda q: float(q.get("time") or 0), reverse=True
        )[:5]
        for q in slowest:
            self.stdout.write(f"  {float(q.get('time') or 0):.2f}s  {q['sql'][:220]}")

        out = io.StringIO()
        stats = pstats.Stats(profiler, stream=out).sort_stats("cumulative")
        stats.print_stats(r"tpweb|human_target", options["top"])
        self.stdout.write(out.getvalue())
