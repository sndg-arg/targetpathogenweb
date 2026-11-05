"""
WSGI config for tpweb project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tpwebconfig.settings")

application = get_wsgi_application()

# Import the URLconf (and every view/service module it pulls in, ~5 s) while
# the gunicorn worker boots, not inside the first request it serves.
from django.urls import get_resolver  # noqa: E402

get_resolver().check()
