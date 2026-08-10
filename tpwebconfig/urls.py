"""sndgweb URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.conf import settings
from django.http import Http404
from django.urls import include, path, re_path

from tpweb.views.UserViews import user_redirect_view

import tpweb.admin

str(tpweb.admin)  # Do not remove, it loads the admin models


def _password_reset_disabled(request, *args, **kwargs):
    raise Http404("Password reset is disabled on this platform.")


urlpatterns = (
    [
        path(settings.ADMIN_URL, admin.site.urls),
        path("~redirect/", view=user_redirect_view, name="redirect"),
        path("", include("tpweb.urls")),
        # Self-service password reset is disabled. These shadow allauth's own
        # password-reset URLs (same paths/names) before its include() below, so
        # every other allauth URL (login, logout, signup, email management)
        # keeps working normally -- only these four routes 404.
        path("accounts/password/reset/", _password_reset_disabled, name="account_reset_password"),
        path(
            "accounts/password/reset/done/",
            _password_reset_disabled,
            name="account_reset_password_done",
        ),
        re_path(
            r"^accounts/password/reset/key/(?P<uidb36>[0-9A-Za-z]+)-(?P<key>.+)/$",
            _password_reset_disabled,
            name="account_reset_password_from_key",
        ),
        path(
            "accounts/password/reset/key/done/",
            _password_reset_disabled,
            name="account_reset_password_from_key_done",
        ),
        path("accounts/", include("allauth.urls")),
        path("ckeditor/", include("ckeditor_uploader.urls")),
    ]
    if not settings.WORKERPROC
    else []
)


if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
