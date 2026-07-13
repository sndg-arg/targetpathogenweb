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
- Reemplazo del ranking secundario por cantidad de ligandos (`Strongest ligand support`) por
  `Worth a fresh look`: mismo score de evidence-convergence, restringido a proteinas con cero
  registros de ligando. El ranking por conteo premiaba proteinas "muy estudiadas" (homologos
  humanos de kinasas/GPCRs con muchos hits en ChEMBL/ZINC) independientemente de si eran buenos
  targets bacterianos — la misma homologia que el off-target penaliza en el mismo score. La
  nueva vista responde una pregunta real: candidatos druggable/selectivos que nadie exploro
  quimicamente todavia.
- Logica de scoring refactorizada en `_score_proteins`/`_format_score_items` (assembly_workspace.py)
  para que ambos rankings reusen el mismo calculo en vez de duplicarlo.
- Hero simplificado: 2 acciones primarias (`Proteins`, `Metabolism`) y el resto (Add data,
  Custom score, EC tree, BLAST) en una fila secundaria menos prominente, en vez de 6 botones
  con el mismo peso visual.
- Jerarquia tipografica arreglada en `Evidence available`: conteos de evidencia directa
  (PDB co-crystal, ChEMBL bioactive) mas grandes/bold/con acento; conteos transferidos
  (homologos, ZINC) mas chicos y grises. Antes tenian la misma tipografia y el numero mas
  grande (ej. ZINC propuesto) ganaba la atencion aunque fuera la evidencia mas debil.

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

- Controles de pocket renombrados a capas mas claras: `Alpha spheres`/`Pocket`, `Residues`, `Surface`, `Labels`.
- Tooltips por capa explicando que muestra cada representacion.
- Acciones `Zoom` y `Residues` con tooltip.
- Card de pocket/residue set marcada visualmente cuando alguna capa esta visible en el viewer.
- Diferenciacion visual leve entre cards FPocket y P2Rank.
- Accion `Inspect` para seleccionar un pocket, centrar camara, mostrar la capa `Pocket`, apagar capas visibles de otros pockets y completar un panel persistente de detalle.
- Panel de pocket seleccionado con metodo, score, capa visible, residuos y propiedades.
- El panel muestra propiedades importadas disponibles: para FPocket, volumen, score, alpha spheres, SASA, hidrofobicidad y flexibilidad; para P2Rank, score/probabilidad.
- La capa `Pocket` usa coordenadas importadas del output revisado cuando existen: alpha spheres de FPocket o atomos de superficie de P2Rank. La capa `Sector` conserva la superficie/residuos alrededor para contexto.
- Diferenciacion visual reforzada: alpha spheres/pocket core se renderiza como nube de beads pequenos y la superficie del entorno queda translucida para que no parezcan la misma capa.
- Bug encontrado y corregido: las alpha spheres se veian "sueltas" y no delimitaban un pocket
  reconocible. Causa real: cada esfera se dibujaba con un radio fijo hardcodeado de `0.34` A,
  ~10 veces mas chico que el radio real de una alpha sphere de FPocket (tipicamente unos pocos
  A). FPocket escribe el radio real de cada esfera en la columna B-factor de sus pseudo-atomos
  `STP` (confirmado en `FPocket2SQL.py`, que parsea esa columna PDB estandar a `Atom.bfactor`) —
  ese dato ya estaba en la base, pero se descartaba al armar los puntos para el viewer. Fix:
  `_atom_points` (`StructureView.py`) ahora incluye `radius` desde `atom.bfactor`, clampeado
  defensivamente entre `1.0` y `6.5` A (rango tipico de una alpha sphere real) con fallback de
  `2.5` A si el valor viene vacio o invalido, y `ngl_pocket_representations.js` usa
  `{{ point.radius }}` real para las alpha spheres de FPocket en vez del `0.34` fijo. Para P2Rank
  se mantuvo un radio fijo (subido de `0.28` a `1.1`) porque sus `core_points` son atomos de
  residuo reales (via `_residue_set_core_points`), cuyo B-factor es el valor cristalografico/
  predicho real, no un radio — usarlo ahi seria semanticamente incorrecto.
