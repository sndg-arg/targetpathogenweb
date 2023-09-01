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
from django.urls import include, path

from tpweb.views.UserViews import user_redirect_view

import tpweb.admin
str(tpweb.admin) # Do not remove, it loads the admin models

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("~redirect/", view=user_redirect_view, name="redirect"),
    path("", include("tpweb.urls")),
    path("accounts/", include("allauth.urls")),

    path('ckeditor/', include('ckeditor_uploader.urls')),
] if not settings.WORKERPROC else []


if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns