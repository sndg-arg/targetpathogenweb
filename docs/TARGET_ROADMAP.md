# TargetPathogen roadmap

Documento vivo para ordenar tareas de producto e implementacion. La idea es mantener aca el backlog tecnico-funcional que antes estaba en Notion, con estado, alcance y prioridades.

## Estado actual

### Hecho / en validacion

Estas tareas ya tienen implementacion en la rama actual y necesitan revision visual/funcional en datos reales antes de darlas por cerradas.

### Corte actual - 2026-07-17

- Metabolismo: implementado end-to-end para Klebsiella, con ingesta SBML/TSV/SIF, contexto por
  proteina, ranking por ruta, vistas navegables y ahora tambien un grafo unico genome-wide con
  zoom in/out estilo Krona por pathway (a pedido de las biologas, que no querian navegar ruta por
  ruta). Sigue en validacion biologica fina.
- Protein detail / genome overview: ya tienen resumen ejecutivo, evidencia estructural/quimica/metabolica y lenguaje mas explicativo para biologos. Queda seguir puliendo criterios de ranking y wording.
- Pockets / estructura: se agrego lectura de pockets especificos y alpha spheres desde outputs originales de GATES, mas controles visuales iniciales. Queda validar que la representacion sea biologicamente clara y no confunda "zona" con "pocket puntual".
- Agente IA: ya funciona con OpenAI en cluster, tiene drawer global, historial por sesion, tools
  para filtros, explicacion de targets, auditoria de evidencia y comparacion de candidatos, ahora
  con snapshot de estado de UI (filtros/sort/pocket/estructura/filas visibles), Markdown completo
  en el drawer (tablas, codigo, listas ordenadas, links) y logging de tokens/costo/latencia por
  request. El foco siguiente es un set chico de evaluacion y definir budget/alertas.
- UX premium: hay sistema visual mas consistente en paginas principales, pero falta una pasada sistematica por las vistas de mayor uso para cerrar inconsistencias de motion, sombras, botones, spacing y jerarquia de datos.

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

**Pendiente para cerrar.**

- Validar con biologas si la interpretacion de chokepoint `producing`, `consuming` y `both` se entiende igual que en el pipeline.
- Agregar export/import curado para BioCyc SmartTables cuando haya archivo ejemplo.
- Mejorar leyendas biologicas: explicar que significa centralidad, isoenzima, chokepoint y pathway sin cargar la UI.
- Agregar filtros por ruta en la tabla principal de proteinas.
- Agregar validaciones automaticas de ingesta para detectar SBML/TSV/SIF inconsistentes.
- Validar visualmente el grafo de red unificado en modo claro (confirmado en oscuro via captura
  real en el cluster); revisar tambien con un genoma bacteriano mas chico, donde la mayoria de
  pathways tendria pocas reacciones y casi ningun nodo quedaria con label permanente.
- Evaluar un modo de colapsar de nuevo un pathway ya abierto sin pasar por "All pathways" (hoy solo
  existe volver a la vista completa), si en el uso real se pide comparar dos rutas abiertas a la vez.
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
directa mas prominente que la transferida).

**Pendiente para cerrar.**

- Validar pesos con biologas y equipo de bioinformatica.
- Validar si el maximo teorico de 15 puntos y los cortes Strong >=65%, Moderate 40-65% y Limited <40% son intuitivos para usuarios biologos.
- Definir si el score compuesto debe convertirse en `ScoreFormula` editable o quedar solo como ranking de overview.
- Agregar export del ranking compuesto con desglose de contribuciones.
- Validar con biologas si `Worth a fresh look` (candidatos sin evidencia de ligando) se entiende
  como "vale la pena explorar" y no como "target debil".

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

**Pendiente para cerrar.**

- Refinar modo de foco para atenuar geometricamente la proteina y otros pockets (hoy solo apaga capas).
- Agregar toggle `Show only selected pocket` / `Show all pockets` y propiedades derivadas (centro
  geometrico, distancia a ligandos/sitios funcionales, consenso FPocket/P2Rank).
