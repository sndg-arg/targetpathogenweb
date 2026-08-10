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

### 3. Navegación y orientación

El usuario siempre tiene que saber dónde está. Parece obvio, pero es uno de los detalles que más se omiten en fronts de principiantes.

**El problema**: si el usuario llega a una pantalla y no puede responder de un vistazo "¿en qué parte de la app estoy?", la navegación está fallando.

**Las herramientas que resuelven esto:**

**Título de página visible**: cada pantalla tiene un título que describe qué es. No el nombre de la app — el nombre de esa pantalla específica. "Proyectos", "Configuración de cuenta", "Detalle de pedido #1042".

**Ítem activo en el menú**: el ítem de navegación que corresponde a la pantalla actual tiene que estar visualmente marcado como activo. Si el usuario está en "Configuración" y ningún ítem del menú está resaltado, la app se siente desorientadora.

**Breadcrumbs en jerarquías profundas**: cuando hay más de dos niveles de profundidad (ej: Proyectos → Proyecto X → Tarea Y), los breadcrumbs le permiten al usuario saber cómo llegó y volver a cualquier punto sin usar el botón de atrás del navegador.

```
✅  Inicio > Proyectos > Proyecto Alpha > Tareas
❌  Una pantalla sin título y sin indicación de dónde está en la app
```

**El estado activo no es solo visual**: también comunica. Un menú donde nada está resaltado obliga al usuario a leer todos los ítems para orientarse. Un ítem activo claro le permite escanear y seguir.

---

### 4. Modales, drawers y páginas nuevas: cuándo usar cada uno

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

### 5. Filtros y búsqueda

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

### 6. Tablas

Las tablas son uno de los patrones más comunes en apps de gestión y tienen sus propias reglas. Una tabla mal construida con mucha información es ilegible; bien construida, es la forma más eficiente de mostrar datos comparables.

#### Alineación de columnas

La alineación no es estética — comunica el tipo de dato:

| Tipo de dato | Alineación |
|-------------|------------|
| Texto (nombres, descripciones) | Izquierda |
| Números, cantidades, precios | Derecha |
| Estados, badges, íconos | Centro |
| Acciones (botones, links) | Derecha o centro |

Los números alineados a la derecha permiten comparar magnitudes de un vistazo. Alineados a la izquierda o al centro, el ojo tiene que hacer trabajo extra.

#### Columnas y densidad

Más columnas no es más información — es más ruido. Cada columna que se agrega compite con las demás por la atención del usuario.

- Mostrar solo las columnas que el usuario necesita para tomar decisiones en ese contexto
- Si hay muchas columnas, considerar permitir que el usuario elija cuáles ver
- En mobile, una tabla de 8 columnas no cabe: hay que pensar qué columnas son esenciales y cuáles colapsan o desaparecen

#### Acciones por fila

Las acciones que aplican a un elemento específico van en su fila, no en un lugar separado. El usuario no debería tener que seleccionar una fila y luego buscar el botón de acción en otro lugar de la pantalla.

```
✅  Cada fila tiene sus propios botones "Editar" / "Eliminar" al final
✅  Un menú de tres puntos (kebab menu) por fila cuando hay muchas acciones
❌  Botones de acción fuera de la tabla que operan sobre "la fila seleccionada"
```

#### Estado vacío y carga

Una tabla vacía sin mensaje es confusa. Una tabla que carga sin skeleton o spinner hace que el usuario no sepa si algo está pasando. Estos estados son parte del componente, no un detalle para después.

---

### 7. Íconos y tooltips

Los íconos son útiles para reforzar significado, reducir texto, y hacer la interfaz más rápida de escanear. El problema es que solos, sin contexto, son un acertijo.

#### Cuándo un ícono solo alcanza

Un ícono puede estar sin label únicamente cuando:
- Es universalmente reconocido (lupa = buscar, X = cerrar, hamburguesa = menú)
- Aparece en un contexto donde su función es obvia (el ícono de papelera en una fila de tabla de archivos)
- Tiene un tooltip que aparece al hacer hover

En todos los demás casos, el ícono necesita un label de texto al lado.

```
✅  🔍  (lupa sola en una barra de búsqueda — obvia por contexto)
✅  ✏️  Editar  (ícono + label para una acción en un formulario)
❌  Cinco íconos en una barra de herramientas sin labels ni tooltips
```

#### Tooltips

Un tooltip es el texto que aparece al hacer hover sobre un elemento. Sirve para:
- Explicar un ícono que no tiene label
- Dar más contexto sobre una acción antes de ejecutarla
- Mostrar información que no entra en el espacio disponible (texto truncado)

**Reglas básicas:**
- El tooltip aparece sobre el elemento, no debajo (para no quedar tapado por el cursor)
- Texto corto: una frase, no un párrafo
- No usar para información crítica que el usuario necesita antes de actuar — eso va visible en pantalla
- En mobile no existen (no hay hover). Si algo depende de un tooltip para entenderse, en mobile queda roto

---

### 8. Feedback inmediato

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

### 9. Formularios

Los formularios son la parte de la interfaz que más fricción genera. Algunos principios para hacerlos menos dolorosos:

**Pedir solo lo necesario**: cada campo que se agrega es un campo que el usuario tiene que completar. Si no es imprescindible en ese momento, no va.

**Validar en tiempo real, no solo al submit**: si el email está mal formado, decirlo cuando el usuario termina de escribirlo, no cuando intenta enviar el formulario y tiene que encontrar el error.

**Los errores van junto al campo que los causó**: un mensaje de error genérico arriba del formulario obliga al usuario a buscar cuál campo está mal. El error va debajo del campo específico.

**Labels visibles siempre**: los placeholders desaparecen cuando el usuario empieza a escribir. El usuario llega al final del formulario y no recuerda qué le pedía ese campo. El label tiene que estar visible en todo momento.

