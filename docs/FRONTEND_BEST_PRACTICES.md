# Buenas prácticas en el desarrollo de interfaces web

## Introducción

El desarrollo frontend tiene una barrera de entrada baja: con HTML, CSS y algo de JavaScript alcanza para mostrar algo en pantalla. Sin embargo, la diferencia entre un proyecto que escala bien y uno que se convierte en un caos de parches y excepciones no está en el lenguaje ni en el framework. Está en las decisiones de estructura que se toman —o no se toman— desde el principio.

Este documento recorre los pilares que permiten construir interfaces mantenibles, coherentes y accesibles, independientemente del stack tecnológico que se use.

---

## 1. Design Tokens

### ¿Qué son?

Un design token es una variable con nombre semántico que representa una decisión de diseño. En lugar de escribir valores crudos dispersos por el código, se definen una sola vez y se referencian en todos lados.

### ¿Por qué importan?

Cuando los valores viven directo en los estilos, cambiar el color principal de una aplicación implica buscar y reemplazar en cientos de archivos. Cuando viven en tokens, es un cambio en un solo lugar. Además, los tokens son el puente entre diseño y código: si el diseñador y el desarrollador hablan de `color-brand-500`, están hablando de lo mismo.

### Familias esenciales

- **Color**: marca, texto, superficies, estados semánticos
- **Tipografía**: familias, tamaños, pesos, interlineado
- **Espaciado**: escala fija de separaciones y márgenes
- **Bordes**: radios y grosores
- **Sombras**: elevaciones de capas

### Ejemplo

```css
/* ❌ Sin tokens */
.boton {
    background: #1a3c5e;
    font-size: 13px;
    border-radius: 6px;
    padding: 7px 11px;
}

/* ✅ Con tokens */
.boton {
    background: var(--color-brand-800);
    font-size: var(--font-size-sm);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
}
```

### Regla de oro

El único lugar donde aparecen valores crudos (`#1a3c5e`, `13px`, `6px`) es donde se definen los tokens. En ningún otro lado del código.

---

## 2. Sistema de color

### El problema de improvisar

Cuando los colores se eligen componente por componente, el resultado es una paleta accidental: docenas de tonos levemente distintos sin relación entre sí. El producto se ve inconsistente aunque cada pieza suelta "se vea bien".

### Estructura recomendada

Una paleta bien construida tiene:

- **1 familia de marca**: entre 7 y 9 tonos (del más claro al más oscuro)
- **1 familia de neutros**: grises para texto, fondos y bordes
- **4 familias semánticas**: éxito, advertencia, peligro, información

### ¿Por qué múltiples tonos por familia?

Porque un solo color no alcanza para todos los usos. Se necesitan tonos distintos para: fondos sutiles, bordes, iconos, texto sobre fondo claro, texto sobre fondo oscuro, estados hover, estados activos.

Una forma de pensarlo:

| Rango de tono | Uso típico |
|---------------|------------|
| 50 – 100 | Fondos suaves, badges, chips |
| 200 – 300 | Bordes, separadores |
| 400 – 500 | Iconos, elementos decorativos |
| 600 – 700 | Texto sobre fondo claro |
| 800 – 900 | Texto prominente, headings con acento |

### Lo que no funciona

Nombrar colores por su apariencia en lugar de su rol:

```css
/* ❌ */
--azul-claro: #dbeafe;
--azul-medio: #3b82f6;
--azul-oscuro: #1e3a5f;

/* ✅ */
--color-brand-100: #dbeafe;
--color-brand-500: #3b82f6;
--color-brand-900: #1e3a5f;
```

La primera versión no dice nada sobre cuándo usar cada color. La segunda permite definir reglas: los fondos usan tonos 50–100, los bordes usan 200–300, el texto usa 700–900.

### Colores semánticos vs. colores de marca

Una confusión común es usar el color de marca donde debería ir un color semántico.

```css
/* ❌ El rojo de error no es "tu" rojo, es el rojo del sistema */
.error { color: var(--color-brand-700); }

/* ✅ */
.error { color: var(--color-danger-700); }
```

