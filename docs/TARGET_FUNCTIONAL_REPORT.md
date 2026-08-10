# Target Pathogen Web - funcionalidades actuales y pendientes

Documento base para informe o presentación. La idea es explicar, desde cero, qué permite hacer Target Pathogen Web hoy, de dónde sale la información y qué mejoras quedan pendientes.

## 1. Objetivo general de la plataforma

Target Pathogen Web es una plataforma para analizar genomas de patógenos y priorizar proteínas como posibles blancos terapéuticos.

La plataforma integra información de distintas fuentes:

- Genoma y anotación funcional.
- Estructuras 3D experimentales y predichas.
- Pockets y drogabilidad.
- Ligandos y evidencia química.
- Off-target contra humano y microbioma.
- Esencialidad.
- Conservación entre cepas.
- Contexto metabólico.
- Scores configurables por el usuario.
- Asistencia mediante agente IA.

El objetivo no es que una sola métrica decida el target, sino reunir evidencia complementaria para que el usuario pueda comparar candidatos, entender fortalezas y riesgos, y justificar biológicamente la priorización.

### 1.1 Recorrido básico de uso

Un uso típico de Target se puede entender como un recorrido de menor a mayor detalle:

1. Entrar al listado de genomas disponibles.
2. Cargar un genoma nuevo o abrir un genoma ya importado.
3. Revisar el overview del genoma para entender qué evidencia existe.
4. Abrir la lista de proteínas y aplicar búsquedas, filtros o scores.
5. Entrar al detalle de una proteína candidata.
6. Revisar estructura, pockets, ligandos, off-target, esencialidad, conservación, anotaciones y metabolismo.
7. Exportar resultados o guardar criterios de priorización.
8. Usar el agente IA como ayuda para interpretar evidencia o manejar filtros.

Además del recorrido principal, la app tiene vistas auxiliares para BLAST, exploración de anotaciones, carga de evidencia custom, detalle de ligandos y mapas metabólicos.

### 1.2 Páginas informativas

Además de las vistas de análisis, Target tiene páginas institucionales y de referencia.

**Incluye:**

- Home de la plataforma.
- Página de data sources.
- Página de equipo.

**Uso:**

- Explicar de forma general qué es la plataforma.
- Mostrar fuentes de datos usadas.
- Dar contexto institucional al proyecto.

## 2. Carga de genomas y datos iniciales

### 2.1 Listado de genomas

Target tiene una página inicial de genomas donde se puede ver qué datasets están cargados.

**Permite:**

- Buscar genomas disponibles.
- Identificar genomas públicos, curados o cargados por usuario.
- Ver información resumida del dataset.
- Abrir el overview de un genoma.
- Acceder a la carga de nuevos datos.
- Exportar la vista cuando se necesita compartir un estado del análisis.

**Fuentes de información:**

- Base interna de Target.
- Metadatos importados desde los archivos de genoma.
- Metadatos agregados durante pipelines o importaciones curadas.

### 2.2 Cargar un genoma desde la interfaz

Target permite incorporar un genoma bacteriano al sistema.

**Se puede cargar de dos formas principales:**

- Mediante pipeline automático.
- Mediante importación manual o curada de archivos ya generados.

**Desde la interfaz se puede:**

- Subir un archivo GenBank comprimido.
- Definir el identificador visible del genoma.
- Indicar el contexto Gram cuando corresponde.
- Lanzar una carga de prueba.
- Ver historial de cargas:
  - en cola,
  - corriendo,
  - finalizadas,
  - fallidas.
- Abrir directamente el ranking de proteínas cuando la carga termina.
- Revisar mensajes de error del pipeline si algo falla.
- Limpiar historial de cargas.

**Qué información entra en esta etapa:**

- Secuencia genómica.
- Proteínas codificantes.
- RNAs.
- Anotación funcional básica.
- Features del genoma.
- Identificadores de genes/proteínas.
- Descripciones funcionales.

**Fuentes posibles, según el flujo usado:**

- GenBank comprimido desde la interfaz.
- FASTA o archivos de anotación cuando vienen dentro de paquetes curados o pipelines.
- Archivos curados entregados por el equipo biológico o bioinformático.
- Resultados de pipelines externos.

**Qué queda disponible en la app:**

- Una página de overview del genoma.
- Una lista de proteínas.
- Páginas individuales de cada proteína.
- Descarga de archivos originales cuando están disponibles.

### 2.3 Carga curada asistida

Para datasets revisados o ya procesados en cluster, Target tiene un flujo de importación curada.

**Permite:**

- Validar paths del servidor antes de escribir en la base.
- Validar columnas de TSV.
- Detectar genes/proteínas esperadas.
- Detectar estructura de archivos y carpetas.
- Detectar salidas de LigQ_2.
- Correr la importación curada.
- Guardar jobs recientes.
- Reintentar importaciones controladas.
- Mostrar el comando equivalente que se ejecutaría en cluster.

