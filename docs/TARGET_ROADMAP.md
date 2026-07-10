# TargetPathogen roadmap

Documento vivo para ordenar tareas de producto e implementacion. La idea es mantener aca el backlog tecnico-funcional que antes estaba en Notion, con estado, alcance y prioridades.

## Estado actual

### Hecho / en validacion

Estas tareas ya tienen implementacion en la rama actual y necesitan revision visual/funcional en datos reales antes de darlas por cerradas.

### Informacion metabolica

**Objetivo.** Incorporar informacion metabolica al analisis de targets desde el pipeline automatico y fuentes curadas. Debe quedar claro en que ruta participa una proteina, que tan central es, si actua como chokepoint y como esa evidencia afecta la priorizacion.

**Fuentes usadas.**

- Export SBML de MetaFlux/Pathway Tools: reacciones, genes, metabolitos, estequiometria y expresiones GPR.
- Tabla de resultados metabolicos: chokepoints, centralidad y evidencia derivada del pipeline.
- `network.sif`: topologia reaccion-reaccion para vecindarios metabolicos.
- KEGG REST/cache local: nombres y membresia de rutas.

Reactome no se usa como fuente de datos porque esta orientado principalmente a humano. Se usa como referencia de UX: rutas navegables, contexto visual fuerte, agrupacion por pathway y lectura rapida de relevancia biologica.

**Implementado.**

- Modelo e ingesta por genoma para reacciones, genes, chokepoints, isoenzimas, metabolitos y estequiometria.
- Mapeo reaccion-ruta de KEGG.
- Seccion `Metabolic context` en la pagina de proteina.
- Integracion de evidencia metabolica al sistema de `ScoreFormula`.
- Oracion interpretativa automatica para explicar el valor del target.
- Ranking de rutas a nivel genoma completo, con buscador por nombre.
- Grafo Cytoscape del vecindario de reacciones de una proteina.
- Agrupacion visual por ruta metabolica.
- Chokepoints diferenciados por forma y color.
- Conexiones entre rutas marcadas.
- Pagina de mapa completo por ruta con diagrama sustrato -> reaccion -> producto.
- Tabla de reacciones con genes clickeables, metabolitos y tooltips.
- Enlaces entre ranking, mapa de ruta, grafo de vecindario y pagina de proteina.
- Pulido visual inicial: jerarquia tipografica, animaciones, tooltips y affordances de links.
- Alineacion visual con el sistema de componentes de la app: paleta via tokens, paneles `tp-ui-panel`, botones `tp-btn` y espaciado `--tp-space-*`.

**Pendiente para cerrar.**

- Validar con biologas si la interpretacion de chokepoint `producing`, `consuming` y `both` se entiende igual que en el pipeline.
- Agregar export/import curado para BioCyc SmartTables cuando haya archivo ejemplo.
- Agregar una vista genome-wide tipo overview/fireworks: rutas coloreadas por cantidad/calidad de targets.
- Mejorar leyendas biologicas: explicar que significa centralidad, isoenzima, chokepoint y pathway sin cargar la UI.
- Agregar filtros por ruta en la tabla principal de proteinas.
- Agregar validaciones automaticas de ingesta para detectar SBML/TSV/SIF inconsistentes.

### Target executive summary

Agregar un resumen ejecutivo arriba de la pagina de proteina. Debe responder en pocos segundos si el target parece prometedor, por que, que evidencia falta y cuales son los principales riesgos.

**Implementado.**

- Frase interpretativa unica combinando score, metabolismo, drogabilidad, ligandos, estructura, off-target y conservacion.
- Bloques `Strengths`, `Risks` y `Missing evidence`.
- Links internos a las secciones que justifican cada punto.
- Conteo interno de senales positivas para orientar la lectura.
- Integracion visual con el encabezado y el sistema de paneles de la pagina de proteina.

**Pendiente para cerrar.**

- Validar con biologas si el wording del veredicto es claro y no sobrepromete.
- Ajustar pesos/umbrales del resumen cuando el equipo defina criterios de priorizacion.
- Agregar badges mas especificos cuando existan datos completos: pocket consistente FPocket/P2Rank, ligando conocido fuerte, baja similitud humana, buena cobertura estructural.