- Bug encontrado y corregido: `Inspect` dejaba "la proteina borrada". Causa: `inspectPocket`
  (en `structure.html` y `protein.html`) habia empezado a llamar `window.ngl_set_mode("density")`
  al inspeccionar un pocket, lo que apaga la representacion `cartoon` de toda la proteina y
  prende la superficie molecular completa (`__main_density`) en su lugar. Esa superficie ya tenia
  un bug de contraste independiente: su color en modo claro (`--tp-color-structure-density:
  #d8e1e9`) es casi identico al fondo del canvas (`--sv-viewer-canvas-bg: #f0f6fa`), asi que al
  apagarse el cartoon quedaba una superficie practicamente invisible contra el fondo — de ahi
  "se borra toda la proteina". Fix: se saco el cambio automatico de modo de `inspectPocket` (Inspect
  ahora solo prende la capa del pocket especifico, sin tocar el modo de vista global) y se corrigio
  el color de la superficie a `#a3c9d6` para que sea visible si se activa manualmente con el boton
  `Surface`. De paso se encontro y corrigio otro bug en la misma funcion: `pocketInspector.hidden`
  quedaba en `true` al final de `inspectPocket` (deberia ser `false` para mostrar el panel recien
  poblado) — el panel "Selected pocket" nunca llegaba a mostrarse.
- Bug encontrado y corregido: la logica de inicializacion del viewer NGL (`initStructureComponent`,
  `registerShapeComponent`) esta duplicada entre `structure.html` (viewer fullscreen) y
  `protein.html` (viewer embebido en el detalle de proteina) en vez de compartirse. El fix de
  `registerShapeComponent` para renderizar alpha spheres como `NGL.Shape` async (y el try/catch
  que evita que un fallo en el setup opcional de pockets tape el mensaje de carga real) se aplico
  solo en `structure.html`. `protein.html` seguia sin `registerShapeComponent` definido, asi que
  cualquier pocket con `core_points` reales tiraba `ReferenceError` dentro de `initStructureComponent`,
  y como el `.then(initStructureComponent)` de esa pagina no tenia try/catch, el error se propagaba
  y mostraba "Unable to load 3D structure" encima de una estructura que en realidad ya habia
  cargado. Portado el mismo `registerShapeComponent` y el mismo try/catch a `protein.html`.
- Riesgo abierto: esta duplicacion entre paginas es fragil — cualquier cambio futuro al init del
  viewer hay que aplicarlo en los dos lugares a mano. Candidato a refactor: extraer
  `initStructureComponent`/`registerShapeComponent` a un `{% include %}` o modulo JS compartido.
- Bug raiz encontrado y corregido (explica por que zoom/alpha spheres/Inspect seguian sin andar
  incluso despues del fix anterior): `js/entrypoint.js` solo importaba `Stage` de `'ngl'` con el
  alias `NGL` (`import {Stage as NGL} from 'ngl'; window.NGL = NGL;`) — nunca importaba `Shape`.
  `ngl_pocket_representations.js` hace `new NGL.Shape(...)` para las alpha spheres reales (FPocket)
  y los atomos de superficie reales (P2Rank); como `NGL.Shape` era `undefined`, esa linea tiraba
  `TypeError` dentro del loop de pockets de `initStructureComponent`, en las dos paginas por igual
  (comparten el mismo include). El try/catch de `13897ff` lo volvia silencioso (solo
  `console.error`) en vez de mostrar el banner de error, pero el efecto practico era el mismo: el
  loop de pockets se abortaba ahi mismo, asi que ningun pocket procesado desde ese punto en
  adelante (incluyendo P2Rank y residue sets) llegaba a registrar sus representaciones `_zoom`,
  `_sph`, `_lbl` — de ahi que el zoom no anduviera para la mayoria de los pockets y que Inspect
  (que depende de esas mismas representaciones) no hiciera nada. Fix: `entrypoint.js` ahora tambien
  importa `Shape` y lo cuelga de `window.NGL.Shape`; se corrio `npm run build` y se copio
  `js/bundle.js` a `static/bundle.js`.
