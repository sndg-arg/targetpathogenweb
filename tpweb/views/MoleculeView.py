from django.views.generic import View
from django.shortcuts import render
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

class MoleculeView(View):
    def get(self, request):
        smiles = 'CC(C)C[C@@H](CO)N'
        try:
            mol = Chem.MolFromSmiles(smiles)
            canvas_width_pixels = 300
            canvas_height_pixels = 300
            
            drawer = rdMolDraw2D.MolDraw2DSVG(canvas_width_pixels, canvas_height_pixels)
            drawer.DrawMolecule(mol)
            drawer.FinishDrawing()
            
            svg_data = drawer.GetDrawingText()
            
            return render(request, 'molecule/molecule.html', {'svg': svg_data})
        except Exception as e:
            return render(request, 'molecule/error.html', {'message': f"Error rendering molecule: {str(e)}"})
