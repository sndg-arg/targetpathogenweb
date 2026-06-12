# Buenas prácticas en el desarrollo de interfaces web

## Introducción

El desarrollo frontend tiene una barrera de entrada baja: con HTML, CSS y algo de JavaScript alcanza para mostrar algo en pantalla. La dificultad no está en hacer que algo funcione — está en hacer que sea fácil de usar, fácil de mantener, y coherente a lo largo del tiempo.

Este documento tiene dos ejes. El primero es **usabilidad**: cómo tomar decisiones de interacción que no frustren al usuario. El segundo es **estructura**: cómo organizar el código visual para que el proyecto no se convierta en un caos a medida que crece. Los dos están conectados: una interfaz bien estructurada es más fácil de usar, y una interfaz pensada para el usuario termina siendo más fácil de mantener.

---

## Parte 1: Usabilidad

---

### 1. La interfaz existe para que el usuario haga cosas

El error más común en frontend no es técnico. Es de perspectiva: construir la interfaz desde adentro hacia afuera (lo que es fácil de implementar) en lugar de desde afuera hacia adentro (lo que el usuario necesita hacer).

Antes de construir cualquier cosa, la pregunta es: **¿qué vino a hacer el usuario acá?** Todo lo demás — colores, animaciones, componentes — es secundario a esa respuesta.

Una interfaz que se ve hermosa pero requiere diez clicks para hacer algo simple está fallando en su trabajo. Una interfaz sin gracia que le permite al usuario terminar su tarea en dos clicks está haciendo bien su trabajo.

---

### 2. Reducir la fricción

Fricción es todo lo que pone distancia entre el usuario y lo que quiere hacer. Algunos ejemplos:

- Pedir información que no es necesaria en ese momento
- Forzar confirmaciones para acciones de bajo riesgo
- Mostrar opciones que no aplican al contexto actual
- Obligar al usuario a recordar información de una pantalla anterior para usarla en la siguiente
- Hacer que una acción frecuente requiera muchos pasos

**La regla de los dos clicks**: si una acción es frecuente, debería poder hacerse en no más de dos pasos. Si requiere más, hay que preguntarse si el flujo está bien diseñado o si se puede acercar la acción al contexto donde el usuario la necesita.

---

### 3. Modales, drawers y páginas nuevas: cuándo usar cada uno

Esta es una de las decisiones más importantes y más malentendidas del frontend. No es una cuestión de preferencia: cada patrón existe para un caso específico.

#### Modal

Interrumpe el flujo actual para pedir atención inmediata. Bloquea el resto de la pantalla.

**Usarlo cuando:**
- Se necesita una confirmación antes de una acción destructiva ("¿Estás seguro de que querés eliminar esto?")
- Se necesita completar un formulario corto sin abandonar el contexto actual (crear un tag, editar un nombre)
- La acción es puntual y el usuario debe volver al punto donde estaba después

**No usarlo cuando:**
- El formulario tiene más de 4 o 5 campos
- El usuario necesita ver el contenido de fondo mientras completa el modal
- La acción es parte de un flujo más largo
- La pantalla es mobile (los modales en mobile casi siempre son una mala experiencia)

```
❌  Modal con 15 campos para crear un perfil completo
✅  Modal con 2 campos para renombrar un archivo
```

#### Drawer (panel lateral deslizante)

Aparece desde el costado sin salir de la pantalla actual. Permite contexto adicional sin interrumpir del todo.

**Usarlo cuando:**
- Se necesita mostrar detalle de un elemento de una lista sin perder la lista de vista
- Hay un panel de configuración o filtros que el usuario va a abrir y cerrar frecuentemente
- El contenido secundario es extenso pero no justifica una página nueva
- Se quiere mantener el contexto de lo que el usuario estaba mirando

**No usarlo cuando:**
- La tarea dentro del drawer es larga y compleja (se convierte en una mini-app dentro de la página)
- El contenido necesita toda la pantalla para ser usable
- En mobile con contenido muy largo (el drawer ocupa toda la pantalla de todas formas, entonces mejor ir a una página)

```
✅  Drawer de filtros en un listado — el usuario filtra y ve los resultados actualizarse
✅  Drawer con el detalle de un ítem de tabla mientras la tabla sigue visible
❌  Drawer con un formulario de 20 campos y múltiples secciones
```

#### Página nueva

Navegar a una URL diferente. El usuario pierde el contexto actual.

**Usarlo cuando:**
- La tarea es larga o compleja y necesita toda la pantalla
- El resultado de la acción es algo que el usuario va a querer guardar, compartir o volver a visitar
- La pantalla tiene su propia lógica, estado y quizás su propia URL
- El usuario no necesita volver al contexto anterior inmediatamente

```
✅  Ir a la página de detalle de un producto
✅  Ir a una página de configuración completa
❌  Abrir una página nueva para confirmar la eliminación de un elemento
```

#### Inline / en contexto

Editar o ejecutar directamente sobre el elemento, sin abrir nada.

**Usarlo cuando:**
- La edición es de un campo simple (un nombre, un valor)
- La acción es inmediata y sin consecuencias que requieran confirmación
- Mostrar un formulario separado sería excesivo para la magnitud de la acción

```
✅  Click en un nombre para editarlo en el lugar
✅  Toggle para activar/desactivar una opción directamente en la fila de una tabla
```

---

### 4. Filtros y búsqueda

Los filtros son el caso donde más fácil es arruinar la usabilidad. El principio general es: **los filtros tienen que estar donde el usuario los busca y aplicarse lo antes posible**.

#### Cuándo usar cada patrón

**Filtros inline sobre el listado** (chips, dropdowns sobre la tabla):
- Cuando hay pocos filtros (hasta 3 o 4)
- Cuando el usuario va a cambiarlos frecuentemente mientras mira los resultados
- Cuando el espacio lo permite

**Panel lateral de filtros (drawer o sidebar)**:
- Cuando hay muchos filtros (más de 4)
- Cuando los filtros tienen relación entre sí (elegir una categoría cambia las subcategorías disponibles)
- Cuando el usuario necesita configurar varios filtros antes de ver resultados

**Página de búsqueda separada**:
- Cuando la búsqueda es el flujo principal (motores de búsqueda, ecommerce grande)
- Cuando los filtros son tan complejos que necesitan su propio espacio

#### Errores comunes con filtros

**Requerir submit para aplicar**: si el usuario tiene que presionar "Aplicar" después de cada selección, la experiencia se siente lenta. Siempre que sea posible, los filtros deben aplicarse automáticamente (con un debounce si son lentos).

**No mostrar qué filtros están activos**: el usuario activa tres filtros, ve menos resultados, y no sabe por qué. Siempre mostrar el estado actual de los filtros, y ofrecer una forma fácil de limpiarlos.

**Deshabilitar resultados sin explicar por qué**: si un filtro deja el listado vacío, decir por qué y ofrecer una salida ("No hay resultados con estos filtros. Limpiar filtros.").

**Filtros que no recuerdan su estado**: si el usuario aplica filtros, va al detalle de un ítem, y al volver los filtros se perdieron, la experiencia es frustrante. El estado de los filtros debería vivir en la URL o en el estado de la app.

---

### 5. Feedback inmediato

El usuario necesita saber que sus acciones tuvieron efecto. La ausencia de feedback genera desconfianza: ¿funcionó? ¿Lo tengo que hacer de nuevo?

#### Reglas básicas

**Menos de 100ms**: la acción parece instantánea. No necesita feedback especial.

**100ms a 1 segundo**: mostrar algún indicador sutil (el botón se deshabilita, aparece un spinner inline).

**Más de 1 segundo**: mostrar feedback claro de que algo está pasando. El usuario no debería tener que adivinar.

**Más de 10 segundos**: mostrar progreso si es posible, y dar opción de cancelar.

#### Tipos de feedback

**Feedback de confirmación**: algo salió bien. Toast, mensaje de éxito, cambio visual en el elemento. Tiene que ser breve y desaparecer solo — no necesita que el usuario lo cierre.

**Feedback de error**: algo salió mal. Tiene que ser claro, explicar qué pasó, y decir qué puede hacer el usuario. No desaparece solo.

**Feedback de estado**: el elemento cambió de estado (activado, archivado, eliminado). El cambio visual en el elemento mismo es suficiente la mayoría de las veces.

```
❌  Botón "Guardar" que no hace nada visible durante 3 segundos
✅  Botón "Guardar" que muestra spinner y se deshabilita mientras guarda,
    luego muestra "Guardado" por 2 segundos y vuelve a su estado normal
```

---

### 6. Formularios

Los formularios son la parte de la interfaz que más fricción genera. Algunos principios para hacerlos menos dolorosos:

**Pedir solo lo necesario**: cada campo que se agrega es un campo que el usuario tiene que completar. Si no es imprescindible en ese momento, no va.

**Validar en tiempo real, no solo al submit**: si el email está mal formado, decirlo cuando el usuario termina de escribirlo, no cuando intenta enviar el formulario y tiene que encontrar el error.

**Los errores van junto al campo que los causó**: un mensaje de error genérico arriba del formulario obliga al usuario a buscar cuál campo está mal. El error va debajo del campo específico.

**Labels visibles siempre**: los placeholders desaparecen cuando el usuario empieza a escribir. El usuario llega al final del formulario y no recuerda qué le pedía ese campo. El label tiene que estar visible en todo momento.

**El orden importa**: los campos tienen que seguir un orden lógico para el usuario, no para el sistema. Primero nombre, después apellido. Primero país, después provincia, después ciudad.

**Un formulario largo es un flujo en pasos**: si un formulario tiene más de 6 o 7 campos, considerar dividirlo en pasos. Cada paso tiene un objetivo claro y el usuario puede ver su progreso.

---

### 7. Estados que siempre hay que diseñar

Toda pantalla que muestra datos tiene que tener resueltos estos cinco estados. No diseñarlos de antemano significa inventarlos bajo presión cuando aparecen en producción.

| Estado | Qué mostrar |
|--------|-------------|
| **Cargando** | La pantalla está esperando datos. Skeleton screen, spinner, o deshabilitar acciones mientras carga. |
| **Vacío** | No hay datos todavía. Un mensaje claro que explique por qué y qué puede hacer el usuario ("Todavía no tenés proyectos. Creá el primero."). |
| **Con datos** | El caso ideal. El que todos diseñan. |
| **Error** | Algo salió mal. Qué pasó, qué puede hacer el usuario. Opción de reintentar. |
| **Parcial** | Hay datos pero incompletos. El componente tiene que poder renderizar aunque falten campos opcionales. |

El estado vacío y el estado de error son los más olvidados y los que el usuario más necesita entender.

---

### 8. No obligar al usuario a recordar

La memoria del usuario es un recurso escaso. La interfaz no debería depender de él.

**Algunos ejemplos de interfaces que obligan a recordar:**
- Mostrar un código en el paso 1 y pedirlo en el paso 3 sin mantenerlo visible
- Requerir que el usuario ingrese el mismo dato en dos pantallas distintas
- Filtros que se pierden al navegar hacia atrás
- Una búsqueda que no recuerda el término al volver de un resultado

**La alternativa:**
- Persistir el estado relevante en la URL o en el estado de la aplicación
- Mostrar el contexto necesario en el lugar donde se necesita
- Permitir al usuario volver al punto exacto donde estaba

---

## Parte 2: Estructura visual

---

### 9. Design Tokens

Un design token es una variable con nombre semántico que representa una decisión de diseño. En lugar de escribir valores crudos dispersos por el código, se definen una sola vez y se referencian en todos lados.

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

**Familias esenciales:**
- **Color**: marca, texto, superficies, estados semánticos
- **Tipografía**: familias, tamaños, pesos, interlineado
- **Espaciado**: escala fija (4 / 8 / 12 / 16 / 24 / 32 / 48 / 64px)
- **Bordes**: radios y grosores
- **Sombras**: elevaciones

**Regla de oro**: el único lugar donde aparecen valores crudos (`#1a3c5e`, `13px`, `6px`) es donde se definen los tokens. En ningún otro lado.

---

### 10. Sistema de color

Una paleta bien construida tiene estructura, no colores sueltos.

- **1 familia de marca**: 7 a 9 tonos del más claro al más oscuro
- **1 familia de neutros**: grises para texto, fondos y bordes
- **4 familias semánticas**: éxito / advertencia / peligro / información

Los tonos tienen roles:

| Rango | Uso típico |
|-------|------------|
| 50 – 100 | Fondos suaves, badges, chips |
| 200 – 300 | Bordes, separadores |
| 400 – 500 | Iconos, elementos decorativos |
| 600 – 700 | Texto sobre fondo claro |
| 800 – 900 | Texto prominente, headings |

Nombrar los colores por su rol, no por su apariencia:

```css
/* ❌ */
--azul-claro: #dbeafe;
--azul-oscuro: #1e3a5f;

/* ✅ */
--color-brand-100: #dbeafe;
--color-brand-900: #1e3a5f;
```

---

### 11. Tipografía y jerarquía visual

La tipografía hace el 80% del trabajo visual. Antes de tocar colores o ilustraciones, la jerarquía tipográfica tiene que estar resuelta.

**Escala de tamaños** (una, no inventada por componente):
```
xs  → 12px  labels, metadata
sm  → 14px  texto secundario
base→ 16px  cuerpo principal
lg  → 20px  subtítulos
xl  → 24px  títulos de sección
2xl → 32px  títulos de página
```

**Pesos con propósito:**
```
400 regular   → cuerpo de texto
500 medium    → labels, metadata con más presencia
600 semibold  → títulos de sección, valores importantes
700 bold      → títulos principales, énfasis real
```

Si todo tiene el mismo peso, nada está enfatizado. El peso funciona por contraste.

**Jerarquía de texto**: tres niveles son suficientes para casi todo.
- Primario: color de texto normal
- Secundario: un tono más suave
- Muted: metadatos, timestamps, hints

---

### 12. Componentes y variantes

Un componente bien construido encapsula todas sus variantes y estados en un solo lugar.

**Variantes declaradas explícitamente:**
```html
<button class="btn btn--primary">Guardar</button>
<button class="btn btn--secondary">Cancelar</button>
<button class="btn btn--danger">Eliminar</button>
```

**Estados que todo componente interactivo necesita tener resueltos:**
default → hover → focus → active → disabled → loading → error

**Nombres semánticos, no visuales:**
```
❌  .boton-rojo-grande    →    ✅  .btn--danger
❌  .texto-gris-chico     →    ✅  .label--muted
❌  .caja-redondeada      →    ✅  .card
```

Cuando el diseño cambia, el nombre semántico sigue teniendo sentido. El nombre visual miente.

---

### 13. Espaciado consistente

La mayoría de las interfaces que "se ven raro" no tienen problema de color ni de tipografía. Tienen espaciado inconsistente.

**Escala fija y no salirse de ella:**
```
4px → 8px → 12px → 16px → 24px → 32px → 48px → 64px
```

`margin: 7px` o `padding: 11px` son señales de que algo se está improvisando.

**Regla de proximidad**: elementos relacionados usan poco espacio entre sí. Grupos distintos usan más. Esta regla aplicada consistentemente genera layouts que se ven ordenados sin ajuste fino.

---

### 14. Accesibilidad

No es una feature avanzada. Es el piso mínimo.

**Contraste**: texto normal mínimo 4.5:1, texto grande mínimo 3:1.

**Foco visible**: no hacer `outline: none` sin reemplazarlo.
```css
:focus-visible {
    outline: 2px solid var(--color-brand-500);
    outline-offset: 2px;
}
```

**HTML semántico**: `<button>` para botones, `<nav>` para navegación, `<label>` para cada campo de formulario. El elemento correcto define comportamiento accesible automáticamente.

**Tamaños de toque en mobile**: mínimo 44×44px para cualquier elemento interactivo.

---

### 15. Mobile-first

Diseñar desde el viewport más chico y expandir. Un layout simple es más fácil de expandir que uno complejo de achicar.

```css
/* Base: mobile */
.contenedor { display: block; padding: 16px; }

/* Desktop */
@media (min-width: 768px) {
    .contenedor {
        display: grid;
        grid-template-columns: 1fr 2fr;
        padding: 32px;
    }
}
```

---

### 16. Consistencia como usabilidad

La consistencia no es solo estética. Es funcional: cuando algo siempre está en el mismo lugar y se ve igual, el usuario no tiene que pensar. Puede operar la interfaz de forma automática.

Cada excepción al sistema tiene un costo. No solo en código — en la experiencia del usuario. Si los botones de confirmación a veces están a la izquierda y a veces a la derecha, el usuario siempre tiene que buscarlos. Si los modales a veces se cierran con Escape y a veces no, el usuario pierde confianza.

**Lo que genera consistencia:**
- Un sistema de tokens que impide valores arbitrarios
- Componentes documentados y reutilizados
- La pregunta antes de crear algo nuevo: ¿esto ya existe?
- Patrones de interacción que se repiten en toda la aplicación

---

## Conclusión

Una interfaz bien hecha tiene dos capas que se refuerzan entre sí: la usabilidad (el usuario puede hacer lo que vino a hacer, sin fricción, sin confusión) y la estructura (el código visual es coherente, mantenible y predecible).

Ninguna de las dos funciona sola. Una interfaz hermosa pero confusa falla al usuario. Una interfaz usable pero construida sin sistema se convierte en un caos que nadie quiere tocar.

> *Una buena interfaz se siente obvia. El usuario no la nota — nota lo que hace.*