El color de marca comunica identidad. El color semántico comunica significado. Mezclarlos confunde al usuario.

---

## 3. Tipografía como sistema

### Más que elegir una fuente

La tipografía no es solo qué fuente usar. Es la jerarquía completa: qué tamaños existen, qué pesos, cuándo se usa cada combinación, y cómo se comportan en distintos contextos.

### La escala tipográfica

Al igual que con el espaciado, los tamaños de texto deben seguir una escala fija:

```css
--font-size-xs:   0.75rem;   /* 12px — labels, metadata */
--font-size-sm:   0.875rem;  /* 14px — texto secundario */
--font-size-base: 1rem;      /* 16px — cuerpo principal */
--font-size-md:   1.125rem;  /* 18px — texto destacado */
--font-size-lg:   1.25rem;   /* 20px — subtítulos */
--font-size-xl:   1.5rem;    /* 24px — títulos de sección */
--font-size-2xl:  2rem;      /* 32px — títulos de página */
```

No hace falta usar todos. Hace falta no inventar valores fuera de la escala.

### Pesos con propósito

```
400 (regular)  → cuerpo de texto, párrafos
500 (medium)   → labels, metadatos que necesitan algo más de presencia
600 (semibold) → títulos de sección, valores importantes
700 (bold)     → títulos principales, énfasis real
```

Si todo está en 700, nada está enfatizado. El peso funciona por contraste.

### Line-height y legibilidad

El cuerpo de texto necesita espacio para respirar:

```css
/* ❌ Muy apretado */
p { line-height: 1.2; }

/* ✅ Legible */
p { line-height: 1.6; }

/* Los headings pueden ir más ajustados porque son pocas palabras */
h1, h2 { line-height: 1.15; }
```

### Máximo dos familias

Una para títulos (suele ser una sans-serif con personalidad), una para cuerpo (optimizada para lectura continua). Más de dos familias en el mismo proyecto rara vez suma; casi siempre distrae.

---

## 4. Jerarquía visual

### El principio

Cada pantalla tiene una pregunta implícita: **¿qué es lo más importante acá?** La jerarquía visual es la respuesta. Guía la atención del usuario sin que tenga que pensar.

### Las tres herramientas principales

**Tamaño**: lo más grande llama más la atención. Parece obvio, pero muchos diseños tienen todo del mismo tamaño y se sienten planos.

**Peso y contraste**: texto oscuro sobre fondo claro tiene más peso visual que texto gris. Un elemento con color sobre un fondo neutro llama la atención sin necesitar ser grande.

**Espacio**: un elemento con más espacio alrededor tiene más protagonismo. El espacio en blanco no es "espacio vacío", es peso visual.

### La regla de un solo protagonista

Cada sección de pantalla debería tener un elemento dominante. Si todo compite, nada gana. Si hay dos botones igual de grandes e igual de coloridos juntos, el usuario no sabe qué hacer.

```html
<!-- ❌ Dos acciones iguales en peso visual -->
<button class="btn btn--primary">Guardar</button>
<button class="btn btn--primary">Cancelar</button>

<!-- ✅ Jerarquía clara: una acción principal, una secundaria -->
<button class="btn btn--primary">Guardar</button>
<button class="btn btn--secondary">Cancelar</button>
```

### Texto: tres niveles alcanzan

- **Primario**: el contenido principal. Color de texto normal, peso regular o medium.
- **Secundario**: contexto de apoyo. Un poco más claro, un poco más chico.
- **Terciario / muted**: metadatos, timestamps, hints. Claramente subordinado.

Más niveles que eso generan ruido en lugar de orden.

---

## 5. Componentes y variantes

### Qué es un componente

Un componente es una unidad de interfaz reutilizable: un botón, una tarjeta, un campo de formulario, un badge. Lo que lo hace valioso no es que se pueda reusar, sino que encapsula todas sus variantes y estados en un solo lugar.

### Variantes

