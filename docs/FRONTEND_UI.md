# Frontend and UI Guide

This document centralizes frontend build procedures and UI standards.

## 1. Scope

Use this guide for:

- Building `static/bundle.js` from `js/`
- Running JBrowse commands from `js/jbrowse/`
- Applying semantic color rules
- Applying UX conventions for scientific workflows

## 2. Build Frontend Bundle (`static/bundle.js`)

Run from `targetpathogenweb/js`.

### Build image

```bash
docker build -t tpweb-webpack .
```

Creates reproducible Node/Webpack environment.

### Install dependencies

```bash
docker run --rm -w "$PWD" -v "$PWD:$PWD" tpweb-webpack bash -lc 'npm install'
```

### Apply known upstream compatibility patches

```bash
docker run --rm -w "$PWD" -v "$PWD:$PWD" tpweb-webpack bash -lc '
  sed -i "s|require(\"bootstrap/js/tooltip.js\")|require(\"bootstrap/js/dist/tooltip.js\")|" ./node_modules/feature-viewer/lib/index.js
  sed -i "s|require(\"bootstrap/js/popover.js\")|require(\"bootstrap/js/dist/popover.js\")|" ./node_modules/feature-viewer/lib/index.js
  sed -i "s|// FIX scrollbars on Mac||" ./node_modules/msa/css/msa.css
'
```

### Build bundle

```bash
docker run --rm -w "$PWD" -v "$PWD:$PWD" tpweb-webpack bash -lc 'npm run build'
```

### Copy output to Django static

```bash
cp bundle.js ../static/bundle.js
```

### Optional ownership fix

```bash
sudo chown -R "$(id -u):$(id -g)" .npm node_modules bundle.js
```

Only if files become non-writable after container runs.

## 3. JBrowse Commands

Run from `targetpathogenweb/js/jbrowse`.

### Build image

```bash
docker build -t jbrowse .
```

### Serve UI locally

```bash
docker run -v $PWD/data:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD \
  --name jbrowse -p 3000:3000 -it jbrowse npx serve .
```

### Add assembly

```bash
docker run -v $PWD/data:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD \
  jbrowse jbrowse add-assembly data/NC_003047.genome.fna.bgz --load copy --out data/jbrowse/NC_003047/ --type bgzipFasta
```

### Add track

```bash
docker run -v $PWD/data:/jbrowse2/data --rm -u $(id -u ${USER}):$(id -g ${USER}) -v $PWD:$PWD \
  jbrowse jbrowse add-track data/NC_003047.gff.bgz --load copy --out data/jbrowse/NC_003047/
```

## 4. Color System Rules

### Primary rule

- Use semantic variables (`--tp-color-*`) in templates/components
- Direct hex values are allowed only in `tpweb/templates/base/masterpage.html`

### Token families

- Text: `--tp-color-text-*`
- Brand: `--tp-color-brand-*`
- Surfaces: `--tp-color-surface*`
- Borders: `--tp-color-border*`
- States: `--tp-color-success-*`, `--tp-color-info-*`, `--tp-color-idle-*`, `--tp-color-warning-*`, `--tp-color-danger-*`
- Navigation: `--tp-color-nav-*`

### Practical usage

- Primary CTA: `--tp-color-brand-800` (hover `--tp-color-brand-900`)
- Links: `--tp-color-link` / `--tp-color-link-hover`
- Panels/cards: surface + border semantic tokens
- Status chips: state token families only

### Anti-patterns

- Direct hex in templates, inline CSS, or page-level JS
- Implementation-style token names
- Unnecessary near-duplicate neutral colors

## 5. UX Rules for Bioinformatics Screens

- Show pipeline status in context (global + entity-level)
- Make primary scientific facts immediately scannable
- Keep one dominant action per section
- Always include loading, empty, and error states
- Failure messages should include a recovery action when possible
- Keep key identifiers (accession, organism, run) visible without extra clicks

## 6. Frontend Validation Checklist

After frontend changes:

- Protein detail loads feature viewer and 3D controls
- Filters and formula modals work correctly
- Browser hard refresh confirms updated assets
- New UI follows semantic token rules
- New screen works on desktop and mobile

## 7. Related

- Root setup: [../README.md](../README.md)
- Operations: [./OPERATIONS.md](./OPERATIONS.md)
- Engineering standards: [./ENGINEERING.md](./ENGINEERING.md)
