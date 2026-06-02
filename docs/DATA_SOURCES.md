# Origen de los datos en TargetPathogenWeb

Este documento describe de dónde proviene cada dato que la plataforma muestra, qué herramienta o base de datos lo genera, y qué significa biológicamente. Está dirigido a biólogos que quieren entender la trazabilidad de los resultados sin necesidad de conocer los detalles técnicos del pipeline.

---

## 1. Información básica de la proteína

| Campo | Origen |
|---|---|
| Accesión (ej. `PA4406`, `VK055_0001`) | Archivo GenBank (`.gbk`) cargado al importar el genoma |
| Descripción / función anotada | Anotación del GenBank original |
| Gen (ej. `lpxC`) | Qualifier `gene` del GenBank |
| Longitud (aminoácidos) | Secuencia del GenBank |
| Estado (`annotated` / `hypothetical`) | Derivado de la descripción del GenBank |

**Interpretación:** esta información proviene directamente del registro de secuencia depositado en NCBI (u otra fuente). La calidad de la anotación funcional depende de quién y cómo anotó el genoma originalmente.

---

## 2. Estructura 3D

Cada proteína tiene una estructura asignada como fuente primaria de análisis estructural. El orden de preferencia es:

1. **Experimental** (cristalografía de rayos X u otras técnicas) — descargada de la base de datos **PDB** si existe una estructura para esta proteína o un homólogo cercano.
2. **ColabFold** — modelo predicho por ColabFold (variante de AlphaFold2 optimizada para velocidad), calculado durante el pipeline para proteínas sin estructura experimental disponible.
3. **AlphaFold** — modelo descargado desde la base de datos de AlphaFold (DeepMind/EBI), disponible para proteínas con accesión UniProt conocida.

**Indicador pLDDT** (en el perfil de target): métrica de confianza del modelo predicho, escala 0–100. Valores ≥ 70 indican regiones estructuralmente confiables. Valor calculado por ColabFold durante la predicción.

**Interpretación:** una estructura experimental es más confiable para análisis de bolsillos y docking. Los modelos predichos son muy útiles cuando no existe estructura experimental, pero deben interpretarse con más cautela, especialmente en regiones con pLDDT bajo (< 50).

---

## 3. Druggability (drogabilidad)

**Herramienta:** FPocket (v4+)  
**Etapa del pipeline:** procesamiento de estructuras (remoto en SLURM)

FPocket detecta bolsillos en la superficie de la proteína y calcula una puntuación de drogabilidad basada en propiedades geométricas y fisicoquímicas del bolsillo (volumen, hidrofobicidad, accesibilidad al solvente, etc.).

**Escala:** 0 a 1
- ≥ 0.7 → altamente drogable (bolsillo bien definido, favorable para unión de ligandos)
- 0.4–0.69 → moderadamente drogable
- < 0.4 → baja drogabilidad

El valor que aparece en la plataforma corresponde al bolsillo de mayor puntuación de la estructura preferida (experimental si está disponible, modelo predicho en caso contrario).

**Interpretación:** una proteína con druggability alta tiene mayor probabilidad de ser inhibida por una molécula pequeña. No garantiza que exista un inhibidor conocido, pero es un criterio estructural favorable para el diseño de fármacos.

---

## 4. Bolsillos de unión

### FPocket
**Herramienta:** FPocket  
Detecta y caracteriza bolsillos en la superficie proteica. Cada bolsillo listado en la tabla tiene su propia puntuación de drogabilidad. Se pueden visualizar en el modelo 3D interactivo.

### P2Rank
**Herramienta:** P2Rank (machine learning sobre descriptores locales del sitio)  
Predice sitios de unión a ligandos usando un modelo de aprendizaje automático entrenado sobre estructuras del PDB. Devuelve una **probabilidad** (0–1) y una puntuación de ranking.

**Interpretación:** FPocket y P2Rank son complementarios. FPocket es más geométrico; P2Rank incorpora información de aprendizaje de patrones de sitios reales. Cuando ambos coinciden en un bolsillo, la confianza es mayor.

