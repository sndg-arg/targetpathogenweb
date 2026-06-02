# Origen de los datos en TargetPathogenWeb

Este documento describe de dónde proviene cada dato que la plataforma muestra: qué herramienta lo genera, en qué paso del pipeline ocurre, con qué parámetros, y qué significa biológicamente. Está escrito para biólogos que quieren entender la trazabilidad completa de los resultados.

---

## El pipeline completo: 24 etapas en orden

El pipeline se ejecuta linealmente. Las etapas pesadas (marcadas con ★) corren en nodos del cluster SLURM mediante SSH, no en el servidor web.

| Etapa | Nombre interno | Qué hace |
|---|---|---|
| 1 | `clear_folder` | Limpia el directorio de trabajo del genoma |
| 2 | `download_gbk` | Descarga el archivo GenBank desde NCBI (o carga un GBK externo) |
| 3 | `load_gbk` | Importa el GBK a la base de datos: proteínas, secuencias, anotaciones originales |
| 3 | `sync_genome_metadata` | Sincroniza metadatos del ensamblado (organismo, cepa, longitud) |
| 4 ★ | `fasttarget` | Corre FastTarget: DIAMOND BLASTP contra proteoma humano, microbioma intestinal y DEG |
| 5 | `load_score human_offtarget` | Carga los resultados de off-target humano en la base de datos |
| 6 | `load_score micro_offtarget` | Carga los resultados de off-target de microbioma intestinal |
| 7 | `load_score essenciality` | Carga los resultados de esencialidad (DEG) |
| 8 | `index_genome_db` | Indexa las secuencias proteicas para búsquedas internas |
| 9 | `index_genome_seq` | Indexa la secuencia nucleotídica del genoma |
| 10 ★ | `interproscan` | Corre InterProScan en SLURM: anotación de dominios y funciones |
| 11 | `load_interpro` | Carga el TSV de InterProScan: dominios, GO, EC (cuando están en el output) |
| 12 | `gbk2uniprot_map` | Mapea las proteínas del genoma a identificadores UniProt |
| 13 | `fetch_uniprot_annotations` | Descarga GO y EC desde UniProt para las proteínas mapeadas |
| 13 | `fetch_experimental_structures` | Busca estructuras cristalográficas en PDB para las proteínas mapeadas |
| 14 | `get_unipslst` | Lee la lista de UniProt IDs para buscar modelos en AlphaFold DB |
| 15 ★ | `alphafold_unips` | Descarga modelos de AlphaFold DB (4 descargas en paralelo) |
| 16 ★ | `colabfold_predict` | Predice estructuras con ColabFold para proteínas sin modelo disponible |
| 17 ★ | `structures_remote` | Procesa todas las estructuras: FPocket + P2Rank + carga a base de datos |
| 18 | `druggability_2_csv` | Extrae puntuaciones de drogabilidad desde el output de FPocket a CSV |
| 19 | `load_score druggability` | Carga el score de drogabilidad en la base de datos |
| 20 | `psort` | Corre PSORTb para predecir localización subcelular |
| 21 | `load_score psort` | Carga la predicción de localización en la base de datos |
| 22 | `get_binders` | Descarga binders de fuentes externas (flujo alternativo a LigQ_2) |
| 23 | `load_binders` | Carga esos binders en la base de datos |
| 24 ★ | `ligq_remote` | Corre LigQ_2 en SLURM: búsqueda de ligandos por homología en PDB, ChEMBL, ZINC |

---

## Información básica de la proteína

**Etapa:** 2–3 (`download_gbk` → `load_gbk`)

El archivo GenBank (`.gbk` o `.gbk.gz`) se descarga de NCBI usando la accesión del genoma, o se sube manualmente. La etapa `load_gbk` parsea el archivo e importa a la base de datos:

- **Accesión** (`accession`): qualifier `locus_tag` del feature CDS en el GenBank. En algunos genomas es un código del tipo `PA4406` (PAO1) o `VK055_0001` (ATCC43816).
- **Descripción / función**: qualifier `product` del feature CDS.
- **Gen**: qualifier `gene` del feature CDS (ej. `lpxC`, `envA`). Si el GenBank tiene `protein_id` (accesión RefSeq tipo `NP_` o `WP_`), también se importa pero se filtra de la vista para evitar mostrar datos redundantes.
- **Longitud (aminoácidos)**: longitud de la secuencia de aminoácidos del qualifier `translation`.
- **Estado** (`annotated` / `hypothetical`): derivado de la descripción; si contiene "hypothetical" o está vacía, se considera no anotada.