**Por qué importa:**

- Reduce errores manuales al cargar paquetes grandes.
- Permite trabajar con resultados que ya pasaron control biológico o bioinformático.
- Ayuda a reproducir qué se cargó y con qué archivos.

### 2.4 Carga de archivos al servidor

Target también permite subir archivos auxiliares al servidor para usarlos luego en comandos o importaciones.

**Ejemplos:**

- TSV de resultados.
- CSV.
- Archivos comprimidos con estructuras.
- Archivos JSON.
- Paquetes con salidas de pipeline.

**Resultado:**

La interfaz devuelve el path guardado para usarlo después en comandos o flujos curados.

### 2.5 Cargar evidencia externa ya calculada

Además del genoma, Target puede incorporar resultados generados fuera de la app.

**Ejemplos de evidencia externa:**

- Scores de drogabilidad.
- Resultados de FPocket.
- Resultados de P2Rank.
- Estructuras PDB, AlphaFold DB o ColabFold.
- Resultados de off-target.
- Resultados de esencialidad.
- Resultados de conservación.
- Resultados de LigQ_2.
- Resultados metabólicos.

**Por qué es importante:**

- Permite usar resultados ya revisados por biólogos/bioinformáticos.
- Evita recomputar análisis pesados.
- Permite reproducir paquetes curados.
- Permite cargar datos de cluster o de pipelines externos.

### 2.6 Pipeline automático

Cuando se usa pipeline automático, Target puede organizar o consumir análisis derivados del genoma.

**Tipos de análisis que forman parte del flujo:**

- Predicción o carga de estructuras.
- Búsqueda de modelos en AlphaFold DB.
- Generación de modelos ColabFold.
- Detección de pockets con FPocket.
- Predicción de pockets con P2Rank.
- Búsqueda de off-target contra humano.
- Búsqueda de off-target contra microbioma.
- Comparación contra DEG para esencialidad.
- Anotaciones funcionales.
- Búsqueda de ligandos por LigQ_2.

**Fuentes/herramientas involucradas:**

- AlphaFold DB.
- ColabFold.
- FPocket.
- P2Rank.
- BLAST / DIAMOND.
- DEG.
- InterProScan.
- LigQ_2.

**Importante:** hay dos orquestadores de pipeline según configuración (`TPW_USE_DIRECT_PIPELINE`),
y no todas las herramientas de la lista corren siempre:

- Orquestador legado (default si la variable no está seteada): usa **ESMFold** para predicción de
  estructura, no ColabFold, y **no tiene etapa de LigQ_2**.
- Orquestador nuevo (usado en el deploy de cluster): usa ColabFold y sí tiene una etapa de LigQ_2,
  pero **viene apagada por default** (`TPW_LIGQ_USE_REMOTE=0`) — hay que activarla explícitamente.

## 3. Vista general del genoma

La página de genoma funciona como tablero principal del análisis.

### 3.1 Resumen del genoma

**Muestra:**

- Nombre del genoma.
- Organismo.
- Cepa.
- Longitud de secuencia.
- Estado del genoma.
- Cantidad de proteínas.
- Cantidad de features.
- Archivos fuente disponibles.

**Fuentes de información:**

- Archivos de genoma/anotación importados.
- Metadatos del paquete cargado.
- Base interna de Target.

### 3.2 Navegación genómica

Desde el overview se puede seguir hacia varias vistas del mismo genoma.

**Accesos principales:**

- Ranking/listado de proteínas.
- Metabolismo.
- Carga de datos adicionales.
- Score custom.
- Árbol EC / explorador de anotaciones.
- BLAST contra el genoma seleccionado.
- Descargas de archivos fuente.
- Genome browser cuando hay tracks disponibles.

**Genome browser / JBrowse:**

Target puede enlazar el genoma con JBrowse para inspeccionar features sobre la secuencia genómica.

**Uso biológico:**

- Ver genes y RNAs en contexto genómico.
- Revisar regiones vecinas.
- Contrastar coordenadas de anotaciones.
- Complementar el análisis proteico con contexto de genoma.

### 3.3 Evidencia disponible

La página muestra cuánta evidencia existe para ese genoma.

**Incluye:**

- Proteínas con estructura 3D.
- Proteínas con anotación funcional.
- Proteínas con pocket score.
- Proteínas con ligandos directos.
- Proteínas mapeadas al modelo metabólico.
- Reacciones metabólicas.
- Rutas metabólicas.
- Chokepoints.
- Genes con chokepoint y pocket.

**Fuentes de información:**

- PDB.
- AlphaFold DB.
- ColabFold.
- FPocket.
- P2Rank.
- InterProScan / GO / EC.
- LigQ_2.
- Pathway Tools / MetaFlux.
- KEGG.

