# TargetPathogen roadmap

Documento vivo para ordenar tareas de producto e implementacion. La idea es mantener aca el backlog tecnico-funcional que antes estaba en Notion, separado por estado real: hecho, en progreso, pendiente y descartado por ahora.

## Hecho / en uso

### Target executive summary

Resumen ejecutivo arriba de la pagina de proteina para responder rapido si un target parece prometedor.

**Incluye.**

- Frase interpretativa unica combinando score, metabolismo, drogabilidad, ligandos, estructura, off-target y conservacion.
- Bloques `Strengths`, `Risks` y `Missing evidence`.
- Links internos a las secciones que justifican cada punto.
- Badges especificos cuando hay datos completos:
  - Pocket consistente FPocket + P2Rank.
  - Estructura experimental disponible.
  - Baja similitud humana.
  - Ligando conocido fuerte.

### Ligandos, ChEMBL, PDB y quimica del target

Dashboard de senal quimica en la pagina de proteina.

**Incluye.**

- Evidencia directa y por homologos separada por fuente: PDB, ChEMBL y ZINC.
- Links externos a ChEMBL, RCSB PDB y ZINC.
- Zoom inline de la estructura 2D del ligando.
- Afinidad experimental estimada en nM/uM/mM junto al `pchembl` crudo.
- Boton `Open crystal` para enfocar ligandos PDB en el visualizador 3D.

**Pendiente relacionado.**

- Transferencia de ligandos desde homologos.
- Se sigue en la card `Integracion AlphaFill / Ligysis / CSA Atlas`.

### Genome overview 2.0 / ranking compuesto explicable

El overview del genoma funciona como tablero macro, no como reflejo de una sola feature.

**Implementado.**

- Ranking principal `Top evidence-convergent candidates`.
- Score heuristico transparente de 0 a 15.
- Tiers `Strong`, `Moderate` y `Limited`.
- Factores combinados:
  - Pocket FPocket/P2Rank.
  - Ligandos directos.
  - Ligandos transferidos por homologos o ZINC.
  - Off-target humano y microbioma.
  - Esencialidad.
  - Conservacion.
  - Estructura disponible.
  - Contexto metabolico.
- Chips por proteina explicando por que aparece arriba.
- Ranking secundario `Worth a fresh look` para candidatos druggable/selectivos sin evidencia quimica explorada.
- Export CSV del ranking compuesto con desglose completo de senales.


### Visualizacion y control de pockets

El visualizador permite elegir un pocket puntual e inspeccionarlo en detalle sin perder el contexto del entorno.

**Implementado.**

- Accion `Inspect`.
- Al inspeccionar:
  - Centra la camara.
  - Aisla la capa del pocket.
  - Atenua la proteina para mejorar foco geometrico.
  - Muestra panel persistente de detalle.
- Panel de detalle con:
  - Metodo.
  - Score.
  - Residuos.
  - Centro geometrico.
  - Consenso FPocket/P2Rank.
  - Sitio funcional anotado mas cercano cuando existe.
- Toggle `Show only selected pocket`.
- Separacion visual entre:
  - Pocket especifico / alpha spheres.
  - Residuos.
  - Superficie.
  - Labels.
- Paridad entre:
  - Pagina de proteina.
  - Full viewer.

### Agente IA para exploracion de targets

Chat/agente en drawer global para explorar proteinas, filtros, scores, ligandos, estructura y evidencia cargada.

**Base tecnica.**

- Agnostico a proveedor LLM: OpenAI o Anthropic intercambiables.
- Alcance de genoma/proteina re-derivado server-side desde la URL.
- No confia en el cliente para permisos ni scope biologico.
- Historial stateless por pestana.
- Snapshot compacto de UI (`page_state`) en cada mensaje.
- Logging de:
  - Tokens.
  - Costo estimado.
  - Latencia.
  - Tool calls.
  - Errores.
- Budget resuelto desde la plataforma del proveedor.

**Tools disponibles.**

- `search_proteins`.
- `explain_target`.
- `audit_target_evidence`.
- `compare_targets`.
- `list_available_filters`.
- `apply_filters`.
- `clear_filters`.

**UX.**

