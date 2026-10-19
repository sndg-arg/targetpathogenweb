# AGENTS.md — Trabajo eficiente con Codex y Claude

Las convenciones específicas de este repo (arquitectura, pipeline, deploy, tests, CSS) están en
`CLAUDE.md`; este archivo define cómo trabajar, no qué hace el proyecto.

## Objetivo

Completar las tareas correctamente utilizando el mínimo contexto, tiempo y herramientas necesarios.

Principio fundamental: ahorrar tokens significa evitar trabajo innecesario, no sacrificar calidad, seguridad ni verificaciones importantes.

Priorizar soluciones simples, mantenibles y acordes con las convenciones del proyecto.

## 1. Comunicación y contexto

- Responder de forma breve, clara y concreta.
- Evitar explicaciones extensas, repeticiones y narraciones de cada comando ejecutado.
- Comunicar avances únicamente cuando haya resultados, decisiones importantes, bloqueos o cambios de plan.
- Antes de comenzar tareas complejas, resumir brevemente el enfoque.
- Al finalizar, informar qué se hizo, qué se verificó y qué quedó pendiente.
- No pegar logs completos, archivos extensos ni resultados repetitivos en el chat.
- Mantener el contexto existente mientras la tarea continúe siendo la misma.
- Después de una compactación, continuar desde el resumen disponible. Releer únicamente lo necesario.
- Para tareas independientes, sugerir una conversación nueva solo cuando separar el contexto resulte beneficioso.
- No afirmar que se cambió el modelo o el nivel de razonamiento. Solo recomendar ajustes que el usuario pueda realizar.

## 2. Exploración eficiente del proyecto

Antes de utilizar herramientas, identificar qué información se necesita y para qué.

- Explorar primero la estructura relevante del repositorio.
- Preferir búsquedas específicas con `rg`, `rg --files` o herramientas equivalentes.
- Limitar búsquedas por directorio, extensión, patrón o cantidad de resultados.
- No leer archivos completos cuando solo se necesita una función, clase o sección.
- Evitar recorrer todo el repositorio sin una razón concreta.
- Reutilizar información obtenida anteriormente si sigue siendo válida.
- Detener la exploración cuando exista contexto suficiente para actuar.
- Ampliar las búsquedas únicamente para resolver incertidumbres específicas.
- Agrupar operaciones independientes cuando sea posible.
- Evitar búsquedas redundantes entre agentes.

Estrategia recomendada:

1. Localizar los archivos relevantes.
2. Identificar símbolos, funciones o configuraciones involucradas.
3. Leer únicamente las secciones necesarias.
4. Realizar el cambio.
5. Ejecutar verificaciones específicas.

## 3. Optimización de tokens y herramientas

- Utilizar la herramienta más directa para cada operación.
- Evitar llamadas que no aporten información nueva o permitan tomar una decisión.
- Preferir comandos con salida breve y estructurada.
- Filtrar resultados antes de incorporarlos al contexto.
- Guardar salidas extensas en archivos temporales cuando sea necesario.
- Mostrar resúmenes, errores y fragmentos relevantes en lugar de resultados completos.
- No repetir tests, compilaciones o consultas si nada relevante cambió.
- Evitar generar documentación, ejemplos o archivos auxiliares que no aporten valor al pedido.
- No instalar dependencias ni introducir herramientas nuevas sin necesidad.
- No optimizar exclusivamente por cantidad de llamadas: una llamada útil es preferible a varias llamadas pequeñas redundantes.

Para comandos potencialmente verbosos, redirigir la salida a un archivo temporal y consultar solo los fragmentos necesarios, conservando el código de salida.

No ocultar errores para reducir tokens.

## 4. Salida de consola y codex-quiet

- Antes de utilizar `codex-quiet`, verificar que esté instalado y disponible (`command -v codex-quiet`).
- Fuente versionada en este repo: `scripts/codex-quiet.py` (copia instalada en `~/bin`). Si `codex-quiet` no está en el PATH (p. ej. en nodo0 o en un contenedor), usar `python scripts/codex-quiet.py -- <comando>`.
- Para comandos potencialmente verbosos (tests, builds, instalaciones, linting, etc.), preferir `codex-quiet -- <comando>`.
- No utilizarlo para comandos cuya salida breve sea necesaria directamente.
- `codex-quiet` guarda la salida completa en un log temporal y devuelve un JSON compacto con `ok`, `exit_code`, `seconds`, `bytes`, `lines` y `log`.
- Si el comando termina correctamente, utilizar el JSON como evidencia de ejecución. No leer el log salvo que se necesite verificar información específica.
- Si falla, revisar primero `error_tail`. Consultar fragmentos adicionales del archivo indicado en `log` únicamente cuando sea necesario.
- Respetar el código de salida: no interpretar un comando fallido como exitoso.
- Utilizar `--timeout` cuando exista riesgo de ejecuciones excesivamente largas.
- No utilizar `--preview-lines` por defecto; activarlo únicamente cuando se necesite inspeccionar parte de la salida exitosa.
- Si `codex-quiet` no está disponible, redirigir salidas extensas a archivos temporales, conservando el código de salida y mostrando únicamente un resumen relevante.
- Evitar ejecutar nuevamente un comando solo para recuperar su salida: consultar primero el log existente.
- Los logs originales pueden contener secretos. No compartirlos ni incorporarlos al repositorio; la redacción de credenciales en el JSON no garantiza que el log sea seguro.

## 5. Uso de subagentes

Utilizar subagentes cuando permitan ejecutar trabajo independiente en paralelo o separar investigaciones complejas.