Las variantes representan las distintas versiones semánticas de un componente. Un botón puede ser primario, secundario o de peligro. Esas variantes se declaran explícitamente, no se improvisan con clases adicionales.

```html
<!-- ✅ Variantes declaradas -->
<button class="btn btn--primary">Guardar</button>
<button class="btn btn--secondary">Cancelar</button>
<button class="btn btn--danger">Eliminar</button>
```

### Estados

Todo componente interactivo tiene estados. Diseñarlos desde el principio evita que aparezcan inventados en el momento en que se necesitan.

| Estado | Descripción |
|--------|-------------|
| Default | Estado de reposo |
| Hover | El cursor está encima |
| Focus | Seleccionado por teclado |
| Active | Siendo presionado |
| Disabled | No disponible para interacción |
| Loading | Esperando una respuesta |
| Error | Algo salió mal |

Los más olvidados son **loading** y el **estado vacío** (cuando no hay datos que mostrar). Son exactamente los que el usuario más necesita ver.

### Nombres semánticos

Los nombres de componentes y variantes deben describir qué son, no cómo se ven.

```
❌  .boton-rojo-grande       →    ✅  .btn--danger
❌  .texto-gris-chico        →    ✅  .label--muted
❌  .caja-borde-redondeado   →    ✅  .card
```

Cuando el diseño cambia, los nombres semánticos siguen teniendo sentido. Los nombres visuales mienten.

---

## 6. Espaciado consistente

### El problema invisible

La mayoría de las interfaces que "se ven raro" no tienen un problema de color ni de tipografía. Tienen espaciado inconsistente: márgenes que se inventan en cada componente, sin relación entre sí.

### La solución: una escala fija

Se define una progresión de valores y solo esos valores existen en el proyecto:

```
4px → 8px → 12px → 16px → 24px → 32px → 48px → 64px
```

Si un espaciado no está en la escala, no se usa. `margin: 7px` o `padding: 11px` son señales de que algo se está improvisando.

### La regla de proximidad

Elementos relacionados entre sí usan poco espacio. Grupos distintos usan más. Esta regla, combinada con una escala fija, genera layouts que se ven ordenados sin necesidad de ajuste fino.

### Espaciado interno vs. externo

Una distinción útil:

- `padding` define el espacio interno de un componente (entre el borde y el contenido)
- `margin` o `gap` define el espacio entre componentes

Mezclarlos para compensar hace que los componentes dependan de su contexto, lo que dificulta reutilizarlos en otro lugar.

---

## 7. Estados y datos

### El camino feliz no es suficiente

La mayoría de las interfaces se diseñan para el caso ideal: datos cargados, sin errores, usuario logueado, todo funciona. Pero los usuarios viven en los bordes.

### Los estados que hay que diseñar siempre

**Vacío**: ¿qué ve el usuario cuando no hay datos todavía? Una tabla vacía sin mensaje es confusa. Un mensaje claro ("Todavía no tenés elementos. Creá uno acá.") es útil.

**Loading**: mientras se espera una respuesta, el usuario necesita saber que algo está pasando. Un spinner, un skeleton screen, o incluso deshabilitar el botón que disparó la acción.

**Error**: ¿qué pasó? ¿Qué puede hacer el usuario ahora? "Error" a secas no ayuda. "No se pudo guardar. Revisá tu conexión e intentá de nuevo." sí.

**Parcial**: a veces los datos existen pero están incompletos. Un campo que falta, un resultado sin imagen, un nombre sin apellido. El componente tiene que poder renderizar sin explotar.

### Los mensajes de error son parte del diseño

Un mensaje de error es una oportunidad de comunicar con claridad. No tiene que ser técnico ni alarmante. Tiene que decirle al usuario qué pasó y qué hacer.

```
❌  Error 500
❌  Something went wrong
✅  No se pudo enviar el formulario. Revisá que todos los campos estén completos.
```

---

## 8. Accesibilidad

### Por qué es el piso mínimo

La accesibilidad no es una feature avanzada ni un requerimiento especial. Es lo que separa una interfaz que funciona de una que funciona solo para una parte de los usuarios.

