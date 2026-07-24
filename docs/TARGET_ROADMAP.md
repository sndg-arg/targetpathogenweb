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

## En progreso

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
- Ranking de rutas a nivel genoma.
- Pagina de mapa por ruta individual.
- Grafo genome-wide estilo Krona.

**Feedback de biologas.**

- Les gusto:
  - `Metabolic context` en pagina de proteina.
  - Ranking de rutas.
- No les termino de convencer:
  - Topologia de fuerza de los grafos.
  - Falta de principio/fin claro en la lectura de rutas.

**Pendiente.**

- Agregar busqueda por proteina en el ranking de rutas.
- Pulir visualmente `Metabolic context` en pagina de proteina.
- Redisenar grafos con layout mas ordenado, estilo MetaCyc.
- Evaluar si conviene conectar metabolito-a-metabolito con la reaccion como label de borde, en vez de usar metabolito y reaccion como nodos separados.

### Visualizacion de Proteina 2.0

Redisenar el visualizador 3D como experiencia completa.

**Ya existe.**

- Spin apagado por defecto.
- Estados de botones sincronizados.
- Nota aclarando que FPocket/P2Rank son predicciones computacionales.

**Falta.**

- Coloreo por cadena.
- Coloreo por estructura secundaria.
- Manejo claro de estructuras multimericas.
- Selector de estructura priorizado por fuente, cobertura y calidad.
- Mejor toolbar de camara y modos.
- Decidir si la pagina embebida debe ser preview liviana y el full viewer la experiencia principal.

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

**Alcance.**

- Distancia entre centros.
- Porcentaje de residuos compartidos.
- Solapamiento espacial.
- Badge de consenso estructural.
- Filtro para priorizar proteinas donde ambos metodos coinciden en el pocket principal.

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

**AlphaFill.**

- Prioridad alta.
- Mejor costo/beneficio evaluado.
- Base publica `alphafill.eu`.
- Trasplanta ligandos/cofactores desde estructuras homologas resueltas experimentalmente sobre modelos AlphaFold.
- API por UniProt ID.

**Ligysis.**

- Potencial fuente para sitios de union e interacciones ligando-proteina.
- Falta evaluar cobertura/licencia/API.

**CSA Atlas.**

- Potencial fuente para residuos cataliticos.
- Falta evaluar mapeo a proteina/estructura/residuo.

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
