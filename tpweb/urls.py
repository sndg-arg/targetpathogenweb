from django.urls import path

#from .views.TestCelery import test_celery

from .views.AssemblyView import AssemblyView
from .views.DownloadView import DownloadView
from .views.GenomesView import GenomesView
from .views.AssemblyView import genome_selection_view
from .views.IndexView import IndexView
from .views.ProteinListView import ProteinListView
from .views.ProteinView import ProteinView
from .views.StructureExportView import StructureExportView
from .views.StructureRawView import StructureRawView
from .views.StructureView import StructureView


from .views.TestCelery import test_celery

from django.conf.urls.static import static

from django.conf import settings
from django.contrib.auth.decorators import login_required

from tpweb.views.UserViews import (
    user_detail_view,
    user_redirect_view,
    user_update_view,
)

from .admin import *

app_name = "tpwebapp"
from django.shortcuts import render
def untestview(request):
    return render(request, 'test.html')

urlpatterns = [
    #path("~redirect/", view=user_redirect_view, name="redirect"),
    #path("~update/", view=user_update_view, name="update"),
    #path("<str:username>/", view=user_detail_view, name="detail"),
    #path("test_celery/", view=test_celery, name="test_celery"),

    #path("",view=login_required(IndexView.as_view()),name="index"),
    path("",view=IndexView.as_view(),name="index"),
    path('assembly/', genome_selection_view, name='genome-selection'),
    path("assembly/<str:assembly_id>",view=AssemblyView.as_view(),name="assembly"),
    path("protein/<int:protein_id>",view=ProteinView.as_view(),name="protein"),
    path("assembly/<str:assembly_name>/protein",view=ProteinListView.as_view(),name="protein_list"),
    path("download",view=DownloadView.as_view(),name="download"),
    path("genomes",view=GenomesView.as_view(),name="genomes_list"),
    path("structure_raw/<int:struct_id>",view=StructureRawView.as_view(),name="structure_raw"),
    path("structure_export/<int:struct_id>",view=StructureExportView.as_view(),name="structure_export"),

    path("structure/<int:struct_id>",view=StructureView.as_view(),name="structure"),
    path("test",view=untestview,name="untestview"),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)