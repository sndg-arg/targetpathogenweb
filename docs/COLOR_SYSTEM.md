# Color System (TPWeb)

## Objetivo

Definir un sistema de color consistente, semántico y mantenible para toda la UI de TPWeb.

## Regla principal

- En componentes y vistas usar solo variables semánticas: `--tp-color-*`.
- Los hex directos se permiten únicamente en la definición central de tokens en `masterpage.html`.

## Tokens semánticos

### Texto

- `--tp-color-text-primary`
- `--tp-color-text-secondary`
- `--tp-color-text-muted`
- `--tp-color-text-soft`

### Marca

- `--tp-color-brand-900`
- `--tp-color-brand-800`
- `--tp-color-brand-700`
- `--tp-color-brand-600`
- `--tp-color-brand-300`
- `--tp-color-brand-200`
- `--tp-color-brand-100`
- `--tp-color-brand-050`

### Superficies

- `--tp-color-surface`
- `--tp-color-surface-soft`
- `--tp-color-surface-muted`
- `--tp-color-surface-panel`
- `--tp-color-surface-alt`

### Bordes

- `--tp-color-border`
- `--tp-color-border-soft`
- `--tp-color-border-strong`
- `--tp-color-border-accent`

### Estados

- `--tp-color-success-*`
- `--tp-color-info-*`
- `--tp-color-idle-*`
- `--tp-color-warning-*`
- `--tp-color-danger-*`

### Navegación

- `--tp-color-nav-900`
- `--tp-color-nav-800`
- `--tp-color-nav-700`

## Alias legacy

Se permiten alias existentes (`--tp-accent`, `--tp-border`, etc.) solo por compatibilidad.  
Todo color nuevo debe entrar como `--tp-color-*`.

## Guía de uso

- CTA primario: `--tp-color-brand-800` (hover `--tp-color-brand-900`)
- Links: `--tp-color-link` (hover `--tp-color-link-hover`)
- Fondos de panel/tarjeta: `--tp-color-surface*`
- Bordes estándar: `--tp-color-border` o `--tp-color-border-soft`
- Chips de estado: usar exclusivamente tokens de estado

## Anti-patrones

- Hex sueltos en templates o JS inline.
- Tokens por implementación (ejemplo: `--tp-col-0e5266`).
- Multiplicar tonos casi iguales de blanco/gris sin justificación.

## Checklist de PR UI

- ¿No hay hex sueltos fuera del archivo de tokens central?
- ¿Se reusó un token existente antes de crear uno nuevo?
- ¿El nombre del token describe intención y no implementación?
- ¿Se mantiene una cantidad razonable de superficies neutras?
