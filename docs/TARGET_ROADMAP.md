# TargetPathogen roadmap

Documento vivo para ordenar tareas de producto e implementacion. La idea es mantener aca el backlog tecnico-funcional que antes estaba en Notion, con estado, alcance y prioridades.

## Estado actual

### Hecho / en uso

Estas tareas ya tienen implementacion completa en la rama actual.

### Corte actual - 2026-07-18

- Metabolismo: implementado end-to-end para Klebsiella, con ingesta SBML/TSV/SIF, contexto por
  proteina, ranking por ruta, vistas navegables y un grafo unico genome-wide con zoom in/out
  estilo Krona por pathway.
- Protein detail / genome overview: resumen ejecutivo, evidencia estructural/quimica/metabolica y
  lenguaje explicativo para biologos.
- Pockets / estructura: lectura de pockets especificos y alpha spheres desde outputs originales de
  GATES, con controles visuales y paridad completa entre las dos paginas del visualizador.
- Agente IA: funciona con OpenAI en cluster, drawer global, historial por sesion, tools para
  filtros, explicacion de targets, auditoria de evidencia y comparacion de candidatos, snapshot de
  estado de UI, Markdown completo en el drawer, logging de tokens/costo/latencia, y un set de
  evaluacion (`evaluate_agent`) corrido y con sus hallazgos ya corregidos.
- UX premium: sistema visual consistente aplicado a las ~15 paginas de la app, incluido el
  structure viewer, con checklist de pre-merge documentado.

### Informacion metabolica

**Objetivo.** Incorporar informacion metabolica al analisis de targets desde el pipeline automatico y fuentes curadas. Debe quedar claro en que ruta participa una proteina, que tan central es, si actua como chokepoint y como esa evidencia afecta la priorizacion.

**Fuentes usadas.**

- Export SBML de MetaFlux/Pathway Tools: reacciones, genes, metabolitos, estequiometria y expresiones GPR.
- Tabla de resultados metabolicos: chokepoints, centralidad y evidencia derivada del pipeline.
- `network.sif`: topologia reaccion-reaccion para vecindarios metabolicos.
- KEGG REST/cache local: nombres y membresia de rutas.

Reactome no se usa como fuente de datos porque esta orientado principalmente a humano. Se usa como referencia de UX: rutas navegables, contexto visual fuerte, agrupacion por pathway y lectura rapida de relevancia biologica.

**Implementado.**

Ingesta completa por genoma (reacciones, genes, chokepoints, isoenzimas, metabolitos,
estequiometria), mapeo a rutas KEGG, `Metabolic context` en la pagina de proteina,
integracion con `ScoreFormula`, oracion interpretativa automatica, ranking de rutas a nivel
genoma, grafo de vecindario por proteina y pagina de mapa por ruta (sustrato->reaccion->producto).
Alineado visualmente al sistema de componentes de la app (tokens, `tp-ui-panel`, `tp-btn`).

Suma reciente, a pedido de las biologas ("quieren todo junto, no ruta por ruta"): grafo unico
genome-wide (`/genome/<genoma>/metabolism/network`, `tpweb/services/metabolism_network.py`) con
un nodo por pathway bajo una particion estricta reaccion->pathway (distinta de la logica
multi-membership del ranking, necesaria para que nodo y contenido siempre coincidan), tamaño por
reacciones, color por densidad de chokepoints. Interaccion tipo Krona: click en un pathway hace
zoom completo a su subgrafo de reacciones+metabolitos (no expande en el lugar, para que varios
pathways abiertos no se superpongan), con modulo compartido (`metabolic-reaction-graph.js`) reusado
en la pagina standalone de ruta, que reemplazo ahi el diagrama SVG viejo. Pulido visual (toolbar
con iconos, spinner, hint dismissible, barra de score) y labels decluttered (solo pathways
grandes/chokepoint-densos quedan con nombre visible; el resto via hover) porque etiquetar los ~79
nodos de un genoma real volvia el grafo ilegible. Verificado con KpATCC43816: 79 nodos, 350
aristas, cada una de las 1618 reacciones contada una sola vez.