**Importante:** la calidad de la anotación funcional en el campo "descripción" depende 100% de quién y cómo anotó el genoma originalmente (PGAP de NCBI, Prokka, RAST, etc.). TPW no modifica ni valida esa anotación.

---

## Estructura 3D

**Etapas:** 13 (`fetch_experimental_structures`), 15 (`alphafold_unips`), 16 (`colabfold_predict`)

Cada proteína tiene una única estructura asignada como preferida para el análisis. El orden de preferencia es:

### 1. Estructura experimental (cristalografía, cryo-EM, etc.)
**Fuente:** Protein Data Bank (PDB)  
**Cómo se obtiene:** la etapa 13 busca en PDB todas las estructuras disponibles para el UniProt ID de la proteína (requiere que el mapeo UniProt de la etapa 12 haya funcionado). Si se encuentran estructuras, se descargan archivos `.pdb` y se almacenan localmente.  
**Indicador en la vista:** "Experimental" o "Crystal structure".

### 2. Modelo AlphaFold (AlphaFold Database)
**Fuente:** AlphaFold Protein Structure Database (EBI/DeepMind)  
**Cómo se obtiene:** la etapa 15 descarga el modelo `.pdb` desde `https://alphafold.ebi.ac.uk/` usando el UniProt ID. Requiere que la proteína tenga UniProt ID mapeado. La descarga es en paralelo (4 proteínas simultáneas).  
**Indicador en la vista:** "AlphaFold".

### 3. Modelo ColabFold (predicción local o remota)
**Fuente:** ColabFold (implementación de AlphaFold2 con búsqueda acelerada via MMseqs2)  
**Cómo se obtiene:** la etapa 16 corre ColabFold para proteínas que no tienen ni estructura experimental ni modelo de AlphaFold DB. Puede ejecutarse localmente (lento, ~30–60 min/proteína) o remotamente en GPU via SLURM. Se genera un archivo `.pdb` por proteína.  
**Indicador en la vista:** "ColabFold".

### pLDDT (predicted Local Distance Difference Test)
**Qué es:** métrica de confianza del modelo predicho, calculada por AlphaFold/ColabFold para cada residuo. Escala 0–100.  
- ≥ 90: predicción muy confiable
- 70–90: buena confianza general
- 50–70: baja confianza, región posiblemente desordenada
- < 50: no confiable estructuralmente  
**Dónde aparece:** en el "Target profile" como "ColabFold pLDDT". El valor guardado es el pLDDT promedio de todos los residuos del modelo.

---

## Druggability (drogabilidad)

**Etapas:** 17 (`structures_remote` → FPocket) → 18 (`druggability_2_csv`) → 19 (`load_score druggability`)

**Herramienta:** FPocket v4+  
FPocket detecta bolsillos en la superficie proteica usando esferas de Voronoi. Para cada bolsillo, calcula el `drugScore` (también llamado `drug_score`), un índice compuesto basado en:
- Volumen del bolsillo
- Fracción de residuos hidrofóbicos que bordean el bolsillo
- Accesibilidad al solvente
- Momento dipolar del bolsillo

La etapa 18 extrae el drugScore máximo entre todos los bolsillos de la estructura, que es el valor de drogabilidad que se guarda por proteína.

**Escala:** 0 a 1
- ≥ 0.7 → altamente drogable
- 0.4–0.69 → moderadamente drogable
- < 0.4 → baja drogabilidad

**Interpretación:** una puntuación alta indica que la proteína tiene al menos un bolsillo bien definido, de tamaño adecuado y con propiedades fisicoquímicas favorables para alojar una molécula pequeña. No implica que exista un fármaco conocido.

---

## Bolsillos de unión

**Etapa:** 17 (`structures_remote`)