### 3.4 Ranking compuesto de candidatos

El overview incluye un ranking de candidatos que combina varias dimensiones de evidencia.

**Muestra:**

- Proteínas mejor posicionadas.
- Score compuesto de evidencia.
- Chips explicativos por proteína.
- Motivos por los que cada proteína aparece arriba.

**Factores considerados:**

- Pocket FPocket.
- Soporte P2Rank.
- Ligandos directos.
- Ligandos transferidos por homólogos.
- ZINC propuesto.
- Baja similitud con humano.
- Riesgo contra microbioma.
- Esencialidad DEG.
- Conservación.
- Disponibilidad estructural.
- Contexto metabólico.

**Importante:**

El ranking no pretende reemplazar la decisión biológica. Es una primera priorización explicable para ordenar candidatos y abrir las proteínas más prometedoras.

### 3.5 Estadísticas agregadas de ligandos

El overview del genoma muestra totales agregados de evidencia química, no un ranking de proteínas
por soporte químico (no existe un ranking por proteína en esta vista; para eso hay que ordenar la
lista de proteínas por columnas de ligandos).

**Distingue:**

- Ligandos PDB directos.
- Bioactividad ChEMBL directa.
- Ligandos por homólogos.
- Propuestos ZINC.

**Fuentes de información:**

- PDB.
- ChEMBL.
- ZINC.
- LigQ_2.
- Mapeo UniProt.

### 3.6 Descargas y administracion del dataset

El overview también funciona como punto de administración del genoma.

**Permite:**

- Descargar archivos fuente cuando están disponibles.
- Ver detalles importados desde el registro original.
- Exportar la vista.
- Eliminar workspaces o datasets cargados cuando corresponde por permisos.

**Importante:**

Estas acciones no son análisis biológico en sí mismas, pero son clave para reproducibilidad, limpieza de datasets y trabajo en cluster.

## 4. Lista de proteínas

La lista de proteínas es la vista para explorar, buscar, filtrar y ordenar candidatos.

### 4.1 Búsqueda

**Permite buscar por:**

- Accession.
- Gen.
- Descripción.

**Uso esperado:**

- Encontrar rapidamente una proteína conocida.
- Usar sugerencias/autocompletado para evitar errores de escritura.
- Explorar familias o términos funcionales.

**Nota:** la búsqueda siempre muestra el listado filtrado (aunque el resultado sea uno solo); no
hay apertura automática del detalle de proteína. Tampoco se busca por locus tag hoy.

### 4.2 Filtros

La lista permite aplicar filtros sobre variables cargadas.

**Ejemplos de filtros:**

- Tiene estructura.
- Tiene pocket.
- Drogabilidad alta.
- Tiene o no off-target humano.
- Tiene hit en DEG.
- Es core/conservada.
- Tiene anotación EC/GO (se elige un valor EC/GO específico, no es un booleano genérico "tiene alguna anotación").
- Pertenece a metabolismo (se elige una ruta específica, no un booleano genérico).
- Es chokepoint.

**Pendiente:** no existe hoy un filtro genérico "tiene ligandos/binders" — sería una mejora útil.

**Fuentes de información:**

- Scores cargados.
- Datos de estructura.
- FPocket / P2Rank.
- LigQ_2.
- Off-target.
- DEG.
- Roary / CoreCruncher.
- Modelo metabólico.

### 4.3 Presets de filtros

El usuario puede guardar combinaciones de filtros.

**Sirve para:**

- Reutilizar criterios de búsqueda.
- Comparar estrategias de priorización.

**Nota:** los presets son privados por usuario/cuenta, hoy no hay forma de compartirlos entre
miembros del equipo.

### 4.4 Columnas y exportación

**Permite:**

- Ordenar proteínas.
- Mostrar más columnas.
- Elegir columnas visibles.
- Reordenar columnas visibles.
- Restaurar columnas por defecto.
- Exportar resultados a CSV.
- Usar los filtros aplicados como punto de partida para análisis posterior.

### 4.5 Explorador de anotaciones

Target incluye vistas para explorar anotaciones funcionales del genoma.

**Permite:**

- Abrir un árbol de anotaciones EC.
- Explorar términos GO u otros tipos de anotación cuando están disponibles.
- Ver cuántas proteínas caen en cada anotación.
- Abrir proteínas asociadas a una anotación.
- Exportar la vista.

**Fuentes:**

- Anotaciones importadas desde GenBank/GFF.
- InterProScan.
- GO.
- EC.
- Base interna de Target.

**Uso biológico:**

Sirve para pasar de una función o categoría biológica hacia las proteínas concretas del genoma, en vez de empezar siempre desde una lista larga de proteínas.

