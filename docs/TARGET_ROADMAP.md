# TargetPathogen roadmap

Documento vivo para ordenar tareas de producto e implementacion. La idea es mantener aca el backlog tecnico-funcional que antes estaba en Notion, con estado, alcance y prioridades.

## Hecho / en uso

### Informacion metabolica

Incorpora informacion metabolica al analisis de targets (SBML/TSV/SIF de MetaFlux/Pathway Tools + KEGG), para saber en que ruta participa una proteina, que tan central es y si actua como chokepoint. Implementado, ingesta completa por genoma más:

- `Metabolic context` en la pagina de proteina, integrado al scoring, con oracion interpretativa automatica.
- Ranking de rutas a nivel genoma.
- Grafo de vecindario por proteina.
- Pagina de mapa por ruta.
- Grafo unico genome-wide estilo Krona (un nodo por pathway, un click hace zoom a su subgrafo de reacciones — pedido de las biologas para ver todo junto en vez de ruta por ruta), con los cortes de tamaño/densidad de chokepoints que deciden el label permanente ya recalibrados contra la distribucion real de KpATCC43816 (antes elegidos a ojo).

### Target executive summary

Resumen ejecutivo arriba de la pagina de proteina que responde en pocos segundos si el target es prometedor: frase interpretativa unica combinando score, metabolismo, drogabilidad, ligandos, estructura, off-target y conservacion; bloques Strengths / Risks / Missing evidence con links a las secciones que justifican cada punto; y badges especificos cuando hay datos completos (pocket consistente FPocket+P2Rank, estructura experimental disponible, baja similitud humana, ligando conocido fuerte).

### Ligandos, ChEMBL, PDB y quimica del target

Dashboard de señal quimica en la pagina de proteina: evidencia directa y por homologos separada por PDB/ChEMBL/ZINC, links externos, zoom inline de la estructura 2D, afinidad experimental estimada (nM/µM/mM) junto al pchembl crudo, y foco directo de ligandos PDB en el visualizador 3D desde "Open crystal". Pendiente: transferencia de ligandos desde homologos (ver `Integracion AlphaFill / Ligysis / CSA Atlas`).

### Genome overview 2.0 / ranking compuesto explicable

Ranking principal "Top evidence-convergent candidates" con score heuristico transparente (0-15, tier Strong/Moderate/Limited) que combina pocket, ligandos directos y transferidos, off-target, esencialidad, conservacion, estructura y metabolismo — con chips por proteina explicando por que aparece arriba. Ranking secundario "Worth a fresh look" para candidatos druggable/selectivos sin evidencia quimica explorada todavia. Export CSV del ranking compuesto con desglose completo de señales.

### Visualizacion y control de pockets

El visualizador permite elegir un pocket puntual e inspeccionarlo en detalle sin perder el contexto del entorno: Inspect centra la camara, aisla la capa y muestra un panel de detalle (metodo, score, residuos, propiedades derivadas — centro geometrico, consenso FPocket/P2Rank, sitio funcional anotado mas cercano), con toggle "Show only selected pocket" y atenuacion geometrica de la proteina al inspeccionar. Paridad completa entre las dos paginas del visualizador; la version embebida en la pagina de proteina es una vista previa liviana (sin toolbar de camara ni fallback legado a 3Dmol.js), con foco en abrir el visor fullscreen para interaccion completa.

### Agente IA para exploracion de targets

Chat/agente agnostico a proveedor LLM (Claude u OpenAI intercambiables) en un drawer global: responde preguntas sobre proteinas, filtros, scores, ligandos y estructura cargada; explica por que un target aparece priorizado; y puede ejecutar acciones reales en la UI (aplicar filtros), no solo responder texto. Alcance de genoma/proteina siempre re-derivado server-side, snapshot del estado de la UI en cada mensaje, logging de tokens/costo/latencia, budget resuelto via tope de gasto en la plataforma del proveedor, y un comando `evaluate_agent` para verificar el comportamiento contra un set fijo de prompts. Sin pendientes de codigo.