Suma reciente: tooltips explicando centralidad/isoenzima/chokepoint/pathway directamente en la UI
(metric-pills, leyenda del grafo, inspector), filtro por ruta en la tabla principal de proteinas
(boton "Filter protein list by this pathway" en las cards de `metabolism.html` y en el hero de
`metabolism_pathway.html`, reusando el dispatcher existente de filtros especiales) y validaciones
automaticas en `load_metabolism` (SBML sin reacciones, genes del TSV sin locus tag en el genoma,
nodos de `network.sif` sin reaccion correspondiente, columna de centralidad ausente).

**Pendiente para cerrar.**

- Agregar export/import curado para BioCyc SmartTables cuando haya archivo ejemplo.
- Recalibrar el umbral de "pathway importante" para label permanente (hoy `size>=50px` o tier de
  chokepoint alto, hardcodeado) contra la distribucion real de mas de un genoma.

### Target executive summary

Agregar un resumen ejecutivo arriba de la pagina de proteina. Debe responder en pocos segundos si el target parece prometedor, por que, que evidencia falta y cuales son los principales riesgos.

**Implementado.**

- Frase interpretativa unica combinando score, metabolismo, drogabilidad, ligandos, estructura, off-target y conservacion.
- Bloques `Strengths`, `Risks` y `Missing evidence`.
- Links internos a las secciones que justifican cada punto.
- Conteo interno de senales positivas para orientar la lectura.
- Integracion visual con el encabezado y el sistema de paneles de la pagina de proteina.
- Badges especificos cuando hay datos completos: pocket consistente FPocket/P2Rank, estructura
  experimental disponible, baja similitud humana (<30% identidad, distinto tono del riesgo generico
  de similitud humana), ligando conocido fuerte (co-cristal PDB, o registro directo de ChEMBL con
  pchembl >= 7).

Bug real encontrado con datos en vivo (VK055_4737): la pagina decia "11 signals" pero solo listaba
6 Strengths — `strengths[:6]` cortaba en silencio, y las 3 badges perdidas eran justo las mas
especificas agregadas en esta ronda (Direct ligand evidence, Strong known ligand, Experimental
structure available), que se appendean despues de varias genericas que ya llenaban el limite.
Se agrego un `priority` opcional a `_append_summary_item`, se marcaron las 5 badges mas
especificas/valiosas con prioridad alta, y se ordena por esa prioridad (estable) antes de cortar —
ademas se subio el limite de 6 a 9.

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
- Afinidad experimental estimada (nM/µM/mM) junto al pchembl crudo, en la tabla ChEMBL, el detalle
  de ligando y el chip resumen — conversion directa de `pchembl = -log10(concentracion molar)`,
  dato ya cargado, sin ingesta nueva.
- Enfocar ligandos PDB en el visualizador 3D: el boton "Open crystal" ahora pasa el codigo CCD
  del ligando como `?focus_ligand=`, y el visor lo selecciona (`resname`), lo resalta y centra
  la camara apenas carga la estructura.

Dos hallazgos reales de una revision completa de capturas de pantalla, verificados contra el
codigo antes de tocarlos (dos sospechas mas de esa misma revision — el estilo del breadcrumb
actual, el fondo verde de "Pocket druggability" — resultaron ser diseño intencional ya usado en
el resto de la app, no se tocaron): el ligando destacado en "Best available ligand signal"
tambien aparecia duplicado como primer item de la tira de abajo (`_build_binder_summary` armaba
el preview sin excluir al "best"); y las mini-cards de ligando mostraban los botones Detail/RCSB
PDB arriba de la imagen de la molecula (orden de DOM realmente al reves, sin ningun truco de CSS
que lo corrigiera visualmente). Los dos corregidos.

**Pendiente para cerrar.**

- Transferencia de ligandos desde homologos (ver card `Integracion AlphaFill / Ligysis / CSA Atlas`).

### Genome overview 2.0 / ranking compuesto explicable

El overview del genoma debe funcionar como tablero macro, no como reflejo de la ultima feature implementada. La priorizacion inicial no debe depender solo de drogabilidad ni de cantidad cruda de ligandos.

**Implementado.**