### 4.6 BLAST contra un genoma

Target tiene una vista para correr BLAST contra un genoma seleccionado.

**Permite:**

- Pegar una secuencia query.
- Elegir el genoma de búsqueda.
- Ejecutar BLAST.
- Ver resultados en una página dedicada.

**Uso biológico:**

- Buscar si una secuencia conocida aparece en el genoma.
- Ubicar homólogos locales.
- Conectar una pregunta experimental con las proteínas cargadas en Target.

**Nota:** hoy es BLAST de nucleótidos (`blastn`) únicamente, no hay opción de BLAST de proteínas.
También hay límites de largo de query y timeout configurados.

### 4.7 Carga de evidencia custom

Target permite importar evidencia por proteína desde archivos tabulados.

**Permite:**

- Subir un TSV con accession de proteína y valores asociados.
- Incorporar datos experimentales, computacionales o de literatura.
- Usar esos valores después en filtros y scores.

**Ejemplos de uso:**

- Score manual de interes biológico.
- Resultado experimental propio.
- Clasificacion curada por el equipo.
- Variable cuantitativa externa.

**Ya implementado (no confundir con pendiente):**

- La detección de tipo de dato (categórico/cuantitativo) ya es automática hoy — se infiere
  intentando castear los valores a numérico.

**Pendiente de mejorar:**

- Permitir que el usuario **fuerce/corrija manualmente** el tipo inferido (útil si un valor
  numérico-looking en realidad es categórico, ej. un código).
- Mostrar provenance completa de cada columna custom.
- Integrar mejor estas columnas en visualizaciones.

### 4.8 Detalle de ligandos y moléculas

Los ligandos no quedan solo como conteos en la proteína. Target tiene una página de detalle para registros químicos.

**Permite ver:**

- Identificador del ligando.
- Fuente del registro:
  - PDB,
  - ChEMBL,
  - ZINC.
- PDB de origen cuando corresponde.
- Representacion 2D desde SMILES.
- Formula y propiedades moleculares.
- Descriptores ADME simples.
- Alertas como PAINS cuando están disponibles.
- Otros registros relacionados (mismo locus tag, otros PDB/ChEMBL/ZINC).
- Estimación de potencia (a partir de pChEMBL) cuando la fuente es ChEMBL.
- Notas de LigQ_2 parseadas en campos legibles (método, sitios de unión, UniProt, PDB, similitud/e-value/identidad/cobertura).
- Links externos: RCSB, ChEMBL, ZINC15/ZINC20, UniProt, PubChem, SwissADME, SwissTargetPrediction, Google Scholar.

**Fuentes:**

- LigQ_2.
- PDB.
- ChEMBL.
- ZINC.
- RDKit para propiedades derivadas de SMILES.

## 5. Scores y fórmulas de priorización

Target permite trabajar con scores de priorización.

### 5.1 Scores importados

**Ejemplos:**

- Druggability.
- Human off-target.
- Microbiome off-target.
- Essentiality.
- Localization.
- Conservation.
- Metabolic centrality.
- Chokepoint.

**Fuentes:**

- Pipeline automático.
- Archivos curados.
- Herramientas externas.
- Tablas importadas.

### 5.2 Constructor de scores

La app permite crear fórmulas de score combinando variables.

**Sirve para:**

- Ajustar la priorización según criterios del proyecto.
- Dar más peso a unas evidencias que a otras.
- Comparar rankings alternativos.
- Validar fórmulas antes de guardarlas.
- Eliminar fórmulas que ya no se usan.

**Ya implementado (no confundir con pendiente):**

- Preview en vivo de sintaxis: la fórmula se revalida ~500ms después de cada tecla y muestra un
  preview formateado en vivo, con el error concreto si algo está mal escrito.

**Pendiente de mejora:**

- Preview en vivo del **ranking numérico** (ver el top-N de proteínas moverse mientras se ajustan pesos), no solo la sintaxis.
- Mejor seleccion de variables (hoy hay búsqueda/categorías, pero no sugerencias guiadas).
- Mensajes de validación menos técnicos (hoy son bastante crudos/tipo excepción de Python).
- Explicaciones más accionables (a diferencia del ranking del overview, que sí trae chips explicativos).

## 6. Pagina de detalle de proteína

La página de proteína concentra toda la evidencia sobre un target puntual.

### 6.1 Header biológico

**Muestra:**

- Accession principal.
- Descripción funcional.
- Genoma.
- Gen/locus.
- Evidencia 3D.
- UniProt cuando existe.
- Longitud de la proteína.
- Drogabilidad.
- Reacciones metabólicas.
- Chokepoint.
- Ligandos.
- EC / GO.

**Objetivo:**

Dar una lectura rápida del candidato antes de entrar en secciones detalladas.

### 6.2 Target summary

