# Color Palette Guide (TPWeb)

> Versión integrada en documentación técnica: `docs/COLOR_SYSTEM.md`

## Objetivo
Este documento define el sistema de color de TPWeb para mantener consistencia visual y evitar hex sueltos en templates.

## Regla principal
- En componentes y vistas: usar solo variables semánticas `--tp-color-*` (o alias `--tp-*` existentes).
- Hex directos: permitidos únicamente en la definición central de tokens en [`tpweb/templates/base/masterpage.html`](./tpweb/templates/base/masterpage.html).

## Paleta semántica (núcleo)
### Texto
- `--tp-color-text-primary`: texto principal
- `--tp-color-text-secondary`: texto secundario
- `--tp-color-text-muted`: texto de apoyo
- `--tp-color-text-soft`: texto suave/disabled

### Marca
- `--tp-color-brand-900`: marca profunda (hover/active)
- `--tp-color-brand-800`: marca base principal
- `--tp-color-brand-700`: marca alta para gradientes
- `--tp-color-brand-600`: marca brillante puntual
- `--tp-color-brand-300/200/100/050`: bordes, fondos suaves y acentos ligeros

### Superficies (máximo razonable)
- `--tp-color-surface`: superficie base (blanco)
- `--tp-color-surface-soft`: superficie suave
- `--tp-color-surface-muted`: superficie tenue
- `--tp-color-surface-panel`: panel técnico
- `--tp-color-surface-alt`: variante alternativa

### Bordes
- `--tp-color-border`: borde estándar
- `--tp-color-border-soft`: borde liviano
- `--tp-color-border-strong`: borde fuerte
- `--tp-color-border-accent`: borde con acento de marca

### Estados
- `--tp-color-success-*`: éxito/en proceso
- `--tp-color-info-*`: información/finalizado
- `--tp-color-idle-*`: inactivo
- `--tp-color-warning-*`: advertencia
- `--tp-color-danger-*`: error/acción destructiva

### Navegación
- `--tp-color-nav-900/800/700`: sidebar/topbar

## Alias legacy (compatibilidad)
Se mantienen alias en `:root` para no romper estilos existentes:
- `--tp-ink`, `--tp-muted`, `--tp-accent`, `--tp-border`, `--tp-surface`, `--tp-state-*`, etc.

Los alias no deben crecer. Todo nuevo color debe entrar como `--tp-color-*`.

## Guía de uso rápido
- CTA principal: `--tp-color-brand-800` + hover `--tp-color-brand-900`
- Fondos de tarjeta/panel: usar `--tp-color-surface*`
- Bordes default: `--tp-color-border` o `--tp-color-border-soft`
- Chips de estado: `--tp-color-success-*`, `--tp-color-info-*`, `--tp-color-idle-*`
- Links: `--tp-color-link` + `--tp-color-link-hover`

## Anti-patrones
- No usar colores por hexadecimal en templates o JS inline de vistas.
- No crear tokens por valor (`--tp-col-xxxxxx`).
- No duplicar variantes mínimas de blanco/gris sin necesidad.

## Checklist para PRs de UI
- ¿Todo color nuevo está nombrado semánticamente?
- ¿Se reutiliza un token existente antes de crear uno nuevo?
- ¿Se respetan las superficies definidas (sin sumar “otro blanco más”)?
- ¿No hay hex sueltos fuera de `:root`?