---

## 5. Anotación funcional (GO y EC)

### Términos Gene Ontology (GO)
**Fuente principal:** InterProScan — análisis de dominios contra múltiples bases de datos (Pfam, HAMAP, PANTHER, Gene3D, etc.). Cada base de datos aporta términos GO basados en la función conocida de la familia de dominio.  
**Fuente secundaria:** mapeo a UniProt (`fetch_uniprot_annotations`) cuando la proteína tiene accesión UniProt reconocida.

Los términos GO cubren tres aspectos:
- **Función molecular** (qué hace la proteína a nivel bioquímico)
- **Proceso biológico** (en qué proceso celular participa)
- **Componente celular** (dónde está localizada)

### Números EC (Enzyme Commission)
**Fuente:** `fetch_uniprot_annotations` desde UniProt, o entradas con EC en el TSV de InterProScan.  
Clasificación jerárquica de actividad enzimática (ej. `3.5.1.108` = UDP-3-O-acil-N-acetylglucosamina desacetilasa).

**Interpretación:** la presencia de anotaciones GO y EC indica que la proteína tiene función conocida o inferida por homología. Proteínas sin anotación ("hypothetical protein") son candidatos menos estudiados, aunque pueden igualmente ser buenos blancos si tienen druggability y esencialidad favorables.

---

## 6. Features de secuencia (dominios e InterPro)

**Herramienta:** InterProScan (v5.x, ejecución remota en cluster SLURM)  
**Bases de datos consultadas:** Gene3D, Pfam, HAMAP, PANTHER, NCBIfam, PIRSF, PRINTS, ProSitePatterns, ProSiteProfiles, SFLD, SMART, SUPERFAMILY, CDD, FunFam, Phobius, SignalP (3 variantes), TMHMM, MobiDBLite, Coils

Cada fila en la tabla de features representa un hit de una base de datos contra la secuencia de la proteína, con coordenadas de inicio y fin en la secuencia de aminoácidos.

Algunos tipos de features relevantes:
- **Dominios de función** (Pfam, HAMAP, Gene3D): regiones con estructura y función conservada
- **Señal de secreción** (SignalP, Phobius): péptido señal que indica que la proteína se exporta fuera del citoplasma
- **Dominios transmembrana** (Phobius, TMHMM): regiones que atraviesan la membrana
- **Desorden** (MobiDBLite): regiones sin estructura definida

**Interpretación:** los features son la base para inferir función cuando no hay anotación directa. Una proteína con dominio Pfam conocido puede tener función inferida aunque esté anotada como "hypothetical protein".

---

## 7. Perfil de target (scores de priorización)

### Human off-target
**Herramienta:** DIAMOND BLASTP vs. proteoma humano (FastTarget)  
**Resultado:** `Hit` / `No hit` (umbral: e-value ≤ 1×10⁻⁵)  
**Interpretación:** proteínas sin hit humano son candidatas más selectivas para el patógeno, con menor riesgo de efectos adversos en el huésped. **Preferir "No hit"** para blancos terapéuticos.

### Human identity (%) y Human E-value
Detalle cuantitativo del hit humano: porcentaje de identidad y e-value del mejor alineamiento encontrado. Un hit con identidad baja (< 30%) y e-value borderline puede ser menos preocupante que uno con identidad alta.

### Gut microbiome off-target
**Herramienta:** DIAMOND BLASTP vs. genomas de referencia del microbioma intestinal humano (FastTarget)  
**Resultado:** `Hit` / `No hit` (umbral: identidad > 40%, cobertura > 70%)  
**Interpretación:** proteínas con hit en el microbioma intestinal son candidatas más problemáticas para uso terapéutico, ya que el fármaco podría afectar la microbiota beneficiosa del paciente. **Preferir "No hit"**.

### Essential (DEG)
**Herramienta:** DIAMOND BLASTP vs. base de datos DEG (*Database of Essential Genes*)  
**Resultado:** `Y` (esencial) / `N` (no esencial)  
**Interpretación:** proteínas con homología en DEG tienen mayor probabilidad de ser esenciales para la viabilidad del organismo, lo que las hace blancos terapéuticos más atractivos (inhibirlas mataría la bacteria).