- De paso, se llevo `ngl_zoom_to` de `protein.html` a la misma implementacion que `structure.html`
  (le faltaba la rama para zoomear sobre un `tpShapeComponent`, hoy sin uso porque `protein.html`
  no tiene boton Inspect, pero destinada a quedar inconsistente si se agrega mas adelante).
- Decidido y resuelto: `protein.html` usaba `pocket_tables.html` (checkboxes en una tabla, sin
  boton Inspect ni panel "Selected pocket") mientras `structure.html` usaba `pocket_cards.html` (la
  UI nueva con Inspect) — la razon real de que "Inspect no haga nada" en el detalle de proteina
  era que ese boton no existia ahi. Se decidio traer paridad completa en vez de mantener dos UIs
  de pockets: `protein.html` ahora incluye `pocket_cards.html` (cards + Inspect + capas de
  contexto) en lugar de `pocket_tables.html`, con su propio panel "Selected pocket" (mismos campos
  que en el viewer fullscreen: Method, Score, Visible layer, Residues, Pocket properties) y el
  mismo `inspectPocket`/`clearPocketSelection`/`setReprButtonPressed` portado a su `jsloaded()`.
  `pocket_tables.html` quedo sin uso en ningun lado — se elimino el archivo, junto con el CSS y el
  JS de `initPocketTableVariants`/DataTables que solo existian para esas tablas.
- De paso: se agregaron a `protein-detail.css` los estilos de `.pocket-card`/`.pocket-repr-btn`/
  `.sv-pocket-inspector` (portados de `structure-fullscreen.css`, reusando los tokens
  `--protein-accent*` que ya existian en vez de introducir uno nuevo), y se corrigieron 9 usos mas
  de tokens muertos encontrados de paso en `protein-detail.css` (`--tp-color-brand-400` que no
  existe -> `-500`/`-600` segun si era un estado persistente o de hover/focus, `--tp-color-sage-400`
  -> `-500`, tres usos de `--tp-color-sage-800` como texto/borde sobre fondo claro -> `-700`, y
  `var(--tp-font-body)` usado como `font-size` sin que ese token exista -> valor explicito
  `0.92rem`) mas un `--tp-color-sage-600` inexistente en `structure-fullscreen.css` -> `-500`.

- Hallazgo con datos reales (proteina AF_A0A0H3GWB0): las alpha spheres en si estaban bien (radio
  y posicion correctos, verificado con distancia de centroides contra los atomos de residuo del
  mismo pocket) — el problema real es que **los 4 pockets que la UI muestra por defecto (top-4 por
  druggability_score) resultaron ser, para esta proteina, los 4 mas grandes y difusos de sus ~111
  pockets** (26-53 A de diagonal / hasta 397 alpha spheres, contra 4-20 A / 15-100 en el resto) —
  probablemente una region de baja confianza del modelo de AlphaFold que FPocket puntua como
  drogable sin serlo. Por eso se veian como "un bodoque" y no como una cavidad.
- Implementado (fase 1, badge visual): `tpweb/services/pocket_geometry.py` (nuevo) calcula, por
  estructura, si el volumen de un pocket de FPocket es un outlier relativo a los *otros pockets de
  esa misma estructura* (mediana + MAD, z-score modificado de Iglewicz-Hoaglin, umbral 3.5,
  un solo lado — solo marca pockets mas grandes que la mediana, no mas chicos). Reusa el `Volume`
  que FPocket ya calcula por pocket (`ResidueSetProperty`), no recalcula geometria nueva.
  `StructureView.py`/`pdb_structure()` calcula esto para TODOS los pockets de la estructura (no
  solo el top-4 mostrado) y expone `p.size_outlier`/`p.size_outlier_note` por pocket, sin tocar el
  orden/ranking por druggability. `pocket_cards.html` muestra un chip "Unusual size" (reusando
  `.tp-chip--warning` del sistema de diseño) con tooltip explicando el volumen vs. la mediana de la
  estructura. Solo FPocket por ahora — P2Rank no tiene `Volume` guardado ni geometria de alpha
  spheres real, es una decision explicita, no un olvido.