- Drawer global.
- Chips de prompts sugeridos.
- Markdown renderizado:
  - Tablas.
  - Codigo.
  - Listas ordenadas.
  - Links.
- Boton retry para errores reintentables.
- Toggle `Biologist mode`.

**Evaluacion.**

- Comando `evaluate_agent`.
- Corrido contra KpATCC43816.
- Validado que use las tools esperadas.
- Hallazgos corregidos:
  - Diferenciar dato faltante vs evidencia negativa.
  - No confundir "buscame/mostrame" con "aplica filtro".
  - Reducir tool calls innecesarios para bajar tokens.


### Premium UI consistency pass

Pasada sistematica de consistencia visual en la app.

**Incluye.**

- Tokens de color.
- Tokens de sombra.
- Tipografia y jerarquia de datos.
- Hover-lift.
- Entradas sutiles.
- Botones con variantes existentes.
- Reduccion de valores hardcodeados.
- Structure viewer incluido en la pasada.
- Checklist de pre-merge en `docs/VISUAL_CHECKLIST.md`.

**Estado.**

- Implementado como pasada general.
- Conviene mantenerlo como criterio de revision continua, no como tarea cerrada para siempre.

### Informacion metabolica

Incorpora informacion metabolica al analisis de targets.

**Fuentes usadas.**

- SBML de MetaFlux/Pathway Tools.
- TSV de resultados metabolicos.
- `network.sif`.
- KEGG para rutas y nombres.

**Implementado.**

- Ingesta completa por genoma.
- `Metabolic context` en pagina de proteina.
- Integracion al scoring.
- Oracion interpretativa automatica.
- Grafo de vecindario embebido.
- Ranking de rutas a nivel genoma, con busqueda por nombre de ruta o proteina.
- Pagina de mapa por ruta individual.
- Grafo genome-wide estilo Krona.
- Layout tipo MetaCyc (dagre) con direccion real segun el rol reactivo/producto de cada reaccion, no segun la adyacencia cruda del `network.sif`. Originalmente de arriba a abajo por pedido de las biologas; cambiado a izquierda-derecha en los 3 grafos despues de que el sentido vertical rompiera repetidamente el ajuste del canvas en vias chicas/lineales (una cadena lineal queda ancha y baja en LR, que es la forma natural de un canvas siempre ancho) -- decision tomada a criterio propio, no vuelta a validar con las biologas todavia.
- Flecha doble para reacciones reversibles, consistente en tabla, tooltips y los tres grafos (vecindario, ruta especifica y genome-wide).
- Leyenda de densidad de chokepoints con los 4 niveles reales que usa el grafo.
- Grafos chicos/lineales ya no quedan perdidos en un canvas ancho vacio.
- Colores de aristas/flechas con contraste alto (mismo token que el texto) en los tres grafos.
- Pagina de red metabolica de una proteina rediseñada como pagina de detalle (hero con metricas, quick-nav, cards separadas para Pathways/Network/Selected reaction/Catalyzed reactions), reemplazando la sidebar comprimida original.
- Fuente sans-serif (no monoespaciada) y forma de nodo consistente (circulo=reaccion, diamante=chokepoint) en los tres grafos; texto de chokepoint ya no compite en color con el resto.
- Labels de nodos ya no se truncan con largo fijo -- Cytoscape recorta solo cuando el texto realmente no entra, en vez de siempre.
- Link a MetaCyc en toda tabla de reacciones (`reaction_id` ya es el frame id de BioCyc, no requiere dato nuevo), ademas del link a KEGG existente.
- Seccion "Connected pathways" en la pagina de vía especifica: reutiliza el mismo grafo genoma-completo ya calculado (`build_genome_metabolism_network`) filtrado a los vecinos directos de esa vía, en vez de forzar la idea de "red ego" dentro de la vista de todas las vías. Nota de "Connects to N" tambien agregada al ranking de rutas.
- Evaluado BiGG (sin dato/mapeo existente, patogenos raramente estan en su set de modelos curados) y Escher (herramienta de curacion manual, no hace auto-layout mejor que dagre) -- descartados por ahora, no vale la pena construir especulativamente.

