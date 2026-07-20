# TargetPathogen roadmap

Documento vivo para ordenar tareas de producto e implementacion. La idea es mantener aca el backlog tecnico-funcional que antes estaba en Notion, con estado, alcance y prioridades.

## Estado actual

### Hecho / en uso

Estas tareas ya tienen implementacion completa en la rama actual.

### Corte actual - 2026-07-20

- Metabolismo: implementado end-to-end para Klebsiella, con ingesta SBML/TSV/SIF, contexto por
  proteina, ranking por ruta, vistas navegables y un grafo unico genome-wide con zoom in/out
  estilo Krona por pathway.
- Protein detail / genome overview: resumen ejecutivo, evidencia estructural/quimica/metabolica y
  lenguaje explicativo para biologos.
- Pockets / estructura: Inspect por pocket con panel de detalle y propiedades derivadas, paridad
  completa entre las dos paginas del visualizador, visor embebido simplificado a vista previa.
- Agente IA: funciona con OpenAI en cluster, drawer global, historial por sesion, tools para
  filtros, explicacion de targets, auditoria de evidencia y comparacion de candidatos, sin
  pendientes de codigo.
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

- Ingesta completa por genoma (reacciones, genes, chokepoints, isoenzimas, metabolitos, estequiometria) y mapeo a rutas KEGG.
- `Metabolic context` en la pagina de proteina, integrado con `ScoreFormula` y con oracion interpretativa automatica.
- Ranking de rutas a nivel genoma, grafo de vecindario por proteina y pagina de mapa por ruta (sustrato→reaccion→producto).
- Grafo unico genome-wide estilo Krona: un nodo por pathway, click hace zoom a su subgrafo de reacciones (pedido explicito de las biologas, "quieren todo junto, no ruta por ruta").
- Tooltips explicativos (centralidad, isoenzima, chokepoint, pathway), filtro por ruta en la tabla de proteinas, validaciones automaticas de ingesta (SBML/TSV/SIF inconsistentes).

**Pendiente para cerrar.**

- Agregar export/import curado para BioCyc SmartTables cuando haya archivo ejemplo.
- Recalibrar el umbral de "pathway importante" contra la distribucion real de mas de un genoma.

### Target executive summary

Agregar un resumen ejecutivo arriba de la pagina de proteina. Debe responder en pocos segundos si el target parece prometedor, por que, que evidencia falta y cuales son los principales riesgos.

**Implementado.**

- Frase interpretativa unica combinando score, metabolismo, drogabilidad, ligandos, estructura, off-target y conservacion.
- Bloques `Strengths`, `Risks` y `Missing evidence`, con links internos a las secciones que justifican cada punto.
- Conteo interno de señales positivas para orientar la lectura, con prioridad por especificidad (evidencia directa antes que genericas) para que la cantidad mostrada sea consistente con el conteo total.
- Badges especificos cuando hay datos completos: pocket consistente FPocket/P2Rank, estructura experimental disponible, baja similitud humana, ligando conocido fuerte (co-cristal PDB o ChEMBL directo potente).

### Ligandos, ChEMBL, PDB y quimica del target

Mejorar la lectura de evidencia quimica y ligandos. La pagina ya tiene un dashboard inicial de ligandos; falta conectarlo mas fuerte con estructura, ChEMBL y PDB.

**Implementado.**

- Dashboard de señal quimica en la pagina de proteina, separando evidencia directa, homologos, PDB, ChEMBL y ZINC.
- Links externos a ChEMBL, RCSB PDB y ZINC, zoom inline de la estructura 2D y acceso directo al detalle de cada ligando.
- Afinidad experimental estimada (nM/µM/mM) junto al pchembl crudo.
- Enfocar ligandos PDB en el visualizador 3D desde el boton "Open crystal".
- Pulido visual: sin duplicados en el resumen de mejor evidencia, orden consistente en las mini-cards.

**Pendiente para cerrar.**

- Transferencia de ligandos desde homologos (ver card `Integracion AlphaFill / Ligysis / CSA Atlas`).

### Genome overview 2.0 / ranking compuesto explicable

El overview del genoma debe funcionar como tablero macro, no como reflejo de la ultima feature implementada. La priorizacion inicial no debe depender solo de drogabilidad ni de cantidad cruda de ligandos.

**Implementado.**

- Ranking principal `Top evidence-convergent candidates`: score heuristico transparente (0-15, tier Strong/Moderate/Limited) que combina pocket, ligandos directos/transferidos, off-target, esencialidad, conservacion, estructura y metabolismo. Chips por proteina explican por que aparece arriba.
- Ranking secundario `Worth a fresh look`: candidatos druggable/selectivos sin evidencia quimica explorada todavia (reemplaza un ranking anterior por conteo de ligandos que sesgaba hacia proteinas "muy estudiadas").
- Export CSV del ranking compuesto con desglose completo de señales y cautions por proteina.

## To Do prioritario

### Visualizacion de Proteina 2.0

Rediseñar la experiencia completa del visualizador 3D. Debe servir para estructura, cadenas, pockets, ligandos, sitios funcionales y superposiciones sin volverse confuso.

**Alcance propuesto.**