- Implementado (fase 2, impacto en scoring): nuevo comando offline
  `python manage.py index_pocket_size_outlier <genoma>` — para cada proteina resuelve su pocket
  "representativo" (curado primero: si existen `best_fpocket_structure`/`fpocket_pocket` los usa,
  extrayendo el numero del string `"Pocket <N>"` y matcheandolo contra `PDBResidueSet.name`;
  si no hay dato curado o no matchea, cae al pick automatico por `druggability_score` maximo entre
  *todas* las estructuras ligadas a la proteina, no solo una), calcula si ese pocket es outlier con
  el mismo `pocket_geometry.py` de la fase 1, y guarda el resultado como `ScoreParamValue`
  `pocket_size_outlier` (Y/N). El `ScoreParam` se registra solo agregando una entrada a
  `SYSTEM_SCORE_PARAM_DEFINITIONS` (`tpweb/services/score_params.py`) — no hizo falta un metodo
  `Initialize_*` nuevo en `ScoreParam.py`, ese mecanismo ya autocrea el `ScoreParam`/opciones. Las
  funciones de matching de identificador de estructura (`_structure_identifier_candidates`/
  `_structure_matches_identifier`) se sacaron de `ProteinView.py` a
  `tpweb/services/structure_sources.py` para que las comparta el comando nuevo.
  `assembly_workspace.py`/`_score_proteins`: si el pocket con druggability alta/media es outlier,
  el sub-score de drogabilidad se descuenta (alta: 2.0 -> 1.0; media: 1.0 -> 0) y aparece como
  caution en vez de signal. `ProteinView.py`/`_build_target_executive_summary`: mismo caso agrega
  un item a **Risks** ("Best pocket may be a modeling artifact") en vez de a Strengths.
  No se copiaron los bugs reales de `index_druggability.py` (llamaba a un
  `ScoreParam.Initialize2()` inexistente, usaba mal `get_or_create`, asumia una sola estructura
  por proteina).

**Pendiente para cerrar.**

- Refinar modo de foco para atenuar geometricamente la proteina y otros pockets, no solo apagar capas activas.
- Agregar `Show only selected pocket` / `Show all pockets`.
- Agregar propiedades derivadas del pocket seleccionado, como centro geometrico estimado, distancia a ligandos/sitios funcionales y consenso FPocket/P2Rank.
- Verificar en datos reales de Klebsiella que `Pocket` muestra la cavidad/sitio especifico y `Sector` muestra el entorno amplio esperado.
- Verificar en el cluster con datos reales que zoom, alpha spheres e Inspect efectivamente andan
  ahora en las dos paginas (protein detail y viewer fullscreen) tras el fix de `NGL.Shape` y la
  paridad de UI — no se pudo probar en un navegador real desde este entorno.
- Evaluar unificar `initStructureComponent`/`registerShapeComponent` entre `structure.html` y
  `protein.html` para que este tipo de bug de duplicacion no vuelva a pasar.
- Bug encontrado y corregido: el nombre real del `Property` de volumen en la base es `'volume'`
  (minuscula, snake_case) — se asumio `"Volume"` (con mayuscula) copiando la lista existente
  `_FPOCKET_INSPECTOR_PROPERTIES` en `StructureView.py`, que en realidad **nunca matcheo nada**
  (usa claves como `"Volume"`, `"Score"`, `"Number of Alpha Spheres"` contra nombres reales
  `volume`, `score`, `number_of_alpha_spheres`, etc. — confirmado contra la base real, listando
  todos los `Property.objects.all()`). Corregido en `StructureView.py` (fase 1) y
  `index_pocket_size_outlier.py` (fase 2) para usar `'volume'`. La lista
  `_FPOCKET_INSPECTOR_PROPERTIES` en si sigue rota (bug preexistente, no tocado — el panel
  "Pocket properties" del inspector probablemente nunca mostro nada); queda para otra sesion.
  Tambien se hizo mas defensivo el comando: si el `Property` de volumen no existe, corta con un
  mensaje claro en vez de un traceback de `DoesNotExist`.
