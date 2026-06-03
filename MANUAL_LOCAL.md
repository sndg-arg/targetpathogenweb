# Manual Local y Criterio Cluster

Actualizado: 2026-03-04 (run local validado end-to-end).

Objetivo: correr en Mac sin alejarse de `prod`, y evitar cambios locales que degraden resultados en cluster.

## Estado funcional observado
- Run `036` generó 44 archivos `*_af.pdb` (animación 3D recuperada).
- El cuello real era `get_binders` (`exit -9`, OOM local) al cargar BioLiP + `components.cif` completos en RAM.
- Se aplicó fix en `tpweb/management/commands/get_binders.py`:
  - lectura streaming de BioLiP (filtro temprano por UniProt/Ligand),
  - parseo selectivo de `components.cif` solo para ligandos necesarios,
  - sin cargar datasets completos en memoria.
- Se aplicó fix en `tpweb/management/commands/fast_command.py`:
  - timeout de FastTarget con cierre de process-group completo (`SIGTERM`/`SIGKILL`),
  - evita procesos huérfanos `fasttarget.py` tras timeout local.
- Validación post-fix (2026-03-04):
  - `python manage.py get_binders NZ_AP023069.1 --datadir ../data` terminó OK en ~8.3s,
  - `python manage.py load_binders NZ_AP023069.1 --datadir ../data` terminó OK.
  - `python run_pipeline.py --test` (runinfo `003`) completó OK; `Task 63/64` finalizaron sin `exit -9`; 44 `*_af.pdb` generados.

### Verificación adicional (2026-03-04, run 037)
- Se levantaron contenedores y se validó `python manage.py check` OK tras instalar `setuptools==68.2.2` en `tpv2`.
- El pipeline `python run_pipeline.py --test` inició correctamente pero quedó ejecutando `Task 4 (fasttarget)` por varios minutos sin completar durante la ventana de prueba.
- Se interrumpió manualmente para no bloquear la sesión; no llegó a etapas posteriores en este intento.
- Conclusión: el flujo arranca, pero la etapa `fasttarget` en modo estricto puede ser muy lenta o quedar pendiente de recursos externos.

## Inventario de cambios y decisión
| Archivo | Uso real | ¿Necesario local? | ¿Riesgo cluster? | Decisión recomendada |
|---|---|---|---|---|
| `.gitignore` | Ignora archivos locales (`.DS_Store`, `fasttarget_mac/`) | Sí | Bajo | Mantener |
| `parsl/exports.sh` | Perfil `cluster/local` por flags | Sí | Bajo si defaults estrictos | Mantener |
| `parsl/apps.py` | `index_genome_seq_clean` opcional por env, overrides SSH por env, reutilización opcional de UniProt | Sí | Bajo si defaults estrictos | Mantener |
| `tpweb/management/commands/fast_command.py` | Modo estricto por default, fallback opcional, errores claros, timeout con kill de process-group (sin huérfanos) | Sí | Bajo | Mantener |
| `tpweb/management/commands/index_genome_seq_clean.py` | Solución para GFF con `<`/`>` antes de tabix | Sí (local) | Bajo (solo si flag activo) | Mantener |
| `docker-compose.override.yml` | Montajes/rutas de Mac (`fasttarget_mac`, socket SSH de Docker Desktop) | Sí | Alto si se usa en cluster | Local-only |
| Scripts parche manuales (fuera del pipeline) | Scripts de uso puntual | No | N/A | Eliminados |
| `parsl/settings.ini` | Credenciales/usuario SSH locales (`agutson`) | Sí | Alto si se sube a prod | Mantener local, no productivo |
| `Dockerfile` | Dependencias de imagen | Depende | Medio | Revisar y validar antes de merge a prod |
| `parsl/config.py` | Ajuste de monitoring | No crítico | Bajo | Opcional, revisar si aporta |
| `README.md` | Documentación general | Sí | Bajo | Mantener solo cambios genéricos |
| `tpweb/management/commands/get_binders.py` | Corrige OOM en etapa final (`get_binders`) | Sí | Bajo/positivo | Mantener (cluster-safe) |

## Auditoría de dependencias (Dockerfile + requirements)

Objetivo: reducir peso/tiempo de build sin romper ni local ni cluster.

### Dependencias claramente necesarias (mantener)
- `java` (JDK): requerido por P2Rank (`opt/p2rank/distro/prank`).
- Bio CLI en conda (`samtools`, `blast`, `bedtools`, `bcftools`): usados por indexado y scoring.
- `docker` CLI dentro del contenedor: requerido por wrappers que invocan contenedores (ej. `psort/psortb`).
- `rdkit`, `pdbecif`, `biopython`, `pandas`, `django-*` core: usados directamente por vistas/comandos.
- `django-debug-toolbar`: en debug local se importa en `tpwebconfig/urls.py`.
- `setuptools==68.2.2` previo a `pip install -r requirements.txt`: hoy evita fallas de instalación del stack actual.

