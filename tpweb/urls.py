from django.urls import path

#from .views.TestCelery import test_celery

from .views.AssemblyView import AssemblyView
from .views.DownloadView import DownloadView
from .views.IndexView import IndexView
from .views.ProteinListView import ProteinListView
from .views.ProteinView import ProteinView
from .views.TestCelery import test_celery

from tpweb.views.UserViews import (
    user_detail_view,
    user_redirect_view,
    user_update_view,
)

from .admin import *

app_name = "tpwebapp"

urlpatterns = [
    #path("~redirect/", view=user_redirect_view, name="redirect"),
    #path("~update/", view=user_update_view, name="update"),
    #path("<str:username>/", view=user_detail_view, name="detail"),
    path("test_celery/", view=test_celery, name="test_celery"),
    path("",view=IndexView.as_view(),name="index"),
    path("assembly/<str:assembly_id>",view=AssemblyView.as_view(),name="assembly"),
    path("protein/<str:protein_id>",view=ProteinView.as_view(),name="protein"),
    path("protein",view=ProteinListView.as_view(),name="protein_list"),
    path("download",view=DownloadView.as_view(),name="download"),

]