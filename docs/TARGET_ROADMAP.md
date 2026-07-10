# TargetPathogen roadmap

Documento vivo para ordenar tareas de producto e implementacion. La idea es mantener aca el backlog tecnico-funcional que antes estaba en Notion, con estado, alcance y prioridades.

## En progreso

### Informacion metabolica

**Objetivo.** Incorporar informacion metabolica al analisis de targets desde el pipeline automatico y fuentes curadas. Debe quedar claro en que ruta participa una proteina, que tan central es, si actua como chokepoint y como esa evidencia afecta la priorizacion.

**Fuentes usadas.**

- Export SBML de MetaFlux/Pathway Tools: reacciones, genes, metabolitos, estequiometria y expresiones GPR.
- Tabla de resultados metabolicos: chokepoints, centralidad y evidencia derivada del pipeline.
- `network.sif`: topologia reaccion-reaccion para vecindarios metabolicos.
- KEGG REST/cache local: nombres y membresia de rutas.

Reactome no se usa como fuente de datos porque esta orientado principalmente a humano. Se usa como referencia de UX: rutas navegables, contexto visual fuerte, agrupacion por pathway y lectura rapida de relevancia biologica.

**Hecho.**

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

**Pendiente.**

- Validar con biologas si la interpretacion de chokepoint `producing`, `consuming` y `both` se entiende igual que en el pipeline.
- Agregar export/import curado para BioCyc SmartTables cuando haya archivo ejemplo.
- Agregar una vista genome-wide tipo overview/fireworks: rutas coloreadas por cantidad/calidad de targets.
- Mejorar leyendas biologicas: explicar que significa centralidad, isoenzima, chokepoint y pathway sin cargar la UI.
- Agregar filtros por ruta en la tabla principal de proteinas.
- Agregar validaciones automaticas de ingesta para detectar SBML/TSV/SIF inconsistentes.

## To Do prioritario

### Target executive summary

Agregar un resumen ejecutivo arriba de la pagina de proteina. Debe responder en pocos segundos si el target parece prometedor, por que, que evidencia falta y cuales son los principales riesgos.

**Alcance propuesto.**

- Frase interpretativa unica combinando score, metabolismo, drogabilidad, ligandos, estructura, off-target y conservacion.
- Bloques `Strengths`, `Risks` y `Missing evidence`.
- Links internos a las secciones que justifican cada punto.
- Badges para evidencia fuerte: chokepoint sin isoenzimas, pocket consistente, ligando conocido, baja similitud humana, buena cobertura estructural.

### Ligandos, ChEMBL, PDB y quimica del target

Mejorar la lectura de evidencia quimica y ligandos. La pagina ya tiene un dashboard inicial de ligandos; falta conectarlo mas fuerte con estructura, ChEMBL y PDB.

**Alcance propuesto.**

- Links externos a ChEMBL para ligandos directos.
- Zoom o modal para imagen 2D de moleculas.
- Mostrar afinidad experimental cuando exista.
- Separar evidencia directa, homologos y propuestas computacionales.
- Permitir enfocar ligandos PDB en el visualizador 3D.
- Evaluar transferencia de ligandos desde homologos con AlphaFill o superposicion estructural.
- Dejar preparado soporte futuro para modelos Boltz.

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
- Separar valores por tipo de estructura: AlphaFold, PDB, ColabFold u otras.
- Mostrar a que estructura corresponde cada valor.
- Definir con el equipo que valor se usa por defecto en la tabla principal.
- Hacer auditable la decision de prioridad: por ejemplo PDB > AlphaFold si existe buena cobertura.

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

## Orden sugerido

1. Target executive summary.
2. Ligandos, ChEMBL, PDB y quimica del target.
3. Visualizacion de Proteina 2.0.
4. Visualizacion y control de pockets.
5. Comparacion FPocket vs P2Rank.
6. Drogabilidad por fuente y estructura.
7. Sitios funcionales y anotaciones estructurales.
8. Priorizacion estructural completa.
9. Off-target 2.0.
10. Sequence & feature viewer 2.0.
11. Cross-references hub.
12. Pathway-level target prioritization.
13. Evidence provenance / audit layer.
14. Constructor de score mejorado.
15. Columnas custom para analisis.
16. Agente IA para exploracion de targets.
17. Auditoria Target viejo e integraciones externas.