### Ligandos, ChEMBL, PDB y quimica del target

Mejorar la lectura de evidencia quimica y ligandos. La pagina ya tiene un dashboard inicial de ligandos; falta conectarlo mas fuerte con estructura, ChEMBL y PDB.

**Implementado.**

- Dashboard de senal quimica en la pagina de proteina.
- Separacion de evidencia directa, homologos, PDB, ChEMBL y ZINC.
- Links externos visibles a ChEMBL, RCSB PDB y ZINC cuando aplica.
- Zoom inline de la estructura 2D del ligando desde el resumen quimico.
- Acceso directo al detalle interno de cada ligando.
- Acciones visuales usando variantes existentes `tp-btn`.
- Links externos en tablas usando chips del sistema (`tp-chip`).

**Pendiente para cerrar.**

- Mostrar afinidad experimental cuando exista.
- Permitir enfocar ligandos PDB en el visualizador 3D.
- Evaluar transferencia de ligandos desde homologos con AlphaFill o superposicion estructural.
- Dejar preparado soporte futuro para modelos Boltz.
- Revisar en navegador con datos reales que el modal de molecula, las tablas y los links externos se vean bien en modo claro/oscuro.

### Genome overview 2.0 / ranking compuesto explicable

El overview del genoma debe funcionar como tablero macro, no como reflejo de la ultima feature implementada. La priorizacion inicial no debe depender solo de drogabilidad ni de cantidad cruda de ligandos.

**Implementado.**

- Ranking principal `Top evidence-convergent candidates`.
- Score heuristico transparente para triage inicial, combinando:
  - calidad de pocket FPocket;
  - soporte P2Rank;
  - ligandos experimentales PDB y bioactividad ChEMBL directa;
  - evidencia transferida por homologos y compuestos ZINC propuestos, con menor peso;
  - baja similitud humana;
  - baja similitud contra microbioma intestinal;
  - similitud a genes esenciales DEG;
  - conservacion core por Roary/CoreCruncher;
  - estructura disponible;
  - contexto metabolico y chokepoints.
- Chips por proteina explicando por que aparece arriba.
- Score visible como rango interpretable `0-15`, con tier `Strong/Moderate/Limited` y tooltip de significado.
- Drogabilidad explicitada como `FPocket druggability` en chips y copy, no solo como "pocket quality".
- Ligandos tratados como evidencia por tipo y no como conteo lineal: el overview muestra si hay evidencia directa/soporte, y el ranking secundario conserva los conteos detallados.
- Rankings secundarios conservados para senales especificas, como ligand support.
- Copy aclarando que el score es triage, no una conclusion biologica final.

**Pendiente para cerrar.**

- Validar pesos con biologas y equipo de bioinformatica.
- Validar si el maximo teorico de 15 puntos y los cortes Strong >=65%, Moderate 40-65% y Limited <40% son intuitivos para usuarios biologos.
- Definir si el score compuesto debe convertirse en `ScoreFormula` editable o quedar solo como ranking de overview.
- Agregar export del ranking compuesto con desglose de contribuciones.
- Evaluar una comparacion visual entre ranking compuesto, ranking por pocket y ranking por ligandos.

## To Do prioritario

### Visualizacion de Proteina 2.0

Redisenar la experiencia completa del visualizador 3D. Debe servir para estructura, cadenas, pockets, ligandos, sitios funcionales y superposiciones sin volverse confuso.

**Alcance propuesto.**

- Spin apagado por defecto.
- Estado visual claro para botones activos.
- Coloreo por estructura secundaria.
- Coloreo por cadena.
- Manejo claro de estructuras multimericas.
- Selector de estructura priorizado por fuente, cobertura y calidad.
- Evaluar si corresponde crear una vista estructural dedicada cuando haya demasiada informacion.

### Visualizacion y control de pockets

Mejorar como se muestran y controlan los pockets en el visualizador.

**Alcance propuesto.**

