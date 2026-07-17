# Visual checklist — antes de mergear una vista nueva

Checklist corto para pasar antes de dar por cerrada una vista nueva o rediseñada. No reemplaza
`COLOR_SYSTEM.md`/`FRONTEND_BEST_PRACTICES.md` — es el resumen accionable de 2 minutos que se
corre al final, referenciando los patrones concretos que ya usa el resto de TPW.

## Color y tokens

- [ ] Cero hex/rgba hardcodeado fuera de `masterpage.html` (`:root`). Todo lo demás usa
      `--tp-color-*`.
- [ ] Todo token referenciado existe de verdad (`grep` rápido del nombre en `masterpage.html`
      antes de usarlo — varias rondas de auditoría de este proyecto encontraron tokens
      referenciados que directamente no estaban definidos).
- [ ] Un acento dominante por vista. Colores semánticos (success/warning/danger) solo cuando
      agregan significado real, no como decoración.

## Profundidad y motion

- [ ] Paneles/cards usan `--tp-shadow-xs/sm/md/lg`, no un `box-shadow` inventado.
- [ ] Contenedores estáticos (cards de contenido) llevan sombra por **borde**, no por
      `box-shadow` — las sombras `box-shadow` quedan para elementos flotantes/overlay
      (tooltips, drawers, dropdowns).
- [ ] Entrada sutil en vistas nuevas: reusar `.tp-ui-enter` (`ui-system.css`) salvo que el
      elemento ya tenga un `transform` propio (ej. algo centrado con `translateX(-50%)`) — en
      ese caso escribir un keyframe local que preserve ese transform en el estado final, no
      `transform: none`. Ver `structure-fullscreen.css` para el patrón ya resuelto de esto.
- [ ] **Verificar que ningún keyframe de entrada termine en un `transform` no-`none` con
      `animation-fill-mode: both`** salvo que sea necesario (como el caso de arriba) — un
      transform persistente en cualquier ancestro rompe el posicionamiento de un `<select>`
      nativo en Chromium. Bug real ya encontrado y corregido una vez en este proyecto.
- [ ] Hover-lift solo en elementos interactivos (botones, chips, links de acción), no en
      contenedores estáticos.

## Tipografía de datos

- [ ] IDs, accessions, scores, coordenadas, EC/GO numbers: tipografía monoespaciada tabular
      (`JetBrains Mono`, ya usada en el resto de la app), no la fuente de cuerpo.
- [ ] Jerarquía clara entre evidencia directa/fuerte vs. transferida/débil cuando ambas
      aparecen juntas (tamaño/peso/color, no solo el número).

## Motion y accesibilidad

- [ ] Toda animación de entrada respeta `prefers-reduced-motion: reduce`.
- [ ] Foco visible en todo elemento interactivo (`:focus-visible`), nunca `outline: none` sin
      reemplazo.

## Antes de dar por cerrado

- [ ] Cache-buster (`?v=...`) bumpeado en cada template que referencia el CSS/JS tocado.
- [ ] Revisado en claro **y** oscuro — no asumir que un token se ve bien en los dos solo porque
      compila.
- [ ] Si la vista es una superficie interactiva de mayor riesgo (visualizador 3D, canvas,
      cualquier cosa con su propio ciclo de vida JS), probado en un navegador real, no solo
      revisado en código — varios bugs de este tipo en TPW (NGL, Cytoscape) no eran visibles
      leyendo el diff.