### FPocket
FPocket identifica bolsillos y calcula para cada uno su druggability individual. En la tabla 3D se muestra el drugScore de cada bolsillo. Los residuos que bordean el bolsillo se almacenan como `PDBResidueSet` con nombre `FPocketPocket` y se visualizan en el visor 3D interactivo.

### P2Rank
**Herramienta:** P2Rank v2.x (modelo de aprendizaje automático)  
P2Rank usa un clasificador de bosque aleatorio (random forest) entrenado sobre ~15.000 estructuras del PDB. Para cada punto de la superficie proteica, calcula una probabilidad de ser parte de un sitio de unión a ligando, basándose en descriptores locales (accesibilidad al solvente, hidrofobicidad, evolución local de secuencia, etc.).

Los resultados se almacenan como `PDBResidueSet` con nombre `P2RankPocket`. La tabla muestra:
- **Score**: puntuación bruta del modelo
- **Probability**: probabilidad calibrada (0–1) de que sea un sitio de unión real. ≥ 0.5 = alta; 0.2–0.49 = media; < 0.2 = baja.

---

## Anotación funcional: GO y EC

### Gene Ontology (GO)
**Fuentes (en orden de ejecución):**

1. **InterProScan (etapa 11):** el TSV de InterProScan incluye términos GO en la columna 14, asignados por las bases de datos internas de InterPro (Pfam, HAMAP, PANTHER, etc.) cuando reconocen un dominio o familia en la secuencia. Estos GO se cargan directamente con `load_interpro` como crossrefs de la proteína.

2. **UniProt (etapa 13):** para proteínas con UniProt ID mapeado, `fetch_uniprot_annotations` descarga los términos GO directamente desde UniProt (que los curó manualmente o los importó de fuentes especializadas). Estos complementan los de InterProScan.

**Aspectos cubiertos por GO:**
- Función molecular: actividad bioquímica directa (ej. GO:0016787 — actividad hidrolasa)
- Proceso biológico: proceso celular en el que participa (ej. GO:0009245 — biosíntesis de lípido A)
- Componente celular: localización subcelular (ej. GO:0016020 — membrana)

### Número EC (Enzyme Commission)
**Fuentes:**  
1. **InterProScan (etapa 11):** algunas bases de datos de InterPro (especialmente HAMAP, NCBIfam, PIRSF) incluyen números EC en la columna 15 del TSV, en formato `EC:x.x.x.x`. Estos se cargan junto con los dominios.  
2. **UniProt (etapa 13):** si la proteína tiene UniProt ID, `fetch_uniprot_annotations` descarga los EC asignados en UniProt, que incluyen tanto asignaciones experimentales como inferidas.

**Nota:** si el genoma no tiene mapeo UniProt (porque sus accesiones no son reconocidas por la API de UniProt, como ocurre con locus tags tipo `VK055_xxxx`) y el TSV de InterProScan no incluyó líneas EC para esas proteínas, EC = 0 es el resultado esperado y correcto.

---

## Features de secuencia (dominios)

**Etapas:** 10 (`interproscan` remoto en SLURM) → 11 (`load_interpro`)

**Herramienta:** InterProScan v5.x  
InterProScan integra múltiples bases de datos de familias y dominios de proteínas. Para cada proteína del genoma, corre análisis con cada una de las siguientes herramientas y guarda los hits con sus coordenadas de inicio/fin:

| Base de datos | Qué identifica |
|---|---|
| **Pfam** | Dominios proteicos conservados (la BD más usada en anotación) |
| **HAMAP** | Familias de proteínas procariontes con función caracterizada |
| **NCBIfam** | Familias de NCBI, incluye HMMs de TIGRfam legado |
| **PANTHER** | Familias y subfamilias con función evolutiva inferida |
| **Gene3D** | Dominios estructurales basados en clasificación CATH |
| **SUPERFAMILY** | Dominios basados en clasificación SCOP |
| **PIRSF** | Familias de proteínas completas con función específica |
| **PRINTS** | Fingerprints de motivos característicos de familia |
| **ProSitePatterns** | Patrones de secuencia diagnósticos (regex sobre secuencia) |
| **ProSiteProfiles** | Perfiles de secuencia más sensibles que los patrones |
| **SMART** | Dominios de señalización y regulación |
| **SFLD** | Superfamilias enzimáticas con función mecanística |
| **CDD** | Dominios conservados del NCBI |
| **FunFam** | Subfamilias funcionales dentro de Gene3D |
| **Phobius** | Péptidos señal y dominios transmembrana (combinado) |
| **SignalP_GRAM_NEGATIVE** | Péptidos señal en bacterias Gram negativas |
| **SignalP_GRAM_POSITIVE** | Péptidos señal en bacterias Gram positivas |
| **SignalP_EUK** | Péptidos señal en eucariotas |
| **TMHMM** | Dominios transmembrana (modelo de Markov oculto) |
| **MobiDBLite** | Regiones de desorden intrínseco |
| **Coils** | Regiones coiled-coil |

