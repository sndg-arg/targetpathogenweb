import os

from celery import Celery
from django.conf import settings

import pkgutil
# import sndgwebapp.tasks as wtasks
# from inspect import getmembers, isfunction

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("targetpathogen")

# app.register_task(sndgapp.tasks.get_users_count())

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.

# "sndgwebapp." + x
# taskmodule = [name for _, name, _ in pkgutil.iter_modules([os.path.dirname(wtasks.__file__)])][0]
# __import__("sndgwebapp.tasks." + taskmodule)
# import importlib

from django.apps import apps

app.config_from_object(settings)
app.autodiscover_tasks(lambda: [n.name for n in apps.get_app_configs()])

app.autodiscover_tasks(packages=["tpweb.tasks.testtask"])
#app.autodiscover_tasks(packages=["sndgjobs.tasks.submit_job_task"])