- Paleta consistente en modo claro y oscuro.
- Controles por pocket individual.
- Estado seleccionado claro.
- Transparencia y superficie mas legibles.
- Mostrar alpha spheres, superficies u otra representacion adecuada segun el dato disponible.
- Tooltips o panel lateral con score, residues, volumen y metodo.

### Comparacion FPocket vs P2Rank

Implementar comparacion entre pockets predichos por FPocket y P2Rank.

**Alcance propuesto.**

- Distancia entre centros.
- Porcentaje de residuos compartidos.
- Solapamiento espacial.
- Coincidencia entre mejores pockets de cada metodo.
- Badge de consenso estructural.
- Filtro para priorizar proteinas donde ambos metodos predicen el mismo pocket principal.

### Sitios funcionales y anotaciones estructurales

Agregar informacion funcional sobre la estructura de la proteina.

**Fuentes a evaluar.**

- UniProt annotations.
- CSA Atlas para residuos cataliticos.
- Ligysis para sitios de union e interacciones ligando-proteina.
- Funcionalidades del Target viejo.

**Alcance propuesto.**

- Mostrar residuos cataliticos y sitios funcionales sobre la estructura.
- Distinguir tipos de anotacion: catalitico, ligando, PPI, cofactor, mutacion o dominio.
- Panel de evidencia con fuente y confianza.

### Drogabilidad por fuente y estructura

Rediseñar la seccion de drogabilidad.

**Alcance propuesto.**

- Separar valores por programa/fuente.
- Separar valores por tipo de estructura: PDB experimental, AlphaFold DB, ColabFold u otras.
- Mostrar a que estructura corresponde cada valor.
- Definir con el equipo que valor se usa por defecto en la tabla principal.
- Hacer auditable la decision de prioridad: por ejemplo PDB experimental > AlphaFold DB si existe buena cobertura.

### Priorizacion estructural completa

Diseñar una estrategia integral de priorizacion basada en estructura.

**Debe combinar.**

- Disponibilidad y calidad de estructuras.
- Cobertura.
- Tipo de estructura.
- Pockets y consenso FPocket/P2Rank.
- Ligandos directos y homologos.
- Sitios cataliticos.
- Drogabilidad.
- Off-target.
- Resolucion y metadata PDB cuando exista.

### Off-target 2.0

Revisar y mejorar la seccion de off-target.

**Alcance propuesto.**

- Mejor visualizacion de similitud contra humano, microbioma y organismos relevantes.
- Filtros por identidad, cobertura, e-value y organismo.
- Explicacion de riesgos.
- Integracion con estructura, ligandos, drogabilidad y score final.

### Constructor de score mejorado

Mejorar la pantalla de creacion de formulas de score.

**Alcance propuesto.**

- Mostrar funciones y operaciones disponibles cerca de la formula.
- Preview en vivo sobre un subconjunto de proteinas.
- Sugerencias de variables segun filtros activos.
- Ocultar o despriorizar variables incompatibles segun tipo de dato.
- Explicar errores de formula con mensajes accionables.

### Columnas custom para analisis

Permitir columnas custom por genoma o analisis.

**Alcance propuesto.**

- Definir tipo de dato: categorico o cuantitativo.
- Usarlas para filtrar, ordenar, visualizar y construir scores.
- Validar valores al importar.
- Mantener provenance de quien cargo la columna y desde que archivo.

### Agente IA para exploracion de targets

Agregar un agente/chat IA que ayude a explorar proteinas, filtros, scores, ligandos, estructuras y evidencia cargada en TPW.

**Alcance propuesto.**

- Responder preguntas usando datos del sistema.
- Explicar por que un target aparece priorizado.
- Sugerir filtros y comparaciones.
- Ayudar a interpretar evidencia estructural, metabolica y off-target.
- Citar las fuentes internas usadas para cada respuesta.

### Auditoria y migracion de funcionalidades del Target viejo

Revisar el Target viejo y documentar que funcionalidades conviene migrar o reinterpretar.

**Salida esperada.**

- Lista priorizada de features concretas.
- Screenshots o referencias de flujo.
- Decision para cada feature: migrar, adaptar, descartar o investigar.