- Corrido `index_pocket_size_outlier public__KpATCC43816` en produccion: 1549 de 5071 proteinas
  (30.7% sobre 5049 con dato curado) quedaron marcadas como outlier. Investigado a fondo si esto
  era un bug de calibracion (sospecha inicial: MAD degenerado en estructuras con poca variacion de
  volumen, amplificando diferencias chicas a z-scores enormes) — **descartado con datos reales**:
  para `VK055_0002` (13 pockets FPocket, mediana de volumen 411.7, MAD 149.0 — spread normal, no
  degenerado) el pocket curado por las biologas (`Pocket 13`, resuelto correctamente contra la
  estructura `CB_VK055_0002`) es el mas grande de los 13 (1816.5 vs mediana 411.7, z=6.4,
  druggability 0.911) — un outlier genuino, no un artefacto del calculo. A nivel genoma, el flag
  cae casi enteramente sobre proteinas curadas (1549/5049, 30.7%) vs. 0/22 no curadas (muestra muy
  chica para sacar conclusion de la comparacion en si, pero confirma que el flag no esta pegando
  parejo por azar). Conclusion: **el 30% es la señal real que el feature se propuso capturar**, no
  un bug — el pipeline Gates-Targets elige "mejor pocket" por drogabilidad maxima sin penalizar
  tamaño/difusidad, y una fraccion sustancial de esas elecciones resultan ser geometricamente
  atipicas dentro de su propia estructura, igual que en el hallazgo original con AF_A0A0H3GWB0.
  Decision tomada con la usuaria: mantener el umbral z=3.5 (estandar Iglewicz-Hoaglin, sin ajustar
  arbitrariamente para bajar el % de flags) — confirma que la resolucion curated-first (`fpocket_pocket`
  "Pocket <N>" -> `PDBResidueSet.name`) funciona correctamente contra datos reales, cerrando dos
  de los pendientes de abajo. Esto tambien confirma que `volume` esta poblado para estructuras
  reales (no solo la proteina de prueba original).