**Feedback de biologas.**

- Les gusto:
  - `Metabolic context` en pagina de proteina.
  - Ranking de rutas.
- Pidieron layout mas ordenado estilo MetaCyc, direccion/reversibilidad claras y mayor contraste -- resuelto.

### Visualizacion de Proteina 2.0

Redisenar el visualizador 3D como experiencia completa.

**Implementado.**

- Spin apagado por defecto.
- Estados de botones sincronizados.
- Nota aclarando que FPocket/P2Rank son predicciones computacionales.
- Selector de estructura priorizado por fuente, cobertura y calidad (`sort_structures_by_preference` en `structure_sources.py`, ya conectado a ambos pickers).
- Toolbar de camara y modos en el full viewer (spin, cartoon/surface, zoom, reset, selector de estructura, export VMD).
- Toggle real de esquema de color en el full viewer: Uniforme / Por cadena / Por estructura secundaria, junto al toggle Cartoon/Surface. El preview embebido se dejo liviano a proposito, sin nuevos controles. "Por cadena" solo aparece cuando la estructura activa realmente tiene mas de una cadena.
- Estructuras multimericas: se corrigio una truncacion a una sola cadena en `experimental_structures.py`; ahora se muestran todas las cadenas (homooligomeros y proteinas fragmentadas), con backfill (`backfill_structure_chains`) para genomas ya cargados.
- Verificado en vivo: toggle de color y coloreo por estructura secundaria funcionando correctamente en el full viewer.

### Rendimiento: apertura lenta de genoma y proteina individual

Investigacion + fix de por que `/genome/<slug>` y `/protein/<id>` tardaban en abrir. Causa real: tres problemas independientes, no uno solo.

**Encontrado y arreglado.**

- No habia Redis en el stack del cluster (`REDIS_URL` siempre vacio, sin servicio definido) -- cada uno de los 3 workers de gunicorn tenia su propio cache en memoria sin compartir, asi que el cache de 15 min de `assembly_workspace.py` rendia ~1/3 de lo esperado ("a veces rapido, a veces lento" segun que worker atendia). Agregado servicio `redis` al `docker-compose.cluster.yml` (sin persistencia, es puro cache) + paquete `django-redis` que faltaba en `requirements/base.txt`.
- `pdb_structure()` (visor 3D, usado 2x por pagina de proteina y 1x por estructura en `/structure/<id>`) tenia un N+1 real (alpha-spheres por pocket) y re-consultaba en cada llamada 6 filas de referencia que nunca cambian -- bulk-fetch + cache en memoria del proceso.
- `ProteinView`/`assembly_workspace.py`: prefetches muertos, `_has_pocket_data` con query aparte pudiendo derivarse gratis de datos ya calculados, dos paths de scoring sin cachear (export CSV y scoring de una proteina para el chatbot), conteos duplicados/colapsables con `aggregate()`.
- Bug de yapa encontrado perfilando: `/protein/<id>` no validaba que el id perteneciera de verdad a una base `_prots` -- un id de la base del genoma completo (cromosoma) renderizaba igual, tratando miles de features del genoma entero como si fueran de una sola proteina (30s+). Ahora 404 inmediato.
- Mejora de percepcion adicional (no mide progreso real): mensajes en etapas en el loader global al navegar a estas dos paginas, en vez de un label estatico.

**Medido en vivo en el cluster (KpATCC43816), antes/despues de todo lo anterior.**

- Genoma, cache frio: 4.8s (una vez cada 15 min, esperable). Cache caliente: 0.16-0.17s, estable entre requests.
- Proteina con estructura experimental+predicted: 1.1s primera vez, 0.1-0.24s despues.
- Proteina sin estructura (96 features): 0.42-0.50s, estable.
- Indice en `ScoreParamValue.value` (considerado, no implementado): con estos tiempos no parece necesario. Queda en To Do por si vuelve a aparecer lentitud puntual en filtros de localizacion/druggability.

### Memoria del asistente (chatbot), por sesion de navegador

Persistencia server-side del historial del drawer, dividida en conversaciones multiples por sesion en vez de un solo hilo continuo de 7 dias sin cortes.

**Incluye.**