### Limpieza segura (recomendada, bajo riesgo)
- `requirements.txt`:
  - eliminar duplicados (`parsl`, `scpClient`, `django-crispy-forms`, `crispy-bootstrap4` repetidos),
  - eliminar `pathlib` (stdlib en Python 3.10),
  - mantener pines actuales para no introducir drift funcional.
- Esto reduce ruido y tiempo de resolución sin cambiar comportamiento.

### Limpieza probable, pero validar con run completo
- `Dockerfile` apt:
  - `vim`: claramente opcional.
  - `nodejs` y `npm`: no forman parte del pipeline runtime; útiles solo para build/asset tasks puntuales.
  - `bioperl` y `bioperl-run`: no aparecen en el flujo principal observado, pero conviene validar por posibles scripts externos.
- Criterio: quitar en rama de prueba y validar `run_pipeline.py --test` + una corrida real de cluster antes de merge productivo.

### Recomendación de calidad para merge
- No mezclar en un mismo commit:
  1) cambios funcionales del pipeline,
  2) limpieza de dependencias,
  3) documentación.
- Hacer commits atómicos para rollback limpio si algo impacta cluster.

## Snapshot exacto hoy (qué commitear y qué no)
Estado del árbol local en `prod` (HEAD = `origin/prod`, cambios solo locales):
- **Commitear al cluster ahora (mínimo y seguro):**
  - `.gitignore`
  - `parsl/exports.sh`
  - `parsl/apps.py`
  - `tpweb/management/commands/fast_command.py`
  - `tpweb/management/commands/get_binders.py`
  - `tpweb/management/commands/index_genome_seq_clean.py`
- **No commitear (local-only):**
  - `docker-compose.override.yml`
  - `parsl/settings.ini` (usuario/rutas personales)
  - `MANUAL_LOCAL.md` (documentación local interna)
- **Dejar fuera por ahora (requiere decisión aparte):**
  - `Dockerfile`
  - `README.md` (si no queres versionar documentacion operativa)
  - `parsl/config.py`

Comandos para dejar stage limpio y consistente:
```bash
cd /Users/ani/Desktop/Exactas/targetpathogenweb

# 1) limpiar staging previo
git reset

# 2) stage SOLO lo cluster-safe/minimo
git add .gitignore \
  parsl/exports.sh \
  parsl/apps.py \
  tpweb/management/commands/fast_command.py \
  tpweb/management/commands/get_binders.py \
  tpweb/management/commands/index_genome_seq_clean.py

# 3) verificar
git status --short
```

Con eso, lo staged queda listo para un commit productivo sin arrastrar overrides locales.

## Perfil recomendado de ejecución

### Cluster-safe (por defecto)
```bash
cd /app/targetpathogenweb/parsl
source exports.sh
# TPW_PROFILE por default = cluster
python run_pipeline.py --test
```

### Local (sin degradar calidad por defecto)
```bash
cd /app/targetpathogenweb/parsl
source exports.sh
export TPW_PROFILE=local
python run_pipeline.py --test
```

Notas:
- En `local`, por default solo se habilita `TPW_USE_INDEX_GENOME_SEQ_CLEAN=1`.
- `TPW_FASTTARGET_ALLOW_FALLBACK` queda en `0` salvo override manual.
- `FASTTARGET_TIMEOUT_SEC` queda en `0` salvo override manual.
- Si querés debugging rápido y aceptás tablas fallback temporales:
```bash
export TPW_FASTTARGET_ALLOW_FALLBACK=1
export FASTTARGET_TIMEOUT_SEC=30
```

## Arranque local diario (Mac)
```bash
cd /Users/ani/Desktop/Exactas/targetpathogenweb
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d --pull never
open http://localhost:8085
```

Dentro del contenedor:
```bash
docker exec -it target2_nodo0 bash
source /opt/conda/etc/profile.d/conda.sh && conda activate tpv2
cd /app/targetpathogenweb/parsl
source exports.sh
export TPW_PROFILE=local
python run_pipeline.py --test
```

## Logs y verificación
- Log principal: `parsl/runinfo/<run_id>/parsl.log`
- Logs por tarea: `parsl/runinfo/<run_id>/task_logs/0000/task_*.stderr|stdout`
- Ver `_af.pdb` generados:
```bash
find data -type f -name '*_af.pdb' | wc -l
```

## Criterio de commit para branch productiva
- Mantener orientado a cluster-safe:
  - `parsl/exports.sh`
  - `parsl/apps.py`
  - `tpweb/management/commands/fast_command.py`
  - `tpweb/management/commands/get_binders.py`
  - `tpweb/management/commands/index_genome_seq_clean.py`
  - `.gitignore`
- Evitar en commit productivo:
  - `docker-compose.override.yml`
  - `parsl/settings.ini` con credenciales/rutas personales

## Problema pendiente real (independiente de parches locales)
- `get_binders` OOM quedó mitigado con el fix streaming de 2026-03-04.
- `run_pipeline.py --test` post-fix quedó validado sin `exit -9` en `get_binders`.