- Spin apagado por defecto.
- Estado visual claro para botones activos.
- Coloreo por estructura secundaria.
- Coloreo por cadena.
- Manejo claro de estructuras multimericas.
- Selector de estructura priorizado por fuente, cobertura y calidad.
- Evaluar si corresponde crear una vista estructural dedicada cuando haya demasiada informacion.

**Implementado inicial.**

- Auto-rotacion apagada por defecto en el viewer 3D, con estados `aria-pressed` sincronizados y tooltips explicitos.
- Nota en sidebar aclarando que FPocket/P2Rank son predicciones computacionales.

### Visualizacion y control de pockets

Mejorar como se muestran y controlan los pockets en el visualizador.

**Objetivo biologico.**

El usuario debe poder elegir un pocket puntual y mirarlo en detalle, sin perder la opcion de ver el sector/entorno de residuos que lo rodea. La experiencia tiene que responder: "que pocket estoy viendo, de que metodo viene, que residuos lo forman, que score tiene y por que podria importar como sitio de union".

**Implementado.**

- Capas claras (Alpha spheres/Pocket, Nearby, Surface, Labels) con tooltips, y accion Inspect que selecciona un pocket, centra camara, aisla su capa y muestra un panel de detalle (metodo, score, capa visible, residuos, propiedades geometricas).
- Propiedades derivadas por pocket: centro geometrico, consenso FPocket/P2Rank (cuando ambos predicen el mismo sitio) y sitio funcional anotado mas cercano.
- Badge "Unusual size" cuando un pocket es outlier de volumen respecto a la misma estructura (descuenta el sub-score de drogabilidad cuando aplica).
- Toggle "Show only selected pocket" y atenuacion geometrica de la proteina al inspeccionar un pocket.
- Paridad completa entre `protein.html` y `structure.html`: mismos componentes, mismo flujo de Inspect, mismo modulo de registro de shapes NGL.
- Visualizador embebido de `protein.html` simplificado a vista previa liviana (sin toolbar de camara ni fallback legado a 3Dmol.js), con foco en abrir el visor fullscreen para interaccion completa.
- Seccion reordenada: pockets aparecen justo despues del canvas (antes que la tabla de evidencia estructural, ahora colapsada por defecto), con un selector compacto para cambiar de estructura.
- Spinner de carga animado, tipografia y botones alineados al sistema de diseño existente.

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

Grilla "Target profile" rediseñada como data sheet academica: flags de riesgo con icono+color de tono, metricas porcentuales con barra de magnitud, tipografia monoespaciada tabular para valores.

**Pendiente para avanzar.**

- Exponer los filtros de identidad/cobertura/e-value/organismo tambien desde la seccion off-target de la pagina de proteina.
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

- Fundacion agnostica a proveedor (interfaz `LLMProvider` neutral, Anthropic/OpenAI intercambiables), loop agentico generico, con alcance de genoma/proteina siempre re-derivado server-side (nunca confiado del cliente).
- Drawer global con historial por sesion, Markdown completo y pasada visual premium.
- Tools: `apply_filters`/`clear_filters`/`search_proteins`/`explain_target`/`audit_target_evidence`/`compare_targets`, marcando explicitamente evidencia "not loaded" para que el modelo no la confunda con evidencia negativa.
- Snapshot del estado de la UI (filtros, sort, pocket/estructura seleccionada) enviado con cada mensaje, para que el agente entienda la pagina completa.
- Logging de tokens/costo/latencia por request. Budget mensual resuelto fuera de la app (tope de gasto en la plataforma del proveedor). Permisos: aplicar/borrar filtros es directo sin confirmacion (reversible, no muta datos reales); toggle "Biologist mode" para explicaciones mas simples.
- Comando `evaluate_agent` para correr un set fijo de prompts contra el loop real y verificar comportamiento. Corrido varias veces contra datos reales; hallazgos corregidos: ambiguedad falta-vs-negativo en varias tools (chokepoint, centralidad), agrupamiento de filtros en una sola llamada, y distincion entre pregunta ("buscame targets") y accion explicita ("aplica este filtro").

Sin pendientes de codigo.

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

**Implementado.**

- Utilidades globales de entrada sutil y profundidad aplicadas a todas las paginas de la app, incluido el structure viewer fullscreen.
- Auditoria completa de las ~15 paginas: sin color/sombra hardcodeada, tokens muertos corregidos, sombras remapeadas a la escala de shadow tokens.
- Checklist de pre-merge documentado en `docs/VISUAL_CHECKLIST.md`.
- Hover-lift en los botones del structure viewer; header de `protein.html` unificado (Genome como chip junto a Gene/3D evidence/UniProt).

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
2. Premium UI consistency pass.
3. Visualizacion de Proteina 2.0.
4. Comparacion FPocket vs P2Rank.
5. Drogabilidad por fuente y estructura.
6. Integracion AlphaFill (ligando trasplantado sobre AlphaFold/ColabFold ya existente).
7. Sitios funcionales y anotaciones estructurales.
8. Priorizacion estructural completa.
9. Off-target 2.0.
10. Sequence & feature viewer 2.0.
11. Cross-references hub.
12. Pathway-level target prioritization.
13. Red de señalizacion/regulacion por proteina (KEGG PPI).
14. Evidence provenance / audit layer.
15. Constructor de score mejorado.
16. Columnas custom para analisis.
17. Auditoria Target viejo e integraciones externas (Ligysis, CSA Atlas).