El resultado es un archivo TSV con 15 columnas. Cada fila es un hit de una base de datos sobre un rango de residuos de la proteína. `load_interpro` importa este TSV a la tabla `SeqFeature` de la base de datos.

---

## Perfil de target

### Human off-target
**Etapas:** 4 (`fasttarget`) → 5 (`load_score human_offtarget`)

**Herramienta:** FastTarget, que internamente usa DIAMOND (BLASTP ultrarrápido)  
**Base de datos de referencia:** proteoma humano completo (UniProt/Swiss-Prot + TrEMBL)  
**Umbral de hit:** e-value ≤ 1×10⁻⁵  
**Resultado guardado:** `hit` (hay al menos un match humano al umbral) o `no_hit`  
También se guardan `human_identity` (% de identidad del mejor alineamiento) y `human_evalue` (e-value del mejor alineamiento).  
**Interpretación:** `no_hit` es el resultado deseable para un blanco terapéutico en el patógeno, ya que reduce el riesgo de toxicidad cruzada hacia el huésped.

### Gut microbiome off-target
**Etapas:** 4 (`fasttarget`) → 6 (`load_score micro_offtarget`)

**Herramienta:** FastTarget / DIAMOND BLASTP  
**Base de datos de referencia:** genomas de referencia del microbioma intestinal humano (colección curada de especies comensales)  
**Umbral de hit:** identidad de secuencia > 40% AND cobertura de query > 70%  
**Resultado:** `hit` o `no_hit`  
**Interpretación:** un fármaco que inhibe una proteína con hit en microbioma podría afectar la microbiota intestinal beneficiosa. `no_hit` es preferible para un blanco selectivo.

### Essential (DEG)
**Etapas:** 4 (`fasttarget`) → 7 (`load_score essenciality`)

**Herramienta:** FastTarget / DIAMOND BLASTP  
**Base de datos de referencia:** DEG — *Database of Essential Genes* (genes confirmados como esenciales por experimentos de mutagénesis transposónica, deleción o competencia en organismos model)  
**Resultado:** `Y` (tiene homólogo en DEG) o `N`  
También se guardan `deg_identity` y `deg_evalue`.  
**Interpretación:** una proteína con homólogo en DEG tiene mayor probabilidad de ser esencial para la viabilidad del organismo patógeno, lo que la hace un blanco atractivo (inhibirla podría ser letal para la bacteria).

### Localization (localización subcelular)
**Etapas:** 20 (`psort`) → 21 (`load_score psort`)

**Herramienta:** PSORTb v3.x  
PSORTb usa un clasificador de máquina de soporte vectorial (SVM) entrenado sobre proteínas bacterianas con localización experimental confirmada. Analiza señales de secuencia: péptido señal, ancla lipoprotéica, dominios transmembrana, motivos de retención en membrana, etc.  
**Categorías posibles:** Cytoplasmic, CytoplasmicMembrane, Periplasmic, OuterMembrane, Extracellular, Unknown  
**Interpretación:** proteínas de membrana externa, periplasma y superficie extracelular son más accesibles para anticuerpos y moléculas grandes. Las citoplasmáticas requieren que el compuesto penetre ambas membranas (en Gram negativos).

### ColabFold pLDDT
Ver sección Estructura 3D.

---

## Evidencia de ligandos (binders)

**Etapa:** 24 (`ligq_remote`) — LigQ_2 corriendo en nodo SLURM