- Retencion fisica de 7 dias (`HISTORY_RETENTION`), corte automatico a conversacion nueva tras 45 min de inactividad o boton manual "Nueva conversacion".
- Selector de conversaciones previas en el drawer: reabrir, renombrar, borrar (confirmacion inline, sin popup nativo).
- Limpieza fisica via management command `clear_old_agent_chats` (sin Celery beat -- agendar por cron externo).
- Resolucion de contexto (que genoma/proteina esta en foco) corregida para las vistas de estructura 3D y de binder, que antes nunca resolvian scope y dejaban al asistente sin poder responder preguntas de genoma/target ahi. Sugerencias del chat (Explain target, Audit evidence, Clear filters, Find selective targets) ahora se muestran solo en las paginas donde tienen sentido.

## En progreso

### Batch de pedidos de las biologas (6/08 + reporte previo)

Dos documentos de las biologas (cambios de producto + bugs de una sesion de uso anterior)
implementados como prioridad, pausando el orden sugerido que tenia este roadmap hasta este punto.
No se cierra como "Hecho" todavia porque una parte necesita confirmacion en vivo (sin entorno
Django/browser local en la sesion donde se implemento) y quedan 2-3 puntos sin arrancar.

**Hecho (implementado y verificable por codigo).**

- P2Rank como valor de druggability principal mostrado (antes FPocket primero), ambos
  etiquetados explicitamente por fuente ("Druggability (P2Rank)"/"(FPocket)") con la estructura
  de origen visible.
- "With pocket score" ampliado a FPocket OR P2Rank (antes solo FPocket).
- Tooltips en las metric-pills principales del genoma (Proteins, With 3D structure, Annotated,
  With pocket score).
- Localizacion celular (PSORTb) movida de "Prioritization evidence" a "Functional annotation",
  con breakdown por compartimento en la card de evidencia del genoma.
- Visor 3D: capa de heteroatomos co-cristalizados (excluye solvente), toggle nuevo en la toolbar.
- Visor 3D: "Site 1/2" renombrado a "Pocket 1/2" en las cards de FPocket/P2Rank.
- Visor 3D: posiciones de residuos con codigo de aminoacido + numero (ej. Asp123), antes solo
  el numero.
- Visor 3D: color-by-chain/by-structure deshabilitado en modo Surface (silenciosamente no hacia
  nada ahi, ahora se grisea en vez de dejar clickear una opcion rota).
- Metabolism: la seccion de contexto metabolico de una proteina ahora siempre aparece, con
  estado vacio explicito + link a la red general del genoma cuando la proteina no esta asociada
  a la red importada.
- Header de proteina: el nombre (no el accession) pasa a ser el titulo principal; accession baja
  a linea secundaria con tooltip aclarando que viene del GenBank del genoma; genoma actual
  destacado con tipografia propia arriba del titulo.
- Chatbot: prompt reforzado para no tratar preguntas generales como si fueran sobre "esta
  proteina" solo por estar en una pagina de proteina.
- Terminologia: ultimas menciones de "bottleneck" reemplazadas por "chokepoint" en la app.
- Fix: bug real en el scroll-spy del quick-nav de proteina (`updateActive` en
  `protein-detail.js`) que podia marcar "Annotations" activo al aterrizar en "Sequence" si esta
  era corta -- ahora el click de un link fija el activo manualmente durante la animacion de
  scroll.
- Metabolismo: click en una fila de la tabla de reacciones centra/resalta el nodo
  correspondiente en el grafo de la pagina de la via (feature nueva, no existia).
- Metabolismo: espaciado del inspector del grafo genome-wide (chokepoints y demas campos)
  ajustado -- quedaba muy pegado.
- Nota de curacion + cita (Ramos et al. 2018, Scientific Reports) agregada en las paginas de
  metabolismo y como seccion nueva en la pagina de Methodology, aclarando que la red es curada
  manualmente, no generada automaticamente.
- Iconos de ayuda (?) agregados a los headers de Evidence available, Prioritization evidence y
  Metabolic context.
- Logging real del error (404/CORS/archivo corrupto) al fallar la carga de una estructura PDB en
  el visor, antes silencioso.