El resumen ejecutivo interpreta la evidencia del target.

**Muestra:**

- Veredicto corto.
- Fortalezas principales.
- Riesgos o puntos a revisar.
- Evidencia faltante.
- Links a las secciones que justifican cada afirmación.

**Ejemplos de fortalezas:**

- Metabolic bottleneck.
- Pocket consensus FPocket + P2Rank.
- Estructura experimental disponible.
- Ligando directo.
- Baja similitud humana.
- Core gene.

**Ejemplos de riesgos:**

- Similitud con microbioma.
- Similitud humana moderada.
- Pocket difuso o de baja confianza.
- Falta de evidencia experimental.

### 6.3 Glosario

La página incluye un glosario para hacer más accesibles términos técnicos.

**Define conceptos como:**

- PDB.
- AlphaFold DB.
- ColabFold.
- pLDDT.
- FPocket / P2Rank.
- Druggability.
- PDB ligand.
- ChEMBL.
- ZINC.
- LigQ / LigQ_2.
- Off-target.
- DEG.
- Roary / CoreCruncher.
- EC / GO.
- KEGG pathway.
- Chokepoint.

**Objetivo:**

Reducir jerga y facilitar el uso por biólogos que no necesariamente conocen todas las herramientas computacionales.

## 7. Target profile

La sección Target profile resume evidencia computada para priorización.

### 7.1 Off-target humano

**Muestra:**

- Si hay hit contra humano.
- Identidad.
- E-value.
- Riesgo relativo.

**Fuente:**

- BLAST / DIAMOND contra proteoma humano.

**Interpretación:**

Menor similitud con humano suele ser mejor para reducir riesgo de off-target.

### 7.2 Microbioma

**Muestra:**

- Cantidad de hits contra microbioma.
- Genomas analizados.
- Valor normalizado cuando existe.

**Fuente:**

- BLAST / DIAMOND contra base de microbioma intestinal.

**Interpretación:**

Muchas similitudes en microbioma pueden indicar posible impacto sobre bacterias no objetivo.

### 7.3 Esencialidad

**Muestra:**

- Si existe similitud con genes esenciales.
- Identidad contra DEG.
- E-value.

**Fuente:**

- DEG, Database of Essential Genes.

**Interpretación:**

Una coincidencia con DEG sugiere que la proteína podría estar relacionada con funciones esenciales, aunque es evidencia transferida y no prueba experimental directa en el patógeno.

### 7.4 Calidad estructural

**Muestra:**

- pLDDT ColabFold cuando aplica.
- Evidencia 3D disponible.
- Estructura seleccionada para scores de pocket.

**Fuentes:**

- ColabFold.
- AlphaFold DB.
- PDB.

### 7.5 Localización subcelular

**Muestra:**

- Localización subcelular predicha.

**Fuente:**

- PSORTb.

**Interpretación:**

Proteínas extracelulares o de membrana externa suelen ser preferidas como blanco terapéutico
(más accesibles a una droga sin necesidad de atravesar la membrana interna).

## 8. Visualizador 3D de estructura

Target incluye visualización estructural interactiva.

### 8.1 Viewer embebido

**Permite:**

- Ver la estructura 3D dentro de la página de proteína.
- Rotar la proteína.
- Hacer zoom.
- Cambiar estructura cuando hay varias.
- Abrir full viewer.

**Fuentes:**

- PDB experimental.
- AlphaFold DB.
- ColabFold.

### 8.2 Full viewer

Vista dedicada para inspección estructural más cómoda.

**Permite:**

- Usar más espacio de pantalla.
- Explorar pockets.
- Activar/desactivar capas.
- Enfocar pockets o residuos.
- Revisar estructuras cargadas.

### 8.3 Exportación estructural

Target no solo muestra estructuras en pantalla. También expone recursos para inspección externa.

**Permite:**

- Abrir o descargar archivos de estructura cuando están disponibles.
- Exportar una vista estructural.
- Generar scripts de visualización para reproducir o inspeccionar la escena fuera de la página.

**Uso esperado:**

- Compartir una estructura con otra persona del equipo.
- Revisar un target en herramientas externas.
- Guardar evidencia visual para informes.

### 8.4 Colores de estructura

La UI explica que significan los colores.

**Criterio actual:**

- Color uniforme: modelo principal como objeto molecular único.
- Color por cadena: estructura PDB experimental con subunidades/copias.
- Colores de pockets/alpha spheres: overlays de evidencia, no cadenas proteicas.

## 9. Pockets y drogabilidad

La app permite analizar cavidades de unión potenciales.

### 9.1 FPocket

**Muestra:**

- Score de drogabilidad.
- Pocket principal.
- Residuos asociados.
- Alpha spheres.
- Superficie/residuos cercanos.

**Fuente:**

- FPocket.
- Outputs curados tipo Gates cuando existen.