Ranking principal `Top evidence-convergent candidates` con score heuristico transparente
(0-15, tier `Strong/Moderate/Limited`) que combina pocket FPocket/P2Rank, ligandos directos
(PDB/ChEMBL) y transferidos (homologos/ZINC, menor peso), off-target humano/microbioma,
esencialidad DEG, conservacion core, estructura disponible y contexto metabolico/chokepoints.
Chips por proteina explican por que aparece arriba; copy aclara que es triage, no conclusion
final. `Worth a fresh look` reemplazo al ranking secundario por conteo de ligandos
(`Strongest ligand support`), que sesgaba hacia proteinas "muy estudiadas" (homologos humanos
de kinasas/GPCRs) independientemente de si eran buenos targets bacterianos — ahora muestra
candidatos druggable/selectivos sin evidencia quimica explorada todavia. Scoring compartido
entre ambos rankings via `_score_proteins`/`_format_score_items`. Hero simplificado (2 acciones
primarias, resto en fila secundaria) y jerarquia tipografica en `Evidence available` (evidencia
directa mas prominente que la transferida). Export del ranking compuesto en CSV
(`?export=ranking_csv`) con desglose completo de señales y cautions por proteina (no solo los
6 factores capados que se muestran en la card).

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

**Implementado inicial.**

- Auto-rotacion apagada por defecto en el viewer 3D.
- Estado `aria-pressed` sincronizado para Spin, Cartoon y Surface.
- Tooltips mas explicitos para modos de vista y auto-rotacion.
- Nota en sidebar aclarando que FPocket/P2Rank son predicciones computacionales y deben leerse junto con fuente estructural, confianza y ligandos.

### Visualizacion y control de pockets

Mejorar como se muestran y controlan los pockets en el visualizador.

**Objetivo biologico.**

El usuario debe poder elegir un pocket puntual y mirarlo en detalle, sin perder la opcion de ver el sector/entorno de residuos que lo rodea. La experiencia tiene que responder: "que pocket estoy viendo, de que metodo viene, que residuos lo forman, que score tiene y por que podria importar como sitio de union".

**Alcance propuesto.**

- Paleta consistente en modo claro y oscuro.
- Controles por pocket individual.
- Estado seleccionado claro.
- Transparencia y superficie mas legibles.
- Mostrar alpha spheres, superficies u otra representacion adecuada segun el dato disponible.
- Separar visualmente `Pocket` (cavidad/sitio especifico importado) de `Sector` (superficie o residuos alrededor del pocket).
- Jerarquia de UI: accion primaria `Inspect pocket` para la cavidad especifica y capas secundarias para contexto (`Alpha spheres`/`Pocket`, `Residues`, `Surface`, `Labels`).
- Tooltips o panel lateral con score, residues, volumen y metodo.
- Seleccion explicita de pocket activo desde la card o un boton `Inspect pocket`.
- Al seleccionar un pocket: centrar camara, resaltar ese pocket, atenuar/esconder otros pockets y mostrar detalle.
- Toggle `Show only selected pocket` / `Show all pockets`.
- Accion `Clear selection`.
- Panel de detalle del pocket seleccionado con metodo, score, residuos, capas visibles y propiedades geometricas disponibles.
- Preparar la seleccion para comparar luego FPocket vs P2Rank cercano.

**Implementado inicial.**

Capas renombradas y claras (`Alpha spheres`/`Pocket`, `Residues`, `Surface`, `Labels`) con
tooltips, y accion `Inspect` que selecciona un pocket, centra camara, aisla su capa y muestra un
panel persistente (metodo, score, capa visible, residuos, propiedades — volumen/SASA/hidrofobicidad
para FPocket, score/probabilidad para P2Rank). Paridad completa entre `protein.html` y
`structure.html`: mismo `pocket_cards.html`, mismo flujo de Inspect en ambas paginas (antes
`protein.html` usaba una tabla vieja sin Inspect). Corregidos varios bugs de raiz que rompian
zoom/alpha spheres/Inspect: radio de alpha spheres hardcodeado en vez de leer el real desde el
B-factor de FPocket, `Inspect` apagaba el cartoon completo por error, y `entrypoint.js` no
importaba `NGL.Shape` (rompia el render de alpha spheres reales en las dos paginas).