**En curso (implementado, pendiente de confirmar en vivo).**

- Busqueda por secuencia de aminoacidos (blastp) embebida en la tabla de proteinas, reusando el
  indice proteico que el pipeline ya genera por genoma (stage 9) -- falta correr una busqueda
  real contra un genoma cargado.
- Boton "Open full pathway map" del grafo genome-wide: investigado a fondo, el codigo esta
  correctamente conectado para el tap sobre un nodo de pathway/cluster (para nodos de
  reaccion/metabolito el detalle es solo hover por diseño actual, sin boton ahi) -- no se
  encontro una URL rota ni un handler faltante. Falta repetir el click real en vivo para
  confirmar si el problema persiste o era ese caso de hover-only.
- Bug puntual "Unable to load PDB structure" en protein 35767: se agrego logging real del error
  (404/CORS/archivo corrupto) al fallar la carga de una estructura en el visor, antes
  silencioso -- falta revisar en el cluster si ese caso especifico sigue reproduciendo.

**Falta (no arrancado, bloqueado por dato o por definir).**

- Metabolismo Kp13: los 3 archivos de `load_metabolism` (SBML, TSV, network.sif) todavia no
  estaban listos -- sin archivos no hay tarea de codigo.
- "Organizacion botones": reporte demasiado abstracto (no se sabe pagina ni botones) -- a
  re-consultar con las biologas.
- "Se ve raro": reporte demasiado abstracto (sin pagina/detalle especifico) -- a re-consultar
  con las biologas.

El "Orden sugerido" de este roadmap (Off-target 2.0 primero, etc.) queda retomado cuando este
batch se cierre del todo.

### Off-target 2.0

Mejorar la lectura de similitud contra humano, microbioma y otros organismos relevantes.

**Hecho hasta ahora.**

- Rediseño visual de `Target profile`.
- Estilo data sheet academico.
- Flags de riesgo por color.
- Barras de magnitud para metricas porcentuales.
- Score compuesto visible en la pagina de proteina por primera vez: card "Composite score" con el
  valor bajo la formula default del usuario y los 5 factores que mas pesaron (`build_score_breakdown`
  en `protein_summary.py`, reutiliza los mismos calculos que ya usaba el listado de proteinas).
- Explicacion de riesgo enriquecida para hit humano/microbioma: la oracion ahora menciona el score
  de drogabilidad (FPocket) cuando existe, y el link ya no apunta a si misma sino a la evidencia de
  ligandos (`#section-binders`) -- antes de descartar el target solo por riesgo off-target.

**Falta.**

- Filtros reales por Identidad/Cobertura/E-value/Organismo: bloqueado por dato -- hoy solo se
  guarda el mejor hit humano (identity+evalue) y un conteo de especies para microbioma; coverage y
  organismo por hit no se persisten en ningun lado (se descartan en `fast_command.py` al colapsar
  al mejor hit). Necesita modelo nuevo por-hit, cambio de pipeline de ingesta y backfill/reimport
  de genomas ya cargados -- merece su propio plan, no encarado todavia.

## To Do

### GC content faltante en genomas importados/curados

Investigado (6/08): "Imported genome details" muestra "GC —" para genomas que entraron por
import externo/curado (ej. KpATCC43816). No es un bug de render -- `genome_metadata.py` ya
tiene una regla intencional que muestra "—" en vez de "0%" cuando la propiedad `GC` importada
vale literalmente `0`/`0.0` (evita mostrar un cero falso cuando el dato nunca se cargo). La
causa real es que el GC no se calculo/importo para estos genomas.

**Alcance.**

- Calcular GC directo desde el FASTA de la secuencia ya cargada (`EntryLength` ya se conoce
  por genoma, el mismo camino podria dar GC sin depender de que el import externo lo traiga).
- Decidir si se corre una sola vez como backfill para genomas ya cargados con "—", o se agrega
  como paso del import/pipeline para genomas nuevos.

### Comparacion FPocket vs P2Rank

Comparar predicciones de pockets entre ambos metodos.

**Implementado parcialmente.**

