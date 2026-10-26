from django.urls import path

from human_target.views.HumanLigandAtlasView import HumanLigandAtlasView
from human_target.views.HumanProteinListView import HumanProteinListView
from human_target.views.HumanProteinView import HumanProteinView

app_name = "human_target"

urlpatterns = [
    path("proteins", view=HumanProteinListView.as_view(), name="human_protein_list"),
    path("ligands", view=HumanLigandAtlasView.as_view(), name="human_ligand_atlas"),
    path("protein/<str:accession>", view=HumanProteinView.as_view(), name="human_protein"),
]