**El orden importa**: los campos tienen que seguir un orden lógico para el usuario, no para el sistema. Primero nombre, después apellido. Primero país, después provincia, después ciudad.

**Un formulario largo es un flujo en pasos**: si un formulario tiene más de 6 o 7 campos, considerar dividirlo en pasos. Cada paso tiene un objetivo claro y el usuario puede ver su progreso.

---

### 10. Estados que siempre hay que diseñar

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

### 11. No obligar al usuario a recordar

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

### 12. Design Tokens

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

### 13. Sistema de color

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

### 14. Tipografía y jerarquía visual

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

### 15. Componentes, variantes y estados

Un componente bien construido encapsula todas sus variantes y estados en un solo lugar. No es un conjunto de clases ad-hoc — es una unidad con reglas claras sobre cómo puede verse y comportarse.

#### Variantes: qué significan primary, secondary, danger y el resto

Cuando hay más de un botón en pantalla, no todos tienen el mismo peso. La variante le dice al usuario cuál es la acción más importante, cuál es secundaria, y cuál hay que pensarla dos veces antes de ejecutar.

**Primary** es la acción principal de esa pantalla o formulario. La que el usuario vino a hacer. Suele tener el color de marca, relleno sólido, y es visualmente la más prominente. En cualquier pantalla debería haber **un solo botón primary** visible a la vez — si hay dos compitiendo, el usuario no sabe qué hacer.

```
Ejemplos: "Guardar", "Confirmar pedido", "Crear proyecto", "Enviar"
```

**Secondary** es una acción alternativa, válida pero menos importante. Generalmente sin relleno o con relleno suave, borde visible, color más neutro. Existe para dar opciones sin restarle protagonismo al primary.

```
Ejemplos: "Cancelar", "Volver", "Ver más tarde", "Exportar"
```

**Danger** (o destructive) es una acción que no se puede deshacer o que tiene consecuencias importantes: eliminar, borrar, revocar acceso. El color rojo no es decoración — es una señal para el usuario de que tiene que prestar atención antes de hacer click. Un danger button casi siempre debería ir acompañado de alguna confirmación.

```
Ejemplos: "Eliminar cuenta", "Borrar archivo", "Revocar acceso"
```

**Ghost / outline** es un botón sin relleno, solo con borde. Menos visual que secondary, útil para acciones de baja prioridad o cuando hay muchos botones juntos y se necesita reducir el ruido visual.

```
Ejemplos: botones en tablas, acciones secundarias en cards, "Ver detalle"
```

**Link** parece un link de texto pero se comporta como botón. Para acciones que son tan secundarias que no justifican ni el borde del ghost.

```
Ejemplos: "¿Olvidaste tu contraseña?", "Editar", "Ver todos"
```

#### La jerarquía en la práctica

En cualquier grupo de acciones tiene que quedar claro de un vistazo qué es lo más importante:

```
✅  [Guardar]  [Cancelar]
     primary    secondary

✅  [Confirmar eliminación]  [Volver]
         danger               secondary

❌  [Guardar]  [Cancelar]  [Eliminar]
     primary    primary      primary
     — tres botones iguales, ninguna jerarquía clara
```

#### Estados

Todo componente interactivo necesita tener resueltos estos estados desde el principio:

```
default → hover → focus → active → disabled → loading → error
```

#### Nombres semánticos, no visuales

```
❌  .boton-rojo-grande    →    ✅  .btn--danger
❌  .texto-gris-chico     →    ✅  .label--muted
❌  .caja-redondeada      →    ✅  .card
```

Cuando el diseño cambia, el nombre semántico sigue teniendo sentido. El nombre visual miente.

---

### 16. Espaciado consistente

La mayoría de las interfaces que "se ven raro" no tienen problema de color ni de tipografía. Tienen espaciado inconsistente.

**Escala fija y no salirse de ella:**
```
4px → 8px → 12px → 16px → 24px → 32px → 48px → 64px
```

`margin: 7px` o `padding: 11px` son señales de que algo se está improvisando.

**Regla de proximidad**: elementos relacionados usan poco espacio entre sí. Grupos distintos usan más. Esta regla aplicada consistentemente genera layouts que se ven ordenados sin ajuste fino.

---

### 17. Accesibilidad

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

**Tamaños de toque en mobile**: mínimo 44×44px para cualquier elemento interactivo. Un ícono de 16px sin padding suficiente es imposible de presionar con precisión en un teléfono.

---

### 18. Mobile-first

Mobile-first no es solo una técnica de CSS — es una forma de pensar el diseño que cambia el resultado.

Cuando se diseña primero para desktop y después se "adapta" a mobile, el proceso es de compresión: sacar cosas, achicar, reorganizar lo que ya existe. El resultado casi siempre son parches. Algo que no entra se oculta, algo que era una barra lateral pasa a ser un menú flotante, las columnas colapsan de formas inesperadas.

Cuando se diseña primero para mobile, el proceso es de expansión: lo que funciona en 375px es la base, y en pantallas más grandes simplemente se aprovecha el espacio extra. Un layout simple es más fácil de expandir que uno complejo de achicar.

Además, diseñar para mobile fuerza a tomar decisiones sobre qué es realmente importante. En una pantalla chica no entra todo — hay que elegir. Esas decisiones casi siempre mejoran el diseño en todos los tamaños.

```css
/* Base: mobile — se define la estructura esencial */
.contenedor {
    display: block;
    padding: 16px;
}

/* A partir de 768px: se aprovecha el espacio extra */
@media (min-width: 768px) {
    .contenedor {
        display: grid;
        grid-template-columns: 1fr 2fr;
        padding: 32px;
    }
}
```

---

### 19. Consistencia como usabilidad

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