Badge "Unusual size": `tpweb/services/pocket_geometry.py` marca un pocket de FPocket como outlier
de volumen si se aleja mucho (z-score modificado, umbral 3.5) de la mediana de *esa misma
estructura*. Corrido en produccion sobre KpATCC43816 y validado de punta a punta contra el archivo
curado original: 30.7% de proteinas curadas quedan marcadas — confirmado con casos reales (ej.
`VK055_0002`/Pocket 13) que es señal genuina, no un bug de calibracion. Cuando el pocket
druggable elegido es outlier, el sub-score de drogabilidad se descuenta en `_score_proteins` y
aparece como riesgo en el resumen ejecutivo en vez de fortaleza.

Toggle `Show only selected pocket` agregado en ambas paginas: al activarlo, fuerza a ocultar la
capa activa de todos los otros pockets y bloquea sus botones de capa hasta desactivarlo. De paso,
mientras se implementaba se encontro y corrigio una regresion real: `inspectPocket()` terminaba
poniendo `pocketInspector.hidden = true` (volvia a esconder el panel que acababa de llenar de
datos), reintroducida por un commit posterior no relacionado que revertia sin querer un fix
anterior.

Foco geometrico: al inspeccionar un pocket, el cartoon principal ahora baja su opacidad (antes
solo se apagaban capas de otros pockets, la proteina en si quedaba igual de opaca). Propiedades
derivadas agregadas al panel de inspector (mismo campo `Pocket properties` que ya se mostraba):
centro geometrico de cada pocket, consenso FPocket/P2Rank (centros a menos de ~8 Å se marcan como
el mismo sitio, sin importar el metodo) y sitio funcional anotado mas cercano, cuando hay
`residuesets` cargados. No se implemento distancia a ligandos (HETATM): identificar cual HETATM es
un ligando real vs. un aditivo de cristalizacion (sulfato, glicerol, iones) requiere una lista de
exclusion curada que no puedo validar sin datos reales de estructuras — mostrar una distancia falsa
a un ion seria peor que no mostrar nada.

Unificacion parcial de la capa de inspector de pockets: `setReprButtonPressed`, `inspectPocket`,
`clearPocketSelection`, el toggle `Show only selected pocket` y el listener global de click —
exactamente el codigo donde vivio la regresion real de `pocketInspector.hidden` — se extrajeron a
`static/js/pages/pocket-inspector.js` (`window.tpPocketInspector.createPocketInspector(...)`), usado
ahora por las dos paginas en vez de mantener ~100 lineas duplicadas. Funciona igual con NGL o con el
fallback 3Dmol.js de `protein.html` porque solo llama a `window.toogle_view`/`window.ngl_zoom_to`,
que cada pagina/renderer ya expone. **No** se unifico `initStructureComponent`/
`registerShapeComponent` en si (el init de representaciones NGL, el fallback 3Dmol.js completo, y el
switching alt/primary basado en atributos de tabla vs. el picker multi-estructura) — alcance real,
descubierto al leer el codigo completo, mucho mayor al que sugeria esta linea: son dos arquitecturas
de inicializacion distintas, no una funcion duplicada de ~150 lineas. Fusionarlas es alto riesgo de
romper el visualizador de las dos paginas a la vez sin poder probar en un navegador real.

Bug preexistente encontrado en verificacion en vivo (no introducido esta ronda): `protein.html`
nunca definia `tpColorTriplet`, solo `structure.html`. Como las dos paginas comparten
`ngl_pocket_representations.js`, cualquier pocket con alpha spheres reales (`core_points`) tiraba
un `ReferenceError` silencioso (atrapado por el try/catch de `initStructureComponent`) que abortaba
todo lo que venia despues en esa funcion: wiring de los botones de modo, spin, y el
`component.autoView()` final — exactamente los sintomas reportados (cartoon/surface no respondia,
spin no respondia, vista descentrada y recortada). Corregido agregando la misma funcion a
`protein.html`.