- Comparación por distancia entre centros dentro de la misma estructura.
- Conteo y porcentaje de residuos compartidos usando cadena, número de residuo y código de inserción.
- Solapamiento espacial completo: distancia de centros (umbral 8 Å) + residuos compartidos + cobertura del sitio mas chico + Jaccard (`StructureView.py`), mas alla de lo que decia el roadmap.
- Visualización del consenso en las cards de FPocket y P2Rank del detalle estructural.

**Alcance.**

- Badge de consenso estructural: hoy es un bloque de info dentro del accordion de pockets, no un chip compacto a nivel resumen; la fuerza "Independent pocket support" usa umbrales de score, no el consenso geometrico ya calculado.
- Filtro para priorizar proteinas donde ambos metodos coinciden en el pocket principal: no existe, el consenso no esta persistido a nivel de ranking/lista.

### Sitios funcionales y anotaciones estructurales

Mostrar residuos cataliticos y sitios funcionales sobre la estructura.

**Fuentes a evaluar.**

- UniProt.
- CSA Atlas.
- Ligysis.
- Target viejo.

**Alcance.**

- Distinguir tipos de anotacion:
  - Catalitico.
  - Ligando.
  - PPI.
  - Cofactor.
  - Mutacion.
  - Dominio.
- Panel de evidencia con fuente y confianza.

### Drogabilidad por fuente y estructura

Redisenar la seccion de drogabilidad.

**Alcance.**

- Separar valores por programa/fuente.
- Separar valores por tipo de estructura:
  - PDB experimental.
  - AlphaFold DB.
  - ColabFold.
- Mostrar a que estructura corresponde cada valor.
- Definir valor default usado en tabla principal.
- Dejar auditable la decision de prioridad.

### Priorizacion estructural completa

Estrategia integral para priorizacion basada en estructura.

**Debe combinar.**

- Disponibilidad de estructura.
- Calidad.
- Cobertura.
- Tipo de estructura.
- Pockets.
- Consenso FPocket/P2Rank.
- Ligandos directos.
- Ligandos por homologos.
- Sitios cataliticos.
- Drogabilidad.
- Off-target.
- Resolucion y metadata PDB.

### Constructor de score mejorado

Mejorar la pantalla de formulas de score.

**Alcance.**

- Funciones y operaciones cerca de la formula.
- Preview en vivo sobre subconjunto de proteinas.
- Sugerencias de variables segun filtros activos.
- Validacion segun tipo de dato.
- Mensajes de error accionables.

### Columnas custom para analisis

Permitir columnas custom por genoma o analisis.

**Alcance.**

- Tipo categorico o cuantitativo.
- Uso en filtros.
- Uso en ordenamiento.
- Uso en visualizaciones.
- Uso futuro en scores.
- Validacion al importar.
- Provenance de quien cargo cada columna.

### Auditoria y migracion de funcionalidades del Target viejo

Revisar el Target viejo y documentar que conviene migrar o reinterpretar.

**Salida esperada.**

- Lista priorizada de features.
- Referencias de flujo.
- Decision por feature:
  - Migrar.
  - Adaptar.
  - Descartar.
  - Investigar.

### Integracion AlphaFill / Ligysis / CSA Atlas

Evaluar fuentes externas para enriquecer estructura y ligandos.

**Implementado parcialmente.**

- Loader curado `load_csa` para sitios catalíticos CSA/M-CSA sobre estructuras PDB cargadas.
- Mapeo estricto por PDB, cadena, residuo, código de inserción y nombre de residuo opcional.
- Separación de copias de un sitio por cadena y `dry-run` con validación real de residuos.
- Sitios activos/de unión de UniProt sobre AlphaFold DB y ColabFold, integrados al pipeline después de cargar estructuras.
- En ColabFold, transferencia mediante alineamiento de secuencia con umbrales de identidad y cobertura; no se asume numeración 1:1.
- Etiquetas completas de fuente, sitio y cadena en el visor.

**AlphaFill.**

- Prioridad alta.
- Mejor costo/beneficio evaluado.
- Base publica `alphafill.eu`.
- Trasplanta ligandos/cofactores desde estructuras homologas resueltas experimentalmente sobre modelos AlphaFold.
- API por UniProt ID.