**Interpretación:**

El score estima si una cavidad podría alojar una molécula pequeña. No prueba unión experimental.

### 9.2 P2Rank

**Muestra:**

- Probabilidad de sitio de unión.
- Pocket principal.
- Residuos asociados.

**Fuente:**

- P2Rank.

**Interpretación:**

Es una predicción basada en machine learning. Sirve como soporte adicional, especialmente cuando coincide con FPocket.

### 9.3 Control de capas

**Permite activar:**

- Pocket específico / alpha spheres.
- Nearby residues.
- Surface.
- Labels.

**Acciones disponibles:**

- Seleccionar pocket.
- Enfocar pocket.
- Ver residuos.
- Hacer zoom al pocket.
- Mantener varias capas activas para comparar.

## 10. Evidencia de ligandos

Target integra evidencia química asociada a cada proteína.

### 10.1 Tipos de evidencia

**Directa:**

- PDB co-crystal del mismo target.
- ChEMBL bioactivity del mismo target.

**Transferida o inferida:**

- PDB vía homólogos.
- ChEMBL vía homólogos.
- ZINC proposed compounds por similitud química.

### 10.2 Vista en la app

**Permite ver:**

- Moleculas destacadas.
- Imagen 2D.
- Fuente de evidencia.
- PDB asociado.
- ChEMBL cuando existe.
- ZINC cuando existe.
- Filtros por tipo de evidencia.
- Export CSV.

**Fuentes:**

- LigQ_2.
- PDB.
- ChEMBL.
- ZINC.
- UniProt mapping.

### 10.3 Interpretación

**Mas fuerte:**

- Ligando PDB directo.
- ChEMBL directo con bioactividad medida.

**Mas débil:**

- Ligando transferido desde homólogo.
- ZINC propuesto por similitud.

## 11. Información metabólica

Target incorpora metabolismo para evaluar relevancia funcional del target.

### 11.1 Metabolic context en proteína

**Muestra:**

- Reacciones catalizadas.
- Pathways.
- Chokepoint.
- Centrality percentile.
- Frase interpretativa automática.

**Nota:** la señal de isoenzimas/ausencia de backup se calcula igual (por reacción), pero hoy no
se muestra como campo dentro de esta card — aparece como fortaleza en el Target Summary
("No isoenzyme backup detected", ver 6.2) cuando aplica.

**Fuentes:**

- SBML de MetaFlux / Pathway Tools.
- TSV de resultados metabólicos.
- `network.sif`.
- KEGG para rutas.

### 11.2 Ranking de rutas metabólicas

**Permite:**

- Ver rutas del genoma.
- Ranking por densidad de chokepoints o señal de targets.
- Entrar a mapa de ruta.
- Ver proteínas asociadas.

### 11.3 Mapa de ruta

**Permite ver:**

- Reacciones.
- Sustratos.
- Productos.
- Genes asociados.
- Chokepoints.
- Metabolitos.

### 11.4 Grafo metabólico

**Permite:**

- Ver vecindario metabólico de una proteína.
- Explorar rutas y conexiones.
- Ver contexto genome-wide.
- Abrir una vista completa de red metabólica asociada a una proteína.
- Expandir nodos y revisar conexiones entre reacciones y metabolitos.

**Ya implementado (no confundir con pendiente):** el mapa de ruta (11.3) y la red genoma-completo
ya usan un layout dirigido tipo dagre/Sugiyama (menos cruces de líneas, lectura más parecida a un
esquema curado tipo MetaCyc), implementado recientemente.

**Pendiente:**

- El grafo ego-network de una sola proteína (esta sección) todavía usa un layout force-directed
  genérico, no el layout dirigido ya aplicado en 11.3 y en la red genoma-completo — sería
  consistente extenderlo también acá.

## 12. Anotaciones funcionales y secuencia

### 12.1 Secuencia

**Permite:**

- Ver secuencia aminoacídica.
- Copiar secuencia.
- Usarla para análisis externos.

### 12.2 GO / EC

**Permite ver:**

- Terminos GO.
- EC numbers.
- Descripciones funcionales.

**Fuentes:**

- InterProScan.
- GO.
- EC.
- Anotación del genoma.

### 12.3 Sequence features

**Permite ver:**

- Dominios.
- Regiones anotadas.
- Features de bases como InterPro, Pfam, Gene3D, SUPERFAMILY, PANTHER, etc.

**Pendiente:**

- Mejorar visualización para que sea más biológica e interactiva.

## 13. Conservación

Target integra señales de conservación entre cepas.

**Permite ver:**

- Si una proteína es core.
- Si es accesoria.
- Si está conservada según herramientas de pangenoma.

**Fuentes:**

- Roary.
- CoreCruncher.
- Tablas curadas.