A partir de ese bug, se repensó el visualizador embebido de `protein.html`: en vez de mantener el
mismo toolbar completo que `structure.html` (modo cartoon/density, zoom in/out, reset zoom, spin),
pasó a ser una vista previa liviana — cartoon + pockets, sin toolbar — con foco en abrir el visor
fullscreen para interacción real. De paso salió a la luz que
`STRUCTURE_VIEWER_CONFIG.enable3DmolViewer` estaba hardcodeado en `false`, es decir que el fallback
completo a 3Dmol.js (~285 lineas: `initStructureViewerWith3Dmol`, el script de 3Dmol.org,
`molViewerInstance`) era codigo muerto en produccion — se elimino por completo sin riesgo de cambio
de comportamiento. El arrastre/zoom con el mouse sigue funcionando igual (nativo de NGL, no dependia
de los botones), y lo que sí es evidencia real (Inspect/toggle de pockets, comparar estructura
experimental vs. predicha, VMD, abrir el visor completo) sigue intacto. Pulido visual: glow ambiente
detras del canvas (mismo patron de gradiente radial que el grafo metabolico), hover-lift en las dos
acciones que quedaron, y una leyenda "Drag to rotate / scroll to zoom" ya que los botones que lo
insinuaban desaparecieron. Esto reduce bastante la superficie que podria volver a desincronizarse
entre las dos paginas — la causa raiz de esta regresion y de la de `pocketInspector.hidden`.