### Premium UI consistency pass

Pasada sistematica de consistencia visual (tokens de color/sombra/tipografia, hover-lift, entrada sutil, cero valores hardcodeados) aplicada a las ~15 paginas de la app, incluido el structure viewer, con checklist de pre-merge documentado en `docs/VISUAL_CHECKLIST.md`.

## En progreso

### Visualizacion de Proteina 2.0

Rediseño completo del visualizador 3D: coloreo por cadena y por estructura secundaria, manejo claro de estructuras multimericas, y selector de estructura priorizado por fuente/cobertura/calidad. Hoy solo esta la base: auto-rotacion apagada por defecto, estados de botones sincronizados, y nota aclarando que FPocket/P2Rank son predicciones computacionales.

### Off-target 2.0

Mejorar la visualizacion de similitud contra humano/microbioma/organismos relevantes, con filtros por identidad/cobertura/e-value/organismo e integracion al score final. Hecho hasta ahora (solo visualizacion, sin tocar filtros ni logica de scoring): grilla "Target profile" rediseñada como data sheet academica, con flags de riesgo por color y barras de magnitud. Falta: exponer esos filtros desde la propia seccion off-target de la pagina de proteina, una explicacion de riesgo mas rica por eje, e integracion explicita con estructura/ligandos/drogabilidad/score final.

## To Do

### Comparacion FPocket vs P2Rank

Comparar pockets predichos por FPocket y P2Rank: distancia entre centros, porcentaje de residuos compartidos, solapamiento espacial, badge de consenso estructural, y un filtro para priorizar proteinas donde ambos metodos coinciden en el pocket principal.

### Sitios funcionales y anotaciones estructurales

Mostrar residuos cataliticos y sitios funcionales sobre la estructura, distinguiendo tipo de anotacion (catalitico, ligando, PPI, cofactor, mutacion, dominio) con panel de evidencia (fuente y confianza). Fuentes a evaluar: UniProt, CSA Atlas (residuos cataliticos), Ligysis (sitios de union), y funcionalidades del Target viejo.

### Drogabilidad por fuente y estructura

Rediseñar la seccion de drogabilidad separando valores por programa/fuente y por tipo de estructura (PDB experimental, AlphaFold DB, ColabFold), mostrando a que estructura corresponde cada valor. Falta definir con el equipo cual valor se usa por defecto en la tabla principal y dejar auditable esa decision de prioridad (ej. PDB experimental > AlphaFold DB si hay buena cobertura).

### Priorizacion estructural completa

Estrategia integral de priorizacion basada en estructura, combinando disponibilidad/calidad/cobertura/tipo de estructura, pockets y su consenso, ligandos directos y homologos, sitios cataliticos, drogabilidad, off-target, y resolucion/metadata PDB.

### Constructor de score mejorado

Mejorar la pantalla de creacion de formulas de score: mostrar funciones y operaciones disponibles cerca de la formula, preview en vivo sobre un subconjunto de proteinas, sugerencias de variables segun filtros activos, y mensajes de error accionables.

### Columnas custom para analisis

Permitir columnas custom por genoma o analisis (categoricas o cuantitativas), usables para filtrar/ordenar/visualizar/construir scores, con validacion al importar y provenance de quien cargo cada columna.

### Auditoria y migracion de funcionalidades del Target viejo

Revisar el Target viejo y documentar que funcionalidades conviene migrar o reinterpretar: lista priorizada de features, referencias de flujo, y una decision por feature (migrar, adaptar, descartar o investigar).

### Integracion AlphaFill / Ligysis / CSA Atlas