**Uso en priorización:**

Un target conservado puede ser más interesante si se busca cobertura sobre múltiples cepas.

## 14. Exportación y reproducibilidad

La app permite exportar resultados y conservar trazabilidad parcial.

**Permite:**

- Exportar rankings.
- Exportar tablas.
- Exportar vistas completas para compartir el estado de una página.
- Descargar archivos fuente cuando están disponibles.
- Descargar o abrir estructuras.
- Exportar CSV standalone desde: lista de proteínas, anotaciones.
- Exportar XLSX combinado por proteína ("Export view"), que incluye ligandos y features como
  secciones dentro del mismo archivo (no son CSV independientes).
- Metabolismo todavía no tiene ninguna opción de export.
- Consultar evidencia cargada por genoma.
- Ver comandos equivalentes en algunos flujos curados.
- Revisar historial de cargas e importaciones.

**Tambien existe soporte operativo para:**

- Health checks de la app.
- Validaciones de importación.
- Comandos de carga y backfill en cluster.
- Dumps auxiliares, por ejemplo FASTA de proteínas por genoma.

**Pendiente:**

- Capa de provenance **consistente entre todos los tipos de dato** — hoy es parcial e inconsistente,
  no inexistente: la carga curada (`CuratedImportJob`) ya guarda comando + archivo + fecha +
  responsable; la importación metabólica (`MetabolicImportRun`) ya guarda archivo + fecha +
  responsable. Lo que falta en todos los casos es un campo de **versión de herramienta**, y que
  el resto de los flujos (carga de genoma estándar, pipeline automático) capturen el mismo nivel
  de detalle.

## 15. Agente IA

Target incluye un asistente integrado.

### 15.1 Qué puede hacer

**Permite:**

- Preguntar por una proteína.
- Explicar por que un target parece prometedor o riesgoso.
- Auditar evidencia.
- Comparar targets.
- Buscar proteínas.
- Listar filtros disponibles.
- Aplicar filtros.
- Limpiar filtros.
- Explicar términos técnicos.
- Usar acciones sugeridas desde la interfaz.
- Ayudar a interpretar la página actual sin que el usuario copie todo manualmente.

### 15.2 Como usa el contexto

**Usa:**

- Pagina actual.
- Genoma actual.
- Proteína actual si corresponde.
- Filtros activos.
- Datos reales de la base.

**No debería:**

- Inventar evidencia que no está cargada.
- Confundir dato faltante con evidencia negativa.
- Aplicar filtros si el usuario solo pidió información.

### 15.3 Fuente técnica

**Proveedor actual:**

- Claude (Anthropic API) es el proveedor default real.
- OpenAI API existe como camino alternativo/prototipo, pero solo se activa si se configuran
  explícitamente dos variables de entorno a la vez; si no, el sistema cae en Anthropic.

**Backend:**

- Tools internas de Target.
- Scope re-derivado server-side desde la URL (verificado: nunca confía en el scope que manda el
  cliente, siempre lo re-resuelve del lado del servidor a partir del path).
- Logging de tokens, latencia, modelo, cantidad de turnos/tool-calls y errores.
- Manejo de errores de API y límites de tokens.

**Pendiente:** no hay cálculo ni logging de costo estimado en dólares todavía (solo se loguean
tokens y latencia, no un valor de costo).

## 16. Pendientes principales

### 16.1 Flujos base de carga y datasets

- Hacer más clara la diferencia entre:
  - subir un genoma nuevo,
  - importar evidencia curada,
  - subir archivos auxiliares al servidor,
  - correr comandos en cluster.
- Mejorar mensajes de error para usuarios no técnicos.
- Mostrar progreso más granular en cargas largas.
- Consolidar historial de cargas, validaciones e importaciones.
- Exponer provenance por dataset de forma más visible.

### 16.2 Visualización metabólica más clara

**Ya implementado** para el mapa de ruta y la red genoma-completo: layout dirigido tipo dagre/
Sugiyama (menos cruces de líneas, más parecido a un esquema curado tipo MetaCyc).

**Sigue pendiente:**

- Extender el mismo layout dirigido al grafo ego-network de una sola proteína (hoy sigue con
  layout force-directed genérico).
- Mostrar dirección de ruta de forma más explícita.
- Mejorar principio/fin de lectura.
- Agregar búsqueda por proteína en ranking de rutas.

### 16.3 Visualizador 3D 2.0

- Mejor toolbar.
- Coloreo por cadena más explícito.
- Coloreo por estructura secundaria.
- Manejo de multímeros.
- Mejor selector de estructura por fuente/calidad/cobertura.
- Definir si el viewer embebido es preview y el full viewer es la vista principal.

### 16.4 Comparación FPocket vs P2Rank