Delegar cuando:

- Existan tareas independientes que puedan ejecutarse simultáneamente.
- Sea necesario investigar componentes diferentes.
- Una revisión especializada aporte valor.
- La separación de contexto reduzca trabajo duplicado.

No delegar cuando:

- La tarea sea trivial o breve.
- Los pasos dependan estrictamente unos de otros.
- Coordinar agentes resulte más costoso que resolver el problema.
- Varios agentes terminarían leyendo o modificando los mismos archivos.

Cada delegación debe especificar:

- Objetivo concreto.
- Archivos o componentes bajo su responsabilidad.
- Contexto mínimo necesario.
- Restricciones relevantes.
- Resultado esperado.
- Criterio de finalización.

Los subagentes deben devolver conclusiones, archivos modificados y evidencia relevante, evitando transcripciones completas de su trabajo.

El agente principal debe coordinar, integrar y verificar los resultados.

Evitar escrituras simultáneas sobre los mismos archivos.

Si no existe soporte para subagentes, continuar normalmente sin simular delegaciones.

## 6. Implementación y modificaciones

- Resolver el pedido completo dentro del alcance autorizado.
- Seguir el estilo, arquitectura y convenciones existentes.
- Preferir cambios pequeños, localizados y fáciles de revisar.
- Evitar refactorizaciones no relacionadas con el objetivo.
- No introducir abstracciones innecesarias.
- No agregar dependencias si la solución puede implementarse razonablemente con las existentes.
- No modificar archivos ajenos a la tarea sin justificación.
- Revisar los cambios antes de finalizar.
- No sobrescribir trabajo preexistente del usuario.
- No revertir cambios ajenos para simplificar la implementación.
- Ante ambigüedades menores, tomar decisiones razonables y explicarlas brevemente.
- Preguntar únicamente cuando falte información indispensable o exista una decisión material que corresponda al usuario.

Priorizar código legible y mantenible sobre soluciones excesivamente sofisticadas.

## 7. Tests y verificaciones

Realizar verificaciones proporcionales al alcance y riesgo de los cambios.

- Ejecutar primero los tests más específicos.
- Ampliar a suites mayores cuando sea necesario.
- Verificar compilación, linting o tipos si corresponde.
- No ejecutar toda la suite automáticamente por cambios triviales cuando una verificación localizada sea suficiente.
- No repetir verificaciones exitosas sin cambios posteriores relevantes.
- Ante fallos, investigar la causa antes de relanzar.
- Distinguir errores introducidos por el cambio de problemas preexistentes.
- No modificar tests para ocultar errores.
- No afirmar que algo fue verificado si no se ejecutó la comprobación.

Al finalizar, resumir qué verificaciones se realizaron y cuáles no pudieron ejecutarse.

## 8. Seguridad y permisos

- No mostrar, copiar ni registrar secretos, tokens, contraseñas o credenciales.
- No modificar archivos de credenciales salvo solicitud explícita.
- No ejecutar operaciones destructivas sin autorización adecuada.
- No realizar deploys, publicaciones, pushes ni cambios en servicios externos sin autorización para esa operación.
- No enviar información a terceros sin solicitud explícita.
- Respetar los permisos y restricciones del entorno.
- Evitar comandos que puedan eliminar trabajo no relacionado.
- Antes de ejecutar operaciones potencialmente costosas, estimar su impacto cuando sea posible.
- No dividir operaciones para eludir límites de costos o permisos.

Las operaciones locales reversibles necesarias para completar una tarea autorizada pueden realizarse normalmente.

## 9. Dependencias y documentación

- Consultar primero la documentación y configuración existente del proyecto.
- No buscar documentación externa cuando la información local sea suficiente.
- Consultar fuentes externas cuando existan dudas sobre APIs, versiones o comportamientos específicos.
- Preferir documentación oficial y compatible con las versiones instaladas.
- No actualizar dependencias por rutina.
- No generar documentación extensa salvo que se solicite o sea necesaria para mantener el proyecto.
- Actualizar documentación existente cuando el cambio la deje incorrecta.

## 10. Git y control de cambios

- Inspeccionar el estado del repositorio antes de modificar archivos cuando sea relevante.
- Mantener cambios enfocados en el objetivo.
- No incluir archivos temporales, logs, credenciales ni artefactos innecesarios.
- No crear commits, ramas ni realizar pushes salvo solicitud explícita o autorización vigente.
- No utilizar comandos destructivos de Git para resolver conflictos sin autorización.
- Revisar el diff antes de finalizar.
- Respetar los cambios preexistentes del usuario.

## 11. Finalización de tareas

Al terminar, entregar un resumen breve que incluya:

1. Resultado: qué se implementó o resolvió.
2. Archivos: cuáles se modificaron, si corresponde.
3. Verificación: tests o comprobaciones realizadas.
4. Pendientes: limitaciones, riesgos o pasos necesarios.

Omitir secciones que no aporten información.

No repetir el contenido completo de archivos modificados cuando el usuario pueda consultarlos directamente.

## 12. Prioridad de instrucciones

- Seguir las instrucciones explícitas del usuario y las reglas aplicables del entorno.
- Respetar las convenciones y documentación específicas del repositorio.
- Aplicar estas reglas como preferencias generales de trabajo, sin reemplazar requisitos más específicos.
- Ante conflictos, respetar las instrucciones de mayor prioridad y los límites de seguridad.

Regla final: trabajar con precisión, utilizar solo el contexto necesario, minimizar operaciones redundantes y entregar resultados verificables.