Evaluar fuentes externas para enriquecer estructura y ligandos: que fuente usar para que dato, como importarla y mapearla a proteina/estructura/residuo, y riesgos de licencia/cobertura/mantenimiento. AlphaFill es la prioridad alta (mejor costo/beneficio evaluado): base publica (alphafill.eu) que trasplanta ligandos/cofactores de estructuras homologas resueltas experimentalmente sobre un modelo de AlphaFold ya existente, con API publica por UniProt ID que encaja directo con las estructuras que ya generamos por pipeline.

### Sequence & feature viewer 2.0

Pasar la seccion `Sequence` de texto plano a visualizacion funcional: mapa lineal con dominios/regiones/sitios funcionales, grid de residuos con hover, busqueda por posicion o motivo, y links desde residuos anotados hacia la estructura 3D.

### Cross-references hub

Agrupar identificadores externos (UniProt, KEGG, BioCyc, NCBI, PDB, ChEMBL) en una seccion unica, categorizados (sequence, structure, chemistry, pathways, literature) con estado de evidencia visible.

### Pathway-level target prioritization

Extender metabolismo desde target individual hacia decision a nivel ruta. Mayormente cubierto por el grafo genome-wide nuevo (tamaño por reacciones, color por densidad de chokepoints, score por ruta). Falta especificamente: ranking de rutas por cantidad de buenos targets como lista/tabla ordenable (hoy solo existe como grafo), metabolitos clave/cuellos de botella a nivel genoma completo, y export CSV del ranking de rutas.

### Evidence provenance / audit layer

Hacer explicita la procedencia de cada dato usado para priorizar: fuente, fecha de importacion, archivo/comando y version; badge o tooltip por seccion; y log de importaciones relevantes por genoma, para reproducibilidad y debugging en cluster.

### Red de señalizacion/regulacion por proteina (KEGG PPI)

Grafo de interacciones proteina-proteina y regulatorias (activation/inhibition/phosphorylation/expression/binding via KEGG KGML), distinto del grafo de reacciones metabolicas ya implementado — relevante en patogenos para sistemas de dos componentes y regulones de virulencia. Reusaria la infraestructura de fetch de KEGG y el patron de layout/tooltip/inspector ya construido para el grafo metabolico. Evaluado como implementacion real (no mockup) en target-human-web, el proyecto compañero de target humano.

## Ideas evaluadas y descartadas por ahora

Auditoria funcional de target-human-web (compañero, target humano) para ver si habia algo mas para sumar aca. Queda registrado por que no se priorizan, para no re-investigarlas de cero:

- **Retrosynthesis benchmark**: poster estatico sin computo real (2 de 6 modelos con resultado nulo desde octubre). Nada que migrar salvo el formato de tabla si algun dia publicamos benchmarks propios.
- **Matching de rutas de sintesis por patentes**: complementa bien a LigQ_2, pero depende de un dataset de patentes enorme que no tenemos. En espera hasta tener acceso a uno equivalente.
- **Tissue expression (Bgee) y variantes clinicas (dbSNP/OMIM)**: especificos de humano, no aplican a targets de patogeno.
- **RDKit-JS**: cargado pero nunca invocado, no hay nada funcional que migrar.

## Orden sugerido

1. Revisar en navegador/cluster lo implementado: metabolismo, target summary, ligandos, pockets y agente.
2. Visualizacion de Proteina 2.0.
3. Off-target 2.0.
4. Comparacion FPocket vs P2Rank.
5. Drogabilidad por fuente y estructura.
6. Integracion AlphaFill (ligando trasplantado sobre AlphaFold/ColabFold ya existente).
7. Sitios funcionales y anotaciones estructurales.
8. Priorizacion estructural completa.
9. Sequence & feature viewer 2.0.
10. Cross-references hub.
11. Pathway-level target prioritization.
12. Red de señalizacion/regulacion por proteina (KEGG PPI).
13. Evidence provenance / audit layer.
14. Constructor de score mejorado.
15. Columnas custom para analisis.
16. Auditoria Target viejo e integraciones externas (Ligysis, CSA Atlas).