### Integracion AlphaFill / Ligysis / CSA Atlas

Evaluar fuentes externas para enriquecer estructura y ligandos.

**Salida esperada.**

- Que fuente usar para que dato.
- Como importarla.
- Como mapearla a proteina, estructura y residuo.
- Como mostrarla en la UI.
- Riesgos de licencia, cobertura y mantenimiento.

**AlphaFill — prioridad alta, mejor costo/beneficio evaluado.**

- Base de datos publica (alphafill.eu) que trasplanta ligandos/cofactores de estructuras
  homologas resueltas experimentalmente sobre un modelo de AlphaFold ya existente.
- API publica por UniProt ID; encaja directo con las estructuras AlphaFold/ColabFold que ya
  generamos por pipeline, sin depender de una corrida nueva.
- Responde "donde probablemente se sienta un ligando en esta estructura predicha", como paso
  previo/complementario al analisis de drogabilidad ya existente.
- Patron de referencia (target-human-web, compañero): carga el CIF de AlphaFill via 3Dmol.js
  con foco/highlight por ligando individual — reusable con el visualizador NGL propio adaptando
  el formato.

## Nuevas cards recomendadas

### Sequence & feature viewer 2.0

La seccion `Sequence` necesita pasar de texto plano a visualizacion funcional.

**Alcance propuesto.**

- Mapa lineal de la proteina con dominios, regiones, sitios funcionales, peptides, transmembrana y low complexity si existen.
- Grid de residuos con hover.
- Busqueda por posicion o motivo.
- Links desde residuos anotados hacia estructura 3D.

### Cross-references hub

Agrupar identificadores externos en una seccion unica y clara.

**Alcance propuesto.**

- UniProt, KEGG, BioCyc, NCBI, PDB, ChEMBL y otras fuentes disponibles.
- Agrupar por categoria: sequence, structure, chemistry, pathways, literature.
- Mostrar estado de evidencia: disponible, no encontrado, pendiente de importacion.

### Pathway-level target prioritization

Extender metabolismo desde target individual hacia decision a nivel ruta.

**Alcance propuesto.**

- Ranking de rutas por cantidad de buenos targets.
- Densidad de chokepoints.
- Score promedio y mejor score por ruta.
- Metabolitos clave y cuellos de botella.
- Export CSV para discutir con biologas.

### Evidence provenance / audit layer

Hacer explicita la procedencia de cada dato usado para priorizar.

**Alcance propuesto.**

- Fuente, fecha de importacion, archivo/comando y version cuando aplique.
- Badge o tooltip por seccion.
- Log de importaciones relevantes por genoma.
- Ayuda para reproducibilidad y debugging en cluster.

### Premium UI consistency pass

Pasada sistematica para que TPW se sienta como una unica aplicacion cientifica cuidada, no como pantallas acumuladas. No busca redisenar todo: busca aplicar con disciplina los patrones visuales ya existentes.

**Principios.**

- Un acento dominante por vista; colores semanticos solo cuando agregan significado.
- Profundidad consistente usando `--tp-shadow-xs/sm/md/lg`.
- Movimiento con proposito: entrada sutil, hover-lift y foco claro.
- Tipografia de datos consistente: mono/tabular para IDs, scores, EC/GO, accesiones y coordenadas.
- Cero excepciones hardcodeadas de color/sombra/radio cuando exista token del sistema.

**Primer alcance.**

- Genome overview.
- Protein detail.
- Protein list / buscador.

**Implementado inicial.**

- Utilidades globales de entrada sutil y profundidad en `ui-system.css`.
- `tp-page-hero` y `tp-ui-panel` con sombra/token y transiciones consistentes.
- Genome overview, Protein detail y Protein list usando el mismo movimiento base.
- Metabolism overview/pathway y Binder detail incorporados al mismo lenguaje de motion/depth.
- Cache busting de CSS en las vistas tocadas para que el cluster levante el pase visual.

**Pendiente para cerrar.**