### Flujo de LigQ_2

1. TPW exporta un archivo FASTA con todas las proteínas del genoma.
2. El FASTA se transfiere por SCP al nodo del cluster.
3. LigQ_2 corre BLAST/HMMER contra sus bases de datos internas para cada proteína.
4. LigQ_2 busca en PDB y ChEMBL proteínas similares y recupera sus ligandos.
5. Para ZINC, genera candidatos por similaridad química (Tanimoto) a binders ya conocidos.
6. El output (TSV por proteína) se transfiere de vuelta al servidor.
7. `load_ligq_2_results` importa los resultados a la tabla `Binders` de la base de datos.

### Tipos de evidencia y límites aplicados

| Tipo | Fuente | Criterio de inclusión | Límite por proteína |
|---|---|---|---|
| **PDB co-crystal (directa)** | PDB | El UniProt del registro PDB coincide con el UniProt de esta proteína | Sin límite (todos los ligandos co-cristalizados) |
| **PDB via homologs** | PDB | El UniProt del registro PDB es de una proteína similar (no idéntica) | Sin límite |
| **ChEMBL bioactive (directa)** | ChEMBL | El UniProt del target ChEMBL coincide con el UniProt de esta proteína | Top 100 por pChEMBL (potencia) descendente |
| **ChEMBL via homologs** | ChEMBL | Target ChEMBL es proteína similar | Top 100 por pChEMBL descendente |
| **ZINC proposed** | ZINC | Similaridad química Tanimoto ≥ 0.5 con binders conocidos | Top 50 por Tanimoto descendente |

**pChEMBL:** logaritmo negativo de la potencia (IC50, Ki, Kd, etc.) en escala molar. pChEMBL = 6 equivale a IC50 = 1 µM. Mayor pChEMBL = mayor potencia.

**Tanimoto (coeficiente de Jaccard sobre fingerprints moleculares):** mide similaridad química entre dos moléculas. 1.0 = idénticas; 0.5 es el umbral mínimo aplicado; moléculas por encima de ese umbral son "quimicamente similares" a un binder conocido.

### Filtro de ligandos no relevantes (HET denylist)
Al cargar los resultados de LigQ_2, se eliminan automáticamente compuestos que típicamente son ruido de cristalización y no tienen relevancia farmacológica:
- Todos los 20 aminoácidos estándar (ALA, ARG, ASN, … VAL)
- Agua (HOH, DOD, WAT)
- Iones metálicos simples (NA, K, MG, CA, CL, ZN, FE, CU, MN, CO, NI, CD, HG, etc.)
- Crioprotectores y agentes de cristalización (GOL, EDO, MPD, PEG, PG4, etc.)
- Tampones y solventes (TRS, DMS, BME, EPE, MES, etc.)
- Sales (SO4, PO4, NO3, CO3, etc.)

### Directo vs. por homología
Un binder se marca como **directo** (`is_direct=True`) cuando el identificador UniProt que devuelve LigQ_2 para ese binder coincide exactamente con uno de los crossrefs UniProt (`UnipSp` o `UnipTr`) de la proteína en la base de datos de TPW.

Esto requiere que la proteína haya sido mapeada a UniProt en la etapa 12 (`gbk2uniprot_map`). Si el genoma usa locus tags que UniProt no reconoce (como `VK055_xxxx`), el mapeo falla y toda la evidencia aparece como "via homologs" aunque la proteína sea en realidad el mismo target.

---

## Propiedades fisicoquímicas de los ligandos

Todos los descriptores se calculan a partir del **SMILES** del ligando usando la biblioteca **RDKit** (v2023+), en el momento en que se carga la página. No son valores experimentales, sino predicciones basadas en la estructura química.

### MW — Peso molecular (Da)
**Cálculo:** `RDKit.Chem.Descriptors.MolWt(mol)`  
Peso molecular promedio considerando las abundancias isotópicas naturales.  
**Referencia:** Lipinski et al. proponen ≤ 500 Da para permeabilidad oral. Valores > 500 Da no necesariamente son problemáticos para antibióticos (muchos beta-lactámicos y glicopéptidos superan ese valor).

