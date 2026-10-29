from django.urls import path

from human_target.views.HumanLigandAtlasView import HumanLigandAtlasView
from human_target.views.HumanProteinListView import HumanProteinListView
from human_target.views.HumanProteinView import HumanProteinView
from human_target.views.RetrosynthesisBenchmarkView import RetrosynthesisBenchmarkView

app_name = "human_target"

urlpatterns = [
    path("proteins", view=HumanProteinListView.as_view(), name="human_protein_list"),
    path("ligands", view=HumanLigandAtlasView.as_view(), name="human_ligand_atlas"),
    path(
        "retrosynthesis",
        view=RetrosynthesisBenchmarkView.as_view(),
        name="retrosynthesis_benchmark",
    ),
    path("protein/<str:accession>", view=HumanProteinView.as_view(), name="human_protein"),
]