**Ligysis.**

- Potencial fuente para sitios de union e interacciones ligando-proteina.
- Licencia CC-BY y exportación por consulta, sin dump masivo identificado.
- La numeración reportada es canónica de UniProt, no numeración de autor PDB.
- Pendiente decidir si se ejecutará el pipeline propio de Ligysis para cobertura genómica.

**CSA Atlas.**

- Loader implementado.
- Pendiente validar contra un archivo real de CSA/M-CSA y una base del cluster antes de considerarlo evidencia operativa.
- Pendiente definir la fuente/versión curada que se conservará para importaciones reproducibles.

**Salida esperada.**

- Que fuente usar para cada dato.
- Como importarla.
- Como mapearla.
- Como mostrarla.
- Riesgos de licencia, cobertura y mantenimiento.

### Sequence & feature viewer 2.0

Pasar `Sequence` de texto plano a visualizacion funcional.

**Alcance.**

- Mapa lineal.
- Dominios/regiones/sitios funcionales.
- Grid de residuos con hover.
- Busqueda por posicion o motivo.
- Links desde residuos anotados hacia estructura 3D.

### Cross-references hub

Agrupar identificadores externos en una seccion unica.

**Fuentes.**

- UniProt.
- KEGG.
- BioCyc.
- NCBI.
- PDB.
- ChEMBL.

**Organizacion.**

- Sequence.
- Structure.
- Chemistry.
- Pathways.
- Literature.

### Pathway-level target prioritization

Extender metabolismo desde target individual hacia decision a nivel ruta.

**Ya cubierto parcialmente.**

- Grafo genome-wide.
- Tamano por reacciones.
- Color por densidad de chokepoints.
- Score por ruta.

**Falta.**

- Ranking de rutas como lista/tabla ordenable.
- Buenos targets por ruta.
- Metabolitos clave a nivel genoma completo.
- Export CSV del ranking de rutas.

### Evidence provenance / audit layer

Hacer explicita la procedencia de cada dato usado para priorizar.

**Alcance.**

- Fuente.
- Fecha de importacion.
- Archivo/comando.
- Version cuando aplique.
- Badge o tooltip por seccion.
- Log de importaciones por genoma.
- Ayuda para reproducibilidad y debugging en cluster.

### Red de senalizacion/regulacion por proteina (KEGG PPI)

Grafo de interacciones proteina-proteina y regulatorias.

**Diferencia con metabolismo.**

- No es grafo de reacciones.
- Representa relaciones biologicas directas entre genes/proteinas.

**Relaciones KEGG KGML.**

- Activation.
- Inhibition.
- Phosphorylation.
- Expression.
- Binding.

**Relevancia.**

- Sistemas de dos componentes.
- Regulones de virulencia.
- Cascadas de senalizacion.

## Ideas evaluadas y descartadas por ahora

Auditoria funcional de `target-human-web`, el proyecto companero de target humano.

**Descartado o en espera.**

- **Retrosynthesis benchmark**
  - Poster estatico.
  - Sin computo real estable.
  - Nada que migrar por ahora.
- **Matching de rutas de sintesis por patentes**
  - Interesante como complemento de LigQ_2.
  - Bloqueado por falta de dataset de patentes.
- **Tissue expression y variantes clinicas**
  - Especifico de humano.
  - No aplica a targets de patogeno.
- **RDKit-JS**
  - Dependencia cargada pero no usada.
  - No hay funcionalidad real que migrar.

## Orden sugerido

1. ~~Visualizacion de Proteina 2.0.~~ Hecho y verificado en vivo.
2. Off-target 2.0.
3. Comparacion FPocket vs P2Rank.
4. Drogabilidad por fuente y estructura.
5. Integracion AlphaFill.
6. Sitios funcionales y anotaciones estructurales.
7. Priorizacion estructural completa.
8. Sequence & feature viewer 2.0.
9. Cross-references hub.
10. Pathway-level target prioritization.
11. Red de senalizacion/regulacion por proteina.
12. Evidence provenance / audit layer.
13. Constructor de score mejorado.
14. Columnas custom para analisis.
15. Auditoria Target viejo e integraciones externas.