### Contraste de color

El texto debe tener contraste suficiente contra su fondo para ser legible por personas con baja visión o daltonismo. Pero también para cualquiera con la pantalla a pleno sol, o cansancio al final del día.

- Texto normal (menos de 18px): mínimo **4.5:1**
- Texto grande (18px o más) o negrita: mínimo **3:1**

Herramienta para verificarlo: [coolors.co/contrast-checker](https://coolors.co/contrast-checker)

### Foco visible

Cuando un usuario navega con teclado (o tecnología asistiva), necesita saber qué elemento está seleccionado. Remover el indicador de foco es uno de los errores más comunes y más dañinos.

```css
/* ❌ Muy común, muy incorrecto */
:focus {
    outline: none;
}

/* ✅ Foco visible y controlado */
:focus-visible {
    outline: 2px solid var(--color-brand-500);
    outline-offset: 2px;
}
```

### HTML semántico

Los elementos HTML tienen significado. Usar el elemento correcto no es solo una cuestión de buenas prácticas: define el comportamiento accesible automáticamente.

```html
<!-- ❌ Funciona visualmente, falla en todo lo demás -->
<div onclick="enviar()">Enviar</div>

<!-- ✅ Focuseable por teclado, activable con Enter/Space,
        anunciado como botón por lectores de pantalla -->
<button type="submit">Enviar</button>
```

Otros elementos semánticos importantes: `<nav>` para navegación, `<main>` para el contenido principal, `<header>` y `<footer>`, `<label>` asociado a cada campo de formulario.

### Texto alternativo en imágenes

Toda imagen que comunica información necesita un `alt` descriptivo. Las imágenes decorativas llevan `alt=""` para que el lector de pantalla las ignore.

```html
<!-- ❌ -->
<img src="grafico-ventas.png">

<!-- ✅ -->
<img src="grafico-ventas.png" alt="Gráfico de ventas mensuales: crecimiento del 40% en el último trimestre">

<!-- Imagen decorativa -->
<img src="fondo-patron.svg" alt="">
```

---

## 9. Mobile-first

### El error habitual

Diseñar el layout de escritorio completo y luego intentar adaptarlo a pantallas chicas. El resultado casi siempre son parches: elementos que se ocultan, textos que se achican, columnas que colapsan mal.

### El enfoque correcto

Empezar desde el viewport más pequeño y expandir hacia pantallas más grandes. Un layout simple es más fácil de expandir que un layout complejo de achicar.

```css
/* Base: mobile */
.contenedor {
    display: block;
    padding: 16px;
}

/* A partir de 768px: tablet/desktop */
@media (min-width: 768px) {
    .contenedor {
        display: grid;
        grid-template-columns: 1fr 2fr;
        padding: 32px;
    }
}
```

### La pregunta de arranque

Antes de diseñar cualquier sección: ¿cómo se ve esto en un teléfono? La respuesta a esa pregunta define la estructura. El resto es expansión.

### Tamaños de toque

En mobile, los elementos interactivos necesitan un área de toque mínima de 44×44px, independientemente de su tamaño visual. Un ícono de 16px que no tiene padding es imposible de presionar con precisión.

---

## 10. Separación de responsabilidades

### El principio

El HTML describe **qué es** algo. El CSS describe **cómo se ve**. El JavaScript describe **cómo se comporta**. Cuando estas responsabilidades se mezclan, el código se vuelve frágil: un cambio visual requiere tocar el HTML, un cambio de comportamiento rompe los estilos.

### Señales de que algo está mal

- Estilos inline en el HTML: `style="color: red; font-size: 14px"`
- Clases que describen apariencia: `.rojo`, `.negrita`, `.centrado`
- JavaScript que escribe CSS directamente en lugar de agregar/sacar clases

### Señales de que está bien

- Se puede cambiar el diseño tocando solo el CSS
- Se puede leer el HTML y entender la estructura sin ver el resultado visual
- Los nombres de clases describen propósito, no apariencia

### JavaScript y clases

El JS debería cambiar el estado de la interfaz agregando o removiendo clases, no escribiendo estilos directamente:

```javascript
// ❌
elemento.style.display = 'none';
elemento.style.color = 'red';

// ✅
elemento.classList.add('is-hidden');
elemento.classList.add('has-error');
```

Las clases de estado usan convenciones como `is-` o `has-` para distinguirlas de las clases estructurales.

---

## 11. Rendimiento percibido

### Qué mide el usuario (sin saberlo)

El usuario no mide el tiempo de carga. Mide cuánto tarda en poder hacer lo que vino a hacer. Esas dos cosas no son lo mismo.

Una página que muestra contenido útil en 1 segundo y termina de cargar en 3 se siente rápida. Una que tarda 1 segundo pero muestra una pantalla en blanco hasta que todo está listo se siente lenta.

### Estrategias básicas

**Mostrar algo antes**: mientras carga el contenido real, mostrar la estructura (skeleton screens) es mejor que un spinner genérico. El usuario siente que la página está "casi lista".

**Imágenes con tamaño correcto**: no servir una imagen de 2000px donde se va a mostrar a 400px. Es el problema de rendimiento más común y el más fácil de resolver.

**Lazy loading**: las imágenes fuera del viewport inicial no necesitan cargarse hasta que el usuario llega a ellas.

```html
<img src="foto.jpg" loading="lazy" alt="...">
```

**Fuentes**: cargarlas con `font-display: swap` para que el texto sea legible mientras la fuente carga, en lugar de quedarse en blanco.

```css
@font-face {
    font-family: 'MiFuente';
    src: url('mifuente.woff2') format('woff2');
    font-display: swap;
}
```

### Animaciones sin costo

Las propiedades que el browser puede animar sin recalcular el layout son `transform` y `opacity`. Animar `width`, `height`, `top`, `left` o `margin` es costoso y genera animaciones cortadas.

```css
/* ❌ Costoso */
.menu { transition: height 0.3s; }

/* ✅ Sin costo */
.menu { transition: transform 0.3s, opacity 0.3s; }
```

---

## 12. Consistencia como objetivo

### El problema de la libertad sin sistema

Cuando cada desarrollador construye sus propios componentes, cuando no hay documentación de qué existe, cuando cada "caso especial" genera una excepción nueva, el proyecto acumula deuda visual. No se ve mal en ninguna pantalla en particular. Se ve inconsistente en todas.

### Lo que genera consistencia

- Un sistema de componentes documentado y accesible para todo el equipo
- La pregunta obligatoria antes de crear algo nuevo: *¿esto ya existe?*
- Revisiones de código que incluyan el CSS, no solo la lógica
- Tokens que impiden que los valores arbitrarios entren al codebase

### Menos es más

Cada excepción al sistema tiene un costo. No solo en código: en la percepción del usuario. Una interfaz que tiene quince variantes de card, cuatro tamaños de botón distintos y seis colores de texto diferentes se siente caótica aunque ningún elemento individual esté "mal".

Antes de agregar una variante nueva, la pregunta es: ¿puede resolverse con las variantes que ya existen?

### El objetivo final

Una interfaz bien construida se siente invisible. El usuario no debería notar la UI: debería notar lo que la aplicación hace. Cuando algo llama la atención por ser inconsistente, roto, o confuso, la interfaz está fallando en su trabajo.

> *Un buen front end no impresiona a la primera vista. Se nota cuando algo sale mal — y no sale nada mal.*

---

## Conclusión

Ninguno de estos puntos es complicado por sí solo. Lo difícil es aplicarlos desde el principio y mantenerlos a lo largo del tiempo, especialmente bajo presión. La buena noticia es que cada uno de ellos reduce trabajo a futuro: menos bugs visuales, menos inconsistencias, menos tiempo explicando por qué algo "se ve raro". El esfuerzo inicial de estructurar bien se recupera rápido.

El frontend es la única parte del sistema que el usuario toca directamente. Todo lo demás puede fallar en silencio. El front falla en la cara.