Dos rondas mas de pulido a partir de feedback en vivo: (1) spinner animado en el estado "Loading 3D
structure..." de las dos paginas (antes solo texto en italica) — mismo patron de anillo giratorio
que ya usaban los grafos de metabolismo, con `prefers-reduced-motion` respetado. (2) reordenamiento
de la seccion en `protein.html`: los pockets ahora aparecen justo despues del canvas/leyenda en vez
de despues de la tabla de evidencia estructural (que obligaba a scrollear de mas para llegar a lo
que en general se quiere ver); esa tabla paso a un disclosure cerrado por defecto ("All structural
evidence") debajo de los pockets, mismos datos y mismos botones "Switch". El "Switch" perdido de
vista se reemplazo por un selector compacto tipo dropdown, calcado del picker de `structure.html`
(abre hacia abajo en vez de hacia arriba, porque esta cerca del tope de una seccion scrolleable y no
al pie de un toolbar fijo) — sin tocar Python: los labels que necesitaba (`primary_structure_label`,
`alt_structure_label`, etc.) ya estaban calculados en `ProteinView.py` pero nunca se usaban en
ningun template. El picker deliberadamente solo ofrece los dos slots con datos de pockets reales
(`primary`/`alt`); cambiar a cualquier otra estructura cargada sigue yendo por el "Switch" de la
tabla demovida, porque un picker mas lindo que lleve a un pocket vacio para una 3ra estructura seria
peor que la tabla que reemplaza. Ademas se fusiono el hint de arrastre/zoom y la leyenda de scores
en una sola fila (antes dos lineas apiladas).

Bug real encontrado por una captura de pantalla, no solo cosmetico: el commit `1d44143`
("Simplify pocket viewer controls", 12/07) saco el boton `.js-inspect-pocket` de las cards pero
`pocket-inspector.js` sigue escuchando clicks especificamente en esa clase — confirmado con grep
que la clase no existia en ningun template. Consecuencia: el panel "Selected pocket" completo
(score, residuos, metodo, y las propiedades derivadas agregadas hoy) era imposible de abrir en
las dos paginas desde esa fecha. Confirmado con la usuaria que sacar el boton separado fue
intencional (no un olvido) — el header de la card (nombre + score) pasa a ser el disparador
(click o teclado, `role="button"`), sin agregar un boton nuevo. De paso, feedback de "no se ve
premium": las acciones Zoom/lista-de-residuos tenian el mismo peso visual que los toggles de capa,
y "Residues" aparecia como nombre de toggle Y de accion con significados distintos — ambas pasaron
de `tp-btn--outline` a `tp-btn--clear` (variante ya definida en `masterpage.html`, discreta pero
con borde/fondo real) en vez de un override ad-hoc con `!important` que las dejaba sin ninguna
apariencia de boton. Se elimino `.pocket-card-actions--primary` (CSS muerta del boton sacado el
12/07) de las dos hojas de estilo. El toggle de capa "Surrounding residues" se renombro a "Nearby"
(la accion de listar residuos volvio a llamarse "Residues", mas corto — "Residue list" se cortaba
en dos lineas dentro del ancho fijo de la fila de acciones, visible en una captura en vivo). El
campo "Pocket properties" del inspector pasa de un solo string concatenado en fuente monoespaciada
(se leia como volcado de datos crudo) a chips individuales en fuente normal — sin tocar Python, ya
que el string ya venia separado por " | "; `pocket-inspector.js` lo divide y arma un chip por hecho.
El campo "Residues" del mismo panel dejo de duplicar la lista cruda de numeros (ya disponible via
el boton "Residues" de la card) y ahora muestra solo el conteo ("19 residues").

Unificacion de `initStructureComponent`/`registerShapeComponent` cerrada: comparando linea por
linea las dos paginas, lo unico que seguia siendo codigo identico era `registerShapeComponent`
(~40 lineas, registro de esferas alpha de FPocket/P2Rank como shape de NGL) — todo lo demas (modo
density, toolbar de zoom, spin, chain-color para comparar alt/primary) ya es intencionalmente
distinto desde que `protein.html` paso a ser vista previa liviana. Se extrajo esa unica funcion
a `static/js/pages/ngl-shape-registry.js` (`window.tpNglShapes.createShapeRegistry(...)`), usada
por las dos paginas. No hacia falta fusionar el resto: son dos arquitecturas de init distintas
a proposito, no una duplicacion accidental.

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

**Implementado (primer recorte: solo visualizacion, sin tocar filtros ni logica de scoring).**

Grilla "Target profile" rediseñada como data sheet academica: flags de riesgo con
icono+color de tono en vez de texto plano, metricas porcentuales con barra de magnitud,
tipografia monoespaciada tabular para valores — cero cambios de logica/backend. De paso,
corregido un grid con celda fantasma al final de fila y valores largos sin espacios que se
recortaban.

**Pendiente para avanzar.**

- Exponer los filtros de identidad/cobertura/e-value/organismo (ya existen como filtros numericos
  genericos en la lista de proteinas via `_NUMERIC_FILTER_PLACEHOLDERS` en `protein_list.py`)
  tambien desde la propia seccion off-target de la pagina de proteina.
- Explicacion de riesgo mas rica (oracion interpretativa por eje, tipo la que ya existe para metabolismo).
- Integracion explicita con estructura/ligandos/drogabilidad/score final.

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

Agregar un agente/chat IA que ayude a explorar proteinas, filtros, scores, ligandos, estructuras y evidencia cargada en TPW. Requisito explicito: agnostico a que API de LLM se use (Claude u OpenAI intercambiables).

**Alcance propuesto.**

- Responder preguntas usando datos del sistema.
- Explicar por que un target aparece priorizado.
- Sugerir filtros y comparaciones.
- Ayudar a interpretar evidencia estructural, metabolica y off-target.
- Citar las fuentes internas usadas para cada respuesta.
- Ejecutar acciones reales en la UI a pedido del usuario (ej. aplicar filtros), no solo responder texto.

**Implementado.**

Fundacion agnostica a proveedor (`tpweb/services/llm/`): interfaz `LLMProvider` neutral con
adaptadores reales para Anthropic y OpenAI (seleccionable via `TPW_LLM_PROVIDER`), loop agentico
generico (`agent.py`), y tools con alcance de genoma/proteina siempre re-derivado y validado
server-side a partir de la URL de la pagina (nunca confiado del cliente). Drawer global
(panel lateral, no burbuja) con historial stateless por pestaña, chips de prompts sugeridos, y
Markdown completo (tablas, bloques de codigo, listas ordenadas, links) con una pasada visual
premium (avatar, entrada animada, indicador de "pensando", hover-lift, focus ring de marca).

Tools disponibles: `apply_filters`/`clear_filters`/`list_available_filters` (mismo mecanismo de
sesion que `ProteinListView`), `search_proteins`, `explain_target` y, para auditoria/comparacion,
`audit_target_evidence`/`compare_targets` (`target_evidence.py`) — devuelven texto/tabla ya
formateado en vez de JSON crudo, marcando explicitamente evidencia `not loaded` para que el
modelo no la confunda con evidencia negativa. El agente ahora tambien recibe un snapshot
compacto y sanitizado del estado de la UI (`page_state`: filtros, sort, pocket/estructura
seleccionada, filas visibles) junto a cada mensaje, asi que entiende la pagina completa y no
solo la proteina activa. Corridas de verificacion en cluster (OpenAI real via Responses API,
`manage.py check`) sin errores; algunos bugs de despliegue ya resueltos (sidebar cortado al
agregar el boton Assistant, persistencia de config de OpenAI entre restarts).

Costos/tokens: `LLMResponse` ahora carga `Usage` (input/output tokens, neutral, ambos
proveedores), acumulado por `Agent.run()` a lo largo de todo el loop de tool-use. `AgentChatView`
loguea por request modelo, tokens, latencia, turnos y tool calls (o el error) via el logger
`tpweb.agent`. Cada resultado de tool queda capado a 8000 caracteres, y el total acumulado de
resultados de tools en una misma conversacion a 32000 — antes solo el primero estaba acotado.
Budget mensual: resuelto fuera de la app — tope de $20/mes configurado directamente en la
plataforma de OpenAI (no en TPW). Si se llega al limite, OpenAI corta las requests y el usuario
ve el mensaje generico de "assistant unavailable" con boton Retry ya implementado; no hace falta
logica de budget propia. Permisos de acciones: decidido con la usuaria mantener aplicar/borrar
filtros directo, sin pedir confirmacion — es reversible con un click y no toca datos ni afecta a
otros usuarios, asi que confirmar seria friccion innecesaria. Es la unica accion mutante que
existe hoy; cuando se agreguen tools que sí mutan datos reales (crear score, guardar columnas,
exportar) esta misma pregunta hay que volver a hacerla para esas, no asumir que aplica el mismo
criterio.

Cierre de pendientes de esta ronda: `page_state` ahora captura spin/modo de vista del visualizador
3D (las dos paginas, embebida y fullscreen). Errores del drawer ya no filtran detalle tecnico del
proveedor (el log completo sigue yendo al servidor) y los que son reintentables muestran un boton
"Retry" que reenvia el mismo mensaje. Nuevo toggle "Biologist mode" en el drawer (persistido en
localStorage): activo, pide al modelo definir brevemente terminos tecnicos la primera vez que los
usa. Wiring de tools y de system prompt extraido de `AgentChatView` a `tool_registry.py`/
`prompts.py` para que el nuevo comando `evaluate_agent` (corre los prompts de evaluacion contra
el loop real) los reuse en vez de duplicarlos.

Corrido `evaluate_agent` contra KpATCC43816 (5/5 tools esperadas llamadas). Lectura manual de las
respuestas: sin evidencia inventada — los numeros son consistentes entre casos y contra datos ya
validados en otra sesion (druggability 0.911 de VK055_0002). Encontrados y corregidos dos
problemas reales: `is_chokepoint` en `target_evidence.py` colapsaba "sin datos metabolicos
cargados" y "confirmado que no es chokepoint" en el mismo valor `"no"` — exactamente la confusion
falta-vs-negativo que el system prompt le prohibe al modelo, pero el origen estaba en la tool, no
en el modelo; ahora son tres valores distintos (`yes`/`no`/`not loaded`). Y el caso "buscame
targets sin off-target y buen pocket" gasto 17871 tokens de input en 6 turnos porque el modelo
llamaba `apply_filters` una vez por cada criterio en vez de mandarlos juntos en el array
`changes` que la tool ya soporta — la descripcion de la tool ahora lo pide explicitamente.
`create_binders_dict` (y el resto de la logica de ligandos que vivia en `ProteinView.py`) se
extrajo a `tpweb/services/binder_summary.py`, sacando el ultimo import diferido/circular que
quedaba de la ronda de extraccion anterior.

Corridas 2 y 3 de `evaluate_agent` confirmaron los fixes y encontraron dos cosas mas: la ambiguedad
falta-vs-negativo tambien afectaba a `centrality` (misma causa raiz que `is_chokepoint` — corregido
igual), y el system prompt no distinguia "buscame/mostrame targets" (pregunta, debe llamar
`search_proteins` y nombrar candidatos concretos) de "aplica este filtro" (accion explicita sobre la
sesion) — el modelo a veces aplicaba filtros sin responder nada. Con la regla explicita agregada,
la 3ra corrida ya devolvio 10 candidatos nombrados con su druggability en vez de una respuesta vacia.

Con esto, la card de Agente IA queda sin pendientes de codigo.

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

**Mayormente cubierto por el grafo unificado nuevo** (ver `Informacion metabolica` arriba): tamaño
por reacciones, color por densidad de chokepoints y score promedio/mejor por ruta ya se ven en el
grafo genome-wide. Lo que falta especificamente de esta card:

**Alcance propuesto.**

- Ranking de rutas por cantidad de buenos targets (hoy solo existe como grafo, no como lista/tabla ordenable).
- Metabolitos clave y cuellos de botella a nivel genoma completo (hoy el grafo bipartito de metabolitos es por-pathway, no agregado).
- Export CSV del ranking de rutas.

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

Utilidades globales de entrada sutil y profundidad (`ui-system.css`: `tp-page-hero`/`tp-ui-panel`)
aplicadas a Genome overview, Protein detail, Protein list, Metabolism overview/pathway, Binder
detail y ahora tambien el structure viewer fullscreen (secuencia de entrada escalonada en su HUD
flotante, con keyframes propios para no romper el `translateX(-50%)` de centrado del toolbar).
Auditoria completa de las ~15 paginas de la app: sin hex/rgba hardcodeado en ninguna, tokens
muertos referenciados corregidos (`--tp-color-brand-400`, `--tp-font-body`, algunos otros),
sombras sueltas remapeadas a la escala `--tp-shadow-xs/sm/md/lg`. Bug sistemico encontrado y
arreglado en el keyframe compartido `tp-ui-enter`: dejaba un `transform` persistente
(`animation-fill-mode: both` terminando en `translateY(0)` en vez de `none`) que rompia el
posicionamiento de cualquier `<select>` nativo en un ancestro — afectaba a Genome overview y BLAST.

Checklist de pre-merge documentado en `docs/VISUAL_CHECKLIST.md` (color/tokens, profundidad/motion,
tipografia de datos, accesibilidad, y el bug del keyframe con transform persistente para no repetirlo).
Structure viewer: micro hover-lift agregado en los botones del toolbar flotante (antes solo
cambiaban background/color/opacity). Header de `protein.html`: "Genome: X" era una linea de texto
suelta con estilo propio, duplicando el nombre de genoma que ya esta en el breadcrumb — se unifico
como un chip mas en la misma fila que Gene/3D evidence/UniProt, y se elimino el CSS que quedo sin uso.

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

1. Revisar en navegador/cluster lo implementado: metabolismo, target summary, ligandos, pockets y agente.
2. Agente IA para exploracion de targets: contexto de pagina, evaluaciones, costos, Markdown y modo biologo.
3. Premium UI consistency pass.
4. Visualizacion de Proteina 2.0.
5. Visualizacion y control de pockets.
6. Comparacion FPocket vs P2Rank.
7. Drogabilidad por fuente y estructura.
8. Integracion AlphaFill (ligando trasplantado sobre AlphaFold/ColabFold ya existente).
9. Sitios funcionales y anotaciones estructurales.
10. Priorizacion estructural completa.
11. Off-target 2.0.
12. Sequence & feature viewer 2.0.
13. Cross-references hub.
14. Pathway-level target prioritization.
15. Red de señalizacion/regulacion por proteina (KEGG PPI).
16. Evidence provenance / audit layer.
17. Constructor de score mejorado.
18. Columnas custom para analisis.
19. Auditoria Target viejo e integraciones externas (Ligysis, CSA Atlas).