- Auditar colores/sombras hardcodeadas por pagina.
- Definir un checklist visual antes de mergear nuevas vistas.
- Revisar en modo claro/oscuro con screenshots reales.
- Extender luego al structure viewer, con validacion visual especifica porque es una superficie interactiva de mayor riesgo.

### Red de señalizacion/regulacion por proteina (KEGG PPI)

Grafo de interacciones proteina-proteina y regulatorias, distinto del grafo de reacciones
metabolicas ya implementado (ese es de reacciones que comparten metabolito; este seria de
relaciones biologicas directas entre genes/proteinas). Relevante en patogenos para sistemas de
dos componentes, cascadas de señalizacion y regulones de virulencia.

**Fuentes.** KEGG KGML (relaciones activation / inhibition / phosphorylation / expression /
binding entre genes/ortologos). Reusa la infraestructura de fetch de KEGG que ya tenemos
(`fetch_kegg_pathway_map`).

**Alcance propuesto.**

- Parsear relaciones KGML, descartando nodos aislados y compuestos sin interaccion real.
- Layout de fuerza dirigida (fcose, ya en uso para el grafo metabolico) con foco/zoom
  automatico en la proteina en foco.
- Reusar el patron de tooltip enriquecido + inspector ya construido para el grafo metabolico
  en vez de reinventarlo.
- Diferenciar tipo de relacion visualmente (linea solida vs punteada, flecha vs marcador de
  inhibicion), no solo por color.

**Evaluado en:** research funcional de target-human-web (compañero, target humano) — ahi es
una implementacion real y funcional (`PathwayGraph`/`parseKGML` en su `bundle.jsx`), no un
mockup.

### Ideas evaluadas de target-human-web y descartadas por ahora

Auditoria funcional del proyecto de un compañero (target humano, React + prototipo sin backend)
para ver si habia algo mas para sumar aca. Quedo registrado que fueron evaluadas y por que no se
priorizan, para no re-investigarlas de cero mas adelante.

- **Retrosynthesis benchmark** (comparacion top-1/top-10 de modelos de retrosintesis). Es un
  poster estatico: 2 de 6 modelos con `top1: null` desde octubre, sin computo real en ningun
  lado. No hay nada que migrar salvo el formato de tabla si algun dia publicamos benchmarks
  propios (docking, drogabilidad).
- **Matching de rutas de sintesis por patentes** (USPTO-50K + PaRoutes2, ~3.2M reacciones de
  patentes via RDKit/Tanimoto offline). Complementa bien el trabajo de LigQ_2 (dice *como*
  sintetizar un hit, no solo *que* hit existe), pero depende de un dataset de patentes enorme
  que no tenemos disponible. Ademas su indicador de "estado de patente" es codigo muerto, nunca
  se popula. Dejar en espera hasta tener acceso a un dataset equivalente.
- **Tissue expression (Bgee) y variantes clinicas (dbSNP/OMIM).** Especificos de humano, no
  aplican a targets de patogeno.
- **RDKit-JS cargado pero nunca invocado.** No hay edicion de SMILES ni quimica en vivo en el
  navegador pese a la dependencia — no hay nada funcional que migrar de ahi.

## Orden sugerido

1. Revisar en navegador/cluster lo implementado: metabolismo, target summary y ligandos.
2. Premium UI consistency pass.
3. Integracion AlphaFill (ligando trasplantado sobre AlphaFold/ColabFold ya existente).
4. Visualizacion de Proteina 2.0.
5. Visualizacion y control de pockets.
6. Comparacion FPocket vs P2Rank.
7. Drogabilidad por fuente y estructura.
8. Sitios funcionales y anotaciones estructurales.
9. Priorizacion estructural completa.
10. Off-target 2.0.
11. Sequence & feature viewer 2.0.
12. Cross-references hub.
13. Pathway-level target prioritization.
14. Red de señalizacion/regulacion por proteina (KEGG PPI).
15. Evidence provenance / audit layer.
16. Constructor de score mejorado.
17. Columnas custom para analisis.
18. Agente IA para exploracion de targets.
19. Auditoria Target viejo e integraciones externas (Ligysis, CSA Atlas).