### Localization (localización subcelular)
**Herramienta:** PSORTb (v3.x)  
**Categorías:** Cytoplasmic, CytoplasmicMembrane, Periplasmic, OuterMembrane, Extracellular, Unknown  
**Interpretación:** para el diseño de fármacos de acción sistémica, las proteínas de membrana externa, periplasma y superficie extracelular son más accesibles para anticuerpos y algunas moléculas pequeñas. Las proteínas citoplasmáticas requieren que el fármaco penetre la membrana.

---

## 8. Evidencia de ligandos (binders)

Todos los datos de ligandos provienen de **LigQ_2**, una herramienta de búsqueda de ligandos por homología de secuencia, ejecutada en cluster SLURM como último paso del pipeline.

LigQ_2 toma la secuencia de cada proteína del genoma, busca proteínas similares en PDB y ChEMBL mediante BLAST, y recupera los ligandos co-cristalizados o bioactivos reportados para esas proteínas similares. También propone candidatos de ZINC mediante similaridad química.

### Tipos de evidencia

| Tipo | Origen | Significado |
|---|---|---|
| **PDB co-crystal (directa)** | PDB — ligando cristalizado con **esta proteína exacta** | Evidencia más sólida: el ligando está confirmado estructuralmente en el sitio de unión |
| **PDB via homologs** | PDB — ligando cristalizado con una **proteína similar** | Evidencia transferida; la geometría del sitio puede diferir |
| **ChEMBL bioactive (directa)** | ChEMBL — compuesto con actividad medida contra **esta proteína** | Evidencia experimental de bioactividad (IC50, Ki, etc.) |
| **ChEMBL via homologs** | ChEMBL — compuesto activo contra una **proteína similar** | Evidencia transferida por homología |
| **ZINC proposed** | ZINC — candidatos virtuales con similaridad química ≥ 0.5 (Tanimoto) a binders conocidos | Propuesta computacional; no tiene validación experimental |

### Directo vs. por homología
Un ligando es **directo** cuando el identificador UniProt del registro de PDB/ChEMBL coincide exactamente con el UniProt de la proteína analizada. Esto requiere que la proteína tenga un mapeo UniProt válido. Si no hay mapeo UniProt (como ocurre con genomas anotados solo con locus tags), toda la evidencia aparece como "via homologs".

### Propiedades fisicoquímicas mostradas
- **MW** (peso molecular): relevante para absorción; compuestos > 500 Da pueden tener problemas de biodisponibilidad
- **LogP**: lipofilia; valores entre −1 y 5 son favorables para permeabilidad celular
- **TPSA** (polar surface area): < 140 Å² es favorable para penetración de membrana bacteriana
- **Lipinski Ro5**: regla de 5 de Lipinski — ✓ indica cumplimiento de los criterios básicos de drug-likeness oral
- **PAINS**: "Pan-Assay Interference Compounds" — ✓ Clean indica que el compuesto no tiene grupos reactivos que interfieran inespecíficamente en ensayos

---

## 9. Límites y consideraciones de interpretación

- **Toda la evidencia es computacional o transferida por homología**, excepto los binders PDB co-crystal y ChEMBL directos, que son datos experimentales.
- La ausencia de un dato (ej. EC = 0, Localization = Unknown) no significa que la proteína no tenga esa propiedad — puede indicar que la herramienta no encontró homología suficiente o que el dato no se computó para ese genoma.
- Los scores de druggability son descriptores estructurales, no predicciones de actividad biológica ni toxicidad.
- La esencialidad inferida por DEG es conservada: una proteína puede ser esencial en el organismo de referencia de DEG pero no en el patógeno estudiado, o viceversa.
- Los modelos de ColabFold tienen errores sistemáticos en regiones desordenadas, membranas, y proteínas con pocas secuencias homólogas disponibles. Verificar siempre el pLDDT.
