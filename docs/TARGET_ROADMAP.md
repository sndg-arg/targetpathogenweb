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

## En progreso

### Visualizacion de Proteina 2.0

Redisenar el visualizador 3D como experiencia completa.

**Ya existe.**

- Spin apagado por defecto.
- Estados de botones sincronizados.
- Nota aclarando que FPocket/P2Rank son predicciones computacionales.
- Selector de estructura priorizado por fuente, cobertura y calidad (`sort_structures_by_preference` en `structure_sources.py`, ya conectado a ambos pickers).
- Toolbar de camara y modos en el full viewer (spin, cartoon/surface, zoom, reset, selector de estructura, export VMD).
- Toggle real de esquema de color en el full viewer: Uniforme / Por cadena / Por estructura secundaria, junto al toggle Cartoon/Surface. El preview embebido se dejo liviano a proposito, sin nuevos controles.
- Estructuras multimericas: se corrigio una truncacion a una sola cadena en `experimental_structures.py`; ahora se muestran todas las cadenas (homooligomeros y proteinas fragmentadas), con backfill (`backfill_structure_chains`) para genomas ya cargados.

### Off-target 2.0

Mejorar la lectura de similitud contra humano, microbioma y otros organismos relevantes.

**Hecho hasta ahora.**

- Rediseño visual de `Target profile`.
- Estilo data sheet academico.
- Flags de riesgo por color.
- Barras de magnitud para metricas porcentuales.

**Falta.**

- Exponer filtros desde la seccion off-target de la pagina de proteina.
- Filtros por:
  - Identidad.
  - Cobertura.
  - E-value.
  - Organismo.
- Explicacion de riesgo por eje.
- Integracion explicita con:
  - Estructura.
  - Ligandos.
  - Drogabilidad.
  - Score final.

## To Do

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

1. Revisar en navegador/cluster lo implementado: metabolismo, target summary, ligandos, pockets y agente.
2. Visualizacion de Proteina 2.0.
3. Off-target 2.0.
4. Comparacion FPocket vs P2Rank.
5. Drogabilidad por fuente y estructura.
6. Integracion AlphaFill.
7. Sitios funcionales y anotaciones estructurales.
8. Priorizacion estructural completa.
9. Sequence & feature viewer 2.0.
10. Cross-references hub.
11. Pathway-level target prioritization.
12. Red de senalizacion/regulacion por proteina.
13. Evidence provenance / audit layer.
14. Constructor de score mejorado.
15. Columnas custom para analisis.
16. Auditoria Target viejo e integraciones externas.