- Verificar en el cluster con navegador real que zoom/alpha spheres/Inspect andan en las dos
  paginas — no se pudo probar en un navegador real desde este entorno.
- Unificar `initStructureComponent`/`registerShapeComponent` (duplicado entre `structure.html` y
  `protein.html`) para que este tipo de bug de duplicacion no vuelva a pasar.
- Confirmar con el equipo de bioinformatica la magnitud del descuento de scoring por outlier (hoy:
  alta drogabilidad = mitad de puntos, media = cero) — con 30.7% de proteinas curadas afectadas,
  pesa mas de lo esperado y conviene revisarla pronto, no dejarla indefinida.

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

- Filtros por identidad/cobertura/e-value/organismo: ya existen como filtros numericos genericos
  en la lista de proteinas (`human_identity`, `human_evalue`, etc. via `_NUMERIC_FILTER_PLACEHOLDERS`
  en `protein_list.py`) — falta evaluar si conviene exponerlos tambien desde la propia seccion
  off-target de la pagina de proteina, no solo desde el filtro de lista.
  Explicacion de riesgo mas rica (oracion interpretativa por eje, tipo la que ya existe para
  metabolismo) y la integracion explicita con estructura/ligandos/drogabilidad/score final siguen
  sin implementar — quedan como alcance mas amplio para otra sesion.

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
proveedores), acumulado por `Agent.run()` a lo largo de todo el loop de tool-use (no solo la
ultima llamada). `AgentChatView` loguea por request modelo, tokens, latencia, turnos y tool
calls (o el error) via el logger `tpweb.agent`. Cada resultado individual de tool queda
capado a 8000 caracteres antes de volver a entrar a la conversacion, ya que nada lo acotaba
antes.

**Pendiente para avanzar.**

- Armar un set chico de evaluacion con prompts reales y resultado esperado:
  "por que esta proteina es buen target", "de donde sale esa conclusion", "comparame A vs B",
  "buscame targets sin off-target humano y con buen pocket", "borrame filtros". Debe chequear
  que use tools cuando corresponde y que no invente evidencia.
- Definir budget mensual recomendado para demo interna y donde alertar si se supera (el log de
  tokens/costo ya existe, falta la parte de politica/alerta).
- El historial que viaja del cliente ya se recorta (`_compact_history`), pero sigue sin haber un
  limite al tamaño acumulado dentro de una sola conversacion muy larga entre varios turnos.
- Mensajes de error mas accionables en el drawer (hoy son genericos: "el asistente no esta
  disponible" / "no se pudo conectar"), y evaluar si conviene registrar en el snapshot de pagina
  el estado especifico del structure viewer 3D (spin/coloreo/capas), que hoy no se captura.
- Agregar modo "biologo": explicaciones con glosario corto para terminos como FPocket, P2Rank,
  ZINC, ChEMBL, AlphaFold DB, ColabFold, off-target, chokepoint, e-value, identidad y cobertura.
- Definir permisos de acciones: que puede hacer solo leyendo, que puede cambiar en la UI
  (filtros), y que requiere confirmacion futura (crear score, guardar columnas, exportar).
- Evaluar persistir historial de conversacion (modelo `AgentConversation`) si el historial por
  pestaña resulta insuficiente en uso real o si se quiere auditar decisiones.
- Extraer `create_binders_dict` de `ProteinView.py` a un servicio propio para sacar el import
  diferido de `protein_summary.py` (hoy funciona bien, pero es una direccion de dependencia menos
  limpia que el resto de la extraccion).

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

**Pendiente para cerrar.**

- Definir un checklist visual antes de mergear nuevas vistas.
- Revisar en modo claro/oscuro con screenshots reales, incluida la nueva motion del structure viewer.
- Structure viewer: evaluar micro hover-lift en los botones del toolbar flotante (hoy solo
  cambian background/color/opacity) — no se toco en esta pasada para no arriesgar el look
  "glass" ya establecido sin poder probarlo en un navegador real desde este entorno.

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