### LogP — Lipofilicidad
**Cálculo:** `RDKit.Chem.Crippen.MolLogP(mol)` (método de Crippen, contribuciones atómicas)  
Logaritmo del coeficiente de distribución octanol/agua. Mide cuán "grasa" es la molécula.  
- Valores muy negativos (< −2): muy hidrosoluble, mala permeabilidad de membrana
- 0–3: equilibrio favorable para muchos fármacos
- > 5: muy lipofílica, potencial problema de toxicidad y metabolismo

### TPSA — Área polar de superficie topológica (Å²)
**Cálculo:** `RDKit.Chem.Descriptors.TPSA(mol)`  
Suma de las áreas de la superficie molecular ocupadas por átomos polares (oxígeno, nitrógeno y sus hidrógenos). Indica cuánta superficie de la molécula es polar.  
- < 140 Å²: criterio de Veber para buena biodisponibilidad oral
- < 60 Å²: mejor penetración de membrana bacteriana de doble capa

### Lipinski Ro5 (Rule of Five)
**Cálculo:** TPW verifica estas 4 condiciones con RDKit:
1. Peso molecular ≤ 500 Da
2. LogP ≤ 5
3. Donadores de puente hidrógeno (NH + OH) ≤ 5 — `RDKit.Chem.Lipinski.NumHDonors(mol)`
4. Aceptores de puente hidrógeno (N + O) ≤ 10 — `RDKit.Chem.Lipinski.NumHAcceptors(mol)`

Se cuenta cuántas reglas se violan (0, 1 o 2+):
- `✓ Ro5`: 0 violaciones — cumple todos los criterios
- `1 viol.`: 1 violación — uso con precaución
- `N viol.`: ≥ 2 violaciones — problemas de drug-likeness oral esperables

**Referencia:** Lipinski CA et al. (1997). *Adv Drug Deliv Rev* 23(1-3):3–25.  
**Nota:** la "Rule of 5" es una guía estadística para fármacos orales, no una regla absoluta. Muchos antibióticos aprobados la violan (vancomicina, eritromicina, etc.). Para agentes de administración parenteral, los criterios son más laxos.

### PAINS (Pan-Assay Interference Compounds)
**Cálculo:** `RDKit.Chem.FilterCatalog` con el catálogo `PAINS` (catálogo de Baell & Holloway)  
PAINS son subestructuras químicas que tienden a dar resultados falsos positivos en ensayos de cribado de alta capacidad (HTS) mediante mecanismos no específicos: reactividad química promiscua, interferencia óptica (fluorescencia), o unión a múltiples blancos.

- `✓ Clean` (en la plataforma se muestra como `✓ Clean`): el compuesto no contiene subestructuras PAINS conocidas
- `Alert`: contiene al menos una subestructura PAINS — requiere validación experimental adicional

**Referencia:** Baell JB & Holloway GA (2010). *J Med Chem* 53(7):2719–2740.  
**Nota:** un compuesto con alerta PAINS no es automáticamente descartable, pero su actividad debe verificarse con ensayos ortogonales.

---

## Consideraciones de interpretación

- **Toda la evidencia es computacional** excepto los binders de tipo PDB co-crystal (experimental) y ChEMBL directos (bioactividad medida in vitro/in vivo).
- **La ausencia de un dato no es ausencia de propiedad**: EC=0 puede significar que esa proteína genuinamente no tiene función enzimática caracterizada, o que el pipeline no encontró homología suficiente, o que la herramienta no fue configurada para ese análisis.
- **Los scores de druggability son descriptores estructurales**, no predictores de actividad biológica ni de toxicidad.
- **La esencialidad por DEG es transferida**: la proteína puede ser esencial en el organismo de referencia de DEG pero no necesariamente en el patógeno estudiado, y viceversa.
- **Los modelos ColabFold y AlphaFold tienen errores sistemáticos** en regiones intrínsecamente desordenadas, proteínas de membrana, y proteínas sin homólogos conocidos. El pLDDT es el indicador de confianza: no usar el modelo para análisis de bolsillos en regiones con pLDDT < 50.
- **Las propiedades fisicoquímicas (Lipinski, TPSA, LogP)** se calculan desde SMILES y son valores computados, no experimentales.