**Ya implementado:** distancia entre centros de pocket y marca de solapamiento espacial (dentro de
8 Å) entre el pocket principal de FPocket y P2Rank — visible hoy como texto en el inspector de
pockets.

**Sigue pendiente:**

- Residuos compartidos.
- Badge/filtro visible y dedicado de consenso (hoy es solo texto inline, no es filtrable ni se
  destaca visualmente).

### 16.5 Drogabilidad por fuente y estructura

- Separar scores por PDB, AlphaFold DB y ColabFold.
- Mostrar estructura usada para cada score.
- Definir score default.
- Dejar decisión auditable.

### 16.6 Sitios funcionales y catalíticos

**Ya implementado (infraestructura, no integración):** el mismo mecanismo de comparación de 16.4
(distancia entre centros) ya soporta comparar contra cualquier otro sitio anotado en el modelo
(`ResidueSet` genérico, más allá de FPocket/P2Rank) y mostrar "sitio anotado más cercano" cuando
existe uno cargado.

**Sigue pendiente (esto es lo que realmente falta):**

- No hay ningún loader que cargue sitios catalíticos/funcionales reales desde una fuente externa
  todavía — la infraestructura de comparación existe, pero no hay datos de UniProt, CSA Atlas,
  Ligysis ni Target viejo cargados en el modelo.
- Mostrar residuos catalíticos en 3D.
- Mostrar sitios de unión/cofactores/PPI.
- Integrar UniProt, CSA Atlas, Ligysis y Target viejo.

### 16.7 Off-target 2.0

- Mejor interpretación de riesgo humano.
- Mejor interpretación de riesgo microbioma.
- Filtros por identidad, cobertura, e-value y organismo.
- Integración con estructura, ligandos y score final.

### 16.8 Priorizacion estructural completa

- Integrar calidad estructural.
- Cobertura.
- Tipo de estructura.
- Pockets.
- Consenso FPocket/P2Rank.
- Ligandos directos y transferidos.
- Sitios funcionales.
- Off-target.
- Drogabilidad.

### 16.9 Sequence & feature viewer 2.0

- Mapa lineal más claro.
- Búsqueda por posición/motivo.
- Links desde residuos a estructura 3D.
- Mejor lectura de dominios.

### 16.10 Cross-references hub

- Agrupar UniProt, KEGG, BioCyc, NCBI, PDB y ChEMBL.
- Separar identificadores por tipo:
  - secuencia,
  - estructura,
  - química,
  - metabolismo,
  - literatura.

### 16.11 Evidence provenance / auditoría

- Fuente exacta de cada dato.
- Fecha de importación.
- Archivo/comando usado.
- Version de herramienta.
- Log por genoma.
- Mejor reproducibilidad en cluster.

### 16.12 Constructor de score mejorado

- Preview en vivo.
- Variables más visibles.
- Validación por tipo de dato.
- Sugerencias según filtros activos.
- Mensajes de error claros.

### 16.13 Columnas custom

- Cargar columnas nuevas por genoma/análisis.
- Definir tipo categórico o cuantitativo.
- Usarlas en filtros, rankings, visualizaciones y scores.
- Guardar provenance.

### 16.14 BLAST y exploradores funcionales 2.0

- Mejorar visualización de resultados BLAST.
- Conectar hits BLAST directamente con proteínas y features.
- Mejorar explorador GO/EC con búsqueda y filtros más biológicos.
- Agregar resumen interpretativo por anotación o grupo funcional.

### 16.15 Ligandos y detalle químico 2.0

- Mejorar zoom de estructuras 2D.
- Mostrar afinidades de unión cuando existan.
- Separar claramente evidencia experimental, transferida y propuesta.
- Integrar mejor detalle de ligando con el viewer 3D.
- Evaluar AlphaFill o superposición estructural para ligandos transferidos.

### 16.16 Auditoría del Target viejo

- Revisar que features del sistema viejo conviene migrar.
- Priorizar:
  - estructura,
  - sitios catalíticos,
  - drogas/lugares de unión,
  - anotaciones funcionales.

## 17. Orden sugerido para roadmap

1. Revisar en cluster las vistas ya implementadas.
2. Flujos base de carga y datasets.
3. Visualización metabólica más clara.
4. Visualizador 3D 2.0.
5. Comparación FPocket vs P2Rank.
6. Drogabilidad por fuente y estructura.
7. Integración AlphaFill / Ligysis / CSA Atlas.
8. Sitios funcionales y catalíticos.
9. Off-target 2.0.
10. Priorizacion estructural completa.
11. Sequence & feature viewer 2.0.
12. BLAST y exploradores funcionales 2.0.
13. Ligandos y detalle químico 2.0.
14. Cross-references hub.
15. Evidence provenance / auditoría.
16. Constructor de score mejorado.
17. Columnas custom.
18. Auditoría del Target viejo.