- Confirmado en el navegador (proteina VK055_0002, KpATCC43816): el chip "Unusual size" aparece
  correctamente en 3 de los 4 pockets FPocket mostrados (#13, #10, #12) y no en el cuarto (#8) —
  verificado pocket por pocket contra el calculo real de volumen/mediana/MAD (z=6.36, 3.55, 4.77
  para los marcados, z=0.67 para el no marcado). Coincide 100% con lo que muestra la UI.
- Confirmado contra el archivo curado ORIGINAL (`KpATCC43816_results_table.tsv`, Google Drive,
  subido por las biologas): la fila de `VK055_0002` dice literalmente `fpocket_pocket=Pocket 13`,
  `best_fpocket_structure=CB_VK055_0002`, `druggability_score=0.911` — identico a lo cargado en la
  base y a lo que muestra la pagina de proteina. Cadena completa validada de punta a punta: archivo
  curado original -> base de datos -> UI -> calculo de outlier, sin discrepancias. `Pocket 13` es
  realmente la eleccion de las biologas (no un bug de resolucion curated-first), y es un outlier de
  volumen genuino (1816.5 vs mediana 411.7 de esa estructura) — exactamente el caso que el feature
  fue diseñado para capturar. Investigacion cerrada con confianza alta.
- Confirmar con el equipo de bioinformatica la magnitud del descuento en `_score_proteins` (hoy:
  alta drogabilidad + outlier = mitad de puntos; media drogabilidad + outlier = cero puntos) — es
  ajustable en un solo `if`, no bloquea nada correrlo ya con este valor por default. Con un 30.7%
  de proteinas curadas afectadas, esta decision tiene mas peso practico de lo esperado inicialmente
  — vale la pena revisarla pronto con el equipo, no dejarla indefinidamente en "pendiente".

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

Agregar un agente/chat IA que ayude a explorar proteinas, filtros, scores, ligandos, estructuras y evidencia cargada en TPW. Requisito explicito: agnostico a que API de LLM se use (Claude u OpenAI intercambiables).

**Alcance propuesto.**

- Responder preguntas usando datos del sistema.
- Explicar por que un target aparece priorizado.
- Sugerir filtros y comparaciones.
- Ayudar a interpretar evidencia estructural, metabolica y off-target.
- Citar las fuentes internas usadas para cada respuesta.
- Ejecutar acciones reales en la UI a pedido del usuario (ej. aplicar filtros), no solo responder texto.

**Implementado (fundacion + proveedores + tools + endpoint + UI).**

Decisiones confirmadas con la usuaria antes de implementar: panel lateral flotante (no burbuja
minimal, no solo backend), soporte OpenAI real y no scaffold (la organizacion paga ChatGPT, no
Claude, todavia no convencieron de migrar), y alcance amplio de tools desde el arranque (filtros +
explicacion de score + busqueda + contexto metabolico/off-target), aceptando que podia quedar a
medio terminar en una sesion.

- `tpweb/services/llm/base.py`: tipos neutrales (`Message`, `ToolDefinition`, `ToolCall`,
  `ToolResult`, `LLMResponse`) y la interfaz `LLMProvider`, para que el resto del codigo nunca
  dependa de un SDK de proveedor especifico.
- `anthropic_provider.py`: adaptador real sobre el SDK `anthropic`.
- `openai_provider.py`: **adaptador real** (ya no scaffold) sobre el SDK `openai`, Chat Completions
  con tool-calling. La parte no trivial: un `Message` neutral con varios `ToolResult` (que
  `agent.py` arma como un solo mensaje) se expande a **varios** mensajes `role="tool"` separados,
  uno por resultado — OpenAI no tiene forma de agrupar varios resultados en un solo mensaje como
  si hace Anthropic con bloques `tool_result`. `finish_reason` mapea a los mismos
  `stop_reason` neutrales (`stop`->`end_turn`, `tool_calls`->`tool_use`, `length`->`max_tokens`).
  `arguments` de cada tool call viene como string JSON (a diferencia del dict ya parseado de
  Anthropic) — parseado con guard contra `JSONDecodeError`. Tests unitarios con cliente fake
  (`OpenAIProviderTranslationTests` en `tpweb/tests.py`) cubren el aplanamiento de tool-results,
  el mapeo de `finish_reason` y el round-trip de `arguments` — no requieren `OPENAI_API_KEY` ni red.
- `provider_factory.py`: selecciona adaptador via env var `TPW_LLM_PROVIDER` (default
  `anthropic`), mismo patron que `TPW_COLABFOLD_USE_REMOTE` etc. Sin cambios necesarios para
  soportar OpenAI real, la rama `"openai"` ya estaba lista.
- `agent.py`: loop agentico generico (`Agent.run()`), agnostico al proveedor. Se agrego un
  parametro opcional `history: list[Message] | None = None` para sembrar la conversacion desde un
  historial previo (usado por `AgentChatView`) sin romper `test_llm_agent.py` (default `None` =
  comportamiento identico a antes). Tambien expone `self.last_messages` tras `run()` con la
  conversacion completa actualizada (historial + este turno, incluyendo intercambios de tools),
  para que el caller pueda persistirla/devolverla sin cambiar el tipo de retorno de `run()` (sigue
  siendo `str`).
- `tools/demo.py` + management command `test_llm_agent`: prueba end-to-end minima
  (`get_current_time`), sigue funcionando sin cambios.
- **`tools/apply_filters.py`** (nuevo): dos tools —`list_available_filters()` (lista ScoreParams
  visibles para el usuario via `visible_score_params_queryset`, con los ids concretos que
  `apply_filters` necesita) y `apply_filters(changes)` (aplica cambios de filtro a
  `selected_parameters` en sesion, mismo mecanismo que usa `ProteinListView` — un filtro aplicado
  por el agente ya se ve si el usuario despues abre la lista de proteinas de ese genoma).
- **`tools/explain_target.py`** (nuevo): `explain_target(accession)` devuelve un resumen en texto
  plano (no JSON crudo, para que el modelo parafrasee en vez de inventar detalles) con score de
  evidence-convergence, veredicto, strengths/risks/missing y oracion de contexto metabolico —
  unifica en una sola tool lo que iban a ser "explicar score" + "contexto metabolico/off-target"
  por separado, ya que responden la misma pregunta real del usuario ("¿es un buen target?").
- **`tools/search_proteins.py`** (nuevo): `search_proteins(changes, search_text, limit)` reusa
  exactamente el mismo esquema `changes` que `apply_filters` (no lo aplica a la sesion, lo aplica a
  una lista descartable), para que el modelo aprenda un solo lenguaje de filtros en vez de dos.
- **Extracciones de servicio necesarias para las tools** (mecanicas, sin reescritura de logica):
  - `tpweb/services/protein_list.py`: `apply_filter_change`/`apply_filter_changes` (portado de
    `ProteinListView._apply_filter_change`/`_apply_filter_changes_payload`, que ahora delegan);
    `build_special_filter_payload`/`build_numeric_filter_payload` (portados de los metodos
    estaticos homonimos de la vista, que se eliminaron por quedar sin uso); `find_top_proteins`
    (nuevo, compone `apply_selected_parameter_filters`+`apply_protein_search`, sin paginacion).
  - `tpweb/services/assembly_workspace.py`: `score_single_protein(assembly_name, accession)` —
    wrapper barato sobre `_score_proteins` (que sigue siendo genome-wide por diseño, no se
    reescribio para una sola proteina).
  - **`tpweb/services/protein_summary.py`** (nuevo): todo el bloque de construccion del resumen
    ejecutivo se movio verbatim desde `tpweb/views/ProteinView.py` (`_build_target_profile`,
    `_build_selected_pocket_evidence`, `_build_conservation_profile`, `_build_microbiome_context`,
    `_build_metabolic_context`, `_build_target_executive_summary`, y sus helpers privados),
    renombrado a nombres publicos sin guion bajo. Motivo: CLAUDE.md es explicito en que las vistas
    delegan a servicios, no al reves — importar funciones privadas de una vista desde un servicio
    invertia esa direccion. `ProteinView.py` reimporta con alias (`build_target_profile as
    _build_target_profile`, etc.) para que los call-sites existentes no cambien ni una linea.
    Se agrego `build_protein_executive_context(protein)` como entry-point unico para
    `explain_target`, que replica exactamente lo que hace `ProteinView.get` (mismo query de
    `raw_scores`, mismos builders). Unica salvedad: `create_binders_dict` sigue viviendo en
    `ProteinView.py` (no se extrajo, fuera de alcance de este cambio) — `protein_summary.py` lo
    importa de forma diferida (dentro de la funcion, no a nivel de modulo) para evitar import
    circular, ya que `ProteinView.py` importa de `protein_summary.py` a nivel de modulo.
- **`tpweb/views/AgentChatView.py`** (nuevo) + `POST /agent-chat` en `tpweb/urls.py`: endpoint unico
  y global (no scoped por genoma en la URL, porque el panel esta presente incluso en paginas sin
  genoma como el home). El scope de genoma/proteina **nunca** se toma del cuerpo del request tal
  cual lo manda el cliente — se re-deriva server-side con `django.urls.resolve(page_path)` contra
  las URLs reales de la app (`genome/<genome>`, `protein/<protein_id>`), y se valida con
  `user_can_access_genome_name` antes de habilitar ninguna tool con alcance de genoma. Si no
  resuelve o no pasa el check de acceso, el chat sigue funcionando pero sin las tools de
  filtros/busqueda/explain (con una nota en el system prompt). El historial de conversacion es
  **stateless**, viaja completo ida y vuelta en el JSON (`history`) — el navegador lo guarda en
  memoria mientras dura la pestaña; no sobrevive un reload. Es una limitacion v1 aceptada
  explicitamente, no un olvido — una conversacion persistida necesitaria un modelo
  `AgentConversation` nuevo.
- **Panel lateral** (`tpweb/templates/base/masterpage.html` + `static/css/components/agent-drawer.css`
  + `static/js/global/agent-drawer.js`): boton disparador en `.tp-side-footer` (junto al toggle de
  tema) y version compacta en la topbar movil; drawer fijo a la derecha con slide-in, usando
  tokens del sistema de diseño existentes (`--tp-ui-radius-panel`, `--tp-shadow-lg`,
  `--tp-ui-motion-base`, `--tp-color-scrim`) — sin hex hardcodeado, tema claro/oscuro automatico
  porque esos tokens ya son theme-aware via la clase `.tp-dark`. CSS/JS cargados globalmente desde
  `masterpage.html` (excepcion deliberada y documentada a "un CSS por pagina", igual que
  `ui-system.css`; el JS sigue el patron ya existente de scripts planos por `<script src>` como
  `protein-detail.js`, no pasa por el bundle de webpack). El JS lee `page_path` con
  `window.location.pathname` en cada envio, asi que navegar entre paginas durante una conversacion
  "simplemente funciona" sin plumbing extra.

**Pendiente para avanzar.**

- Probar en vivo con API key real de Anthropic y de OpenAI (no ejecutable desde este entorno) —
  correr `python manage.py check`, la suite de tests, y despues un smoke test real por navegador:
  abrir un genome overview, preguntar por proteinas con alta drogabilidad sin homologo humano
  (`search_proteins`), pedir aplicar ese filtro y confirmar en la pagina de lista; abrir una
  proteina puntual y preguntar por que es un buen target (`explain_target`); repetir con
  `TPW_LLM_PROVIDER=openai` para confirmar paridad entre proveedores.
- QA visual del panel en claro/oscuro y en mobile — no verificable desde este entorno.
- Definir de donde sale el contexto que el agente necesita mas alla de lo ya resuelto (que
  ScoreParams existen ya se resuelve con `visible_score_params_queryset`, que filtros estan
  aplicados ya se resuelve leyendo la sesion) — pendiente solo si aparecen nuevas necesidades de
  contexto al usarlo en la practica.
- Evaluar si conviene persistir historial de conversacion (modelo `AgentConversation`) si el
  stateless-por-pestaña resulta insuficiente en uso real.
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
- Auditoria y limpieza de colores/sombras hardcodeadas en `ui-system.css`, `proteins-list.css`,
  `structure-fullscreen.css`, `protein-detail.css`, `metabolism-overview.css` y `genome-overview.css`:
  fallbacks hex muertos sobre tokens que ya existian, tokens referenciados que directamente no
  existian (`--tp-color-amber-800`, `--tp-color-danger-500/700`), chips con hex crudo sin `var()`,
  y sombras `rgba()` sueltas remapeadas a la escala `--tp-shadow-xs/sm/md/lg` ya existente. Se
  agrego `--tp-color-scrim` (backdrop de modal, theme-aware) y `--sv-shadow` (familia de tokens
  del structure viewer) donde no habia un token que calzara.
- Bug sistemico encontrado y arreglado: el keyframe compartido `tp-ui-enter` (y 8 copias
  page-specific del mismo patron) terminaba en `transform: translateY(0)`/`scale(1)` con
  `animation-fill-mode: both`, dejando un transform permanente e invisible en `.genome-card` y
  equivalentes. Cualquier transform persistente en un ancestro de un `<select>` nativo rompe el
  posicionamiento del dropdown en Chromium — asi se rompio el select de Downloads en genome
  overview. Corregido en los 9 archivos (afecta tambien BLAST, que tiene su propio `<select>`).

- Auditoria de las 9 paginas restantes (home/index, binder-detail, auth, blast, customparam,
  formula-form, genome-upload, genomes-list, annotation-explorer): sin hex/rgba hardcodeados
  (mejor estado que las paginas auditadas antes). Se encontraron y corrigieron 2 tokens muertos
  referenciados pero inexistentes: `--tp-color-brand-400` (el ramp de brand salta de 500 a 300,
  no tiene 400) en `formula-form.css` y `annotation-explorer.css`, remapeado a `--tp-color-brand-600`
  siguiendo el uso ya establecido de 600 para estados focus/active/scrollbar-thumb en el resto de
  la app; y `--tp-font-body` (no existe ningun token de font-family, la convencion es escribir el
  stack literal) en `formula-form.css`, reemplazado por el stack literal de body ya usado en
  masterpage.html. Tambien se limpiaron 2 fallbacks muertos sobre `--tp-ui-motion-fast` (con un
  valor incorrecto, 120ms en vez de los 140ms reales del token) y `--tp-color-surface-soft` en
  `home.css`.
- Confirmado que `home.css` y `binder-detail.css` (las unicas 2 de las 9 que no habian pasado por
  el fix del keyframe `tp-ui-enter`) no tienen el bug: `home.css` solo usa una animacion `infinite`
  de spin (no entrance/fill-mode), y `binder-detail.css` ya usa el keyframe compartido `tp-ui-enter`
  que se arreglo en `ui-system.css`.

**Pendiente para cerrar.**

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
