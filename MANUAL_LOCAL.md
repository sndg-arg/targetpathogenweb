# Manual Local y Criterio Cluster

Actualizado: 2026-03-06 (operativa local diaria + monitoreo).

Objetivo: correr en Mac sin alejarse de `prod`, y evitar cambios locales que degraden resultados en cluster.

## Operativa rápida (día a día)

### 1) Levantar la app local (sin pipeline)
```bash
cd /Users/ani/Desktop/Exactas/targetpathogenweb
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d --pull never
docker compose ps
open http://localhost:8085
```
Que hace:
- `cd ...`: te posiciona en el repo.
- `DOCKER_DEFAULT_PLATFORM=linux/amd64 ... up -d`: levanta servicios en background usando arquitectura amd64 (util en Mac).
- `docker compose ps`: confirma que `db` y `web` quedaron en `Up`.
- `open ...`: abre la app en el navegador.

### 2) Ver salud general
```bash
curl -s http://localhost:8085/health/live
curl -s http://localhost:8085/health/ready
curl -s http://localhost:8085/health/pipeline
```
Que hace:
- `/health/live`: dice si el proceso web esta vivo.
- `/health/ready`: valida si la app esta lista para atender requests (incluye dependencias como DB).
- `/health/pipeline`: muestra estado del ultimo pipeline (running/stage/run_id).

### 3) Borrar corridas viejas (runinfo + logs) sin borrar datos biológicos
Esto limpia el estado de pipeline mostrado en UI, pero no borra genomas/proteínas cargados en DB.
```bash
docker exec target2_nodo0 bash -lc '
  rm -rf /app/targetpathogenweb/parsl/runinfo/* \
         /app/targetpathogenweb/runinfo/* \
         /tmp/tpw_pipeline_test.log \
         /tmp/tpw_pipeline_test.pid
  mkdir -p /app/targetpathogenweb/parsl/runinfo /app/targetpathogenweb/runinfo
'
```
Que hace:
- borra metadatos de ejecucion anteriores (`runinfo`) y logs temporales.
- recrea carpetas vacias para que el siguiente run empiece limpio.

### 4) Correr pipeline de test desde cero (en background)
```bash
docker exec target2_nodo0 bash -lc '
  cd /app/targetpathogenweb/parsl
  source /opt/conda/etc/profile.d/conda.sh
  conda activate tpv2
  source exports.sh
  export PYTHONPATH=/app/targetpathogenweb/parsl:/app/targetpathogenweb:$PYTHONPATH
  nohup python run_pipeline.py --test > /tmp/tpw_pipeline_test.log 2>&1 &
  echo $! > /tmp/tpw_pipeline_test.pid
  echo "started pid $(cat /tmp/tpw_pipeline_test.pid)"
'
```
Que hace:
- entra al contenedor `web`.
- activa conda env `tpv2`.
- carga `exports.sh` y `PYTHONPATH` del proyecto/parsl.
- ejecuta `run_pipeline.py --test` en background y guarda:
  - log en `/tmp/tpw_pipeline_test.log`
  - pid en `/tmp/tpw_pipeline_test.pid`

### 5) Ver si está corriendo y por qué etapa va
```bash
curl -s http://localhost:8085/health/pipeline
docker exec target2_nodo0 bash -lc 'tail -f /tmp/tpw_pipeline_test.log'
docker exec target2_nodo0 bash -lc 'ps -eo pid,args | grep -E "run_pipeline.py|process_worker_pool.py|fasttarget.py" | grep -v grep'
```
Que hace:
- `health/pipeline`: etapa actual (ej: `stage_current 4/21`) y estado.
- `tail -f`: seguimiento en vivo del log.
- `ps ...`: verifica procesos reales del pipeline.

Tip: para monitoreo rápido en terminal:
```bash
watch -n 5 'curl -s http://localhost:8085/health/pipeline'
```
Que hace:
- refresca cada 5 segundos el estado del pipeline en la terminal.

### 6) Frenar pipeline en curso (si se clavó)
```bash
docker exec target2_nodo0 bash -lc '
  pids=$(ps -eo pid,args | grep -E "python .*run_pipeline.py|process_worker_pool.py|fasttarget.py" | grep -v grep | awk "{print \$1}" || true)
  [ -n "$pids" ] && echo "$pids" | xargs -r kill -TERM
  sleep 2
  pids=$(ps -eo pid,args | grep -E "python .*run_pipeline.py|process_worker_pool.py|fasttarget.py" | grep -v grep | awk "{print \$1}" || true)
  [ -n "$pids" ] && echo "$pids" | xargs -r kill -KILL
'
```
Que hace:
- intenta cierre ordenado con `SIGTERM`.
- espera 2 segundos.
- si sigue vivo, fuerza cierre con `SIGKILL`.

### 7) Limpieza total del genoma de test (opcional, destructiva)
Útil si querés “arrancar de cero” también en archivos de salida.
```bash
docker exec target2_nodo0 bash -lc '
  rm -rf /app/targetpathogenweb/data/023/NZ_AP023069.1
  rm -rf /app/fasttarget/organism/NZ_AP023069.1
'
```
Que hace:
- elimina resultados del genoma de test en `data/` y `fasttarget/organism/`.
- no usar si queres conservar artefactos de una corrida.

### 8) Entrar al contenedor y ejecutar manualmente
```bash
docker exec -it target2_nodo0 bash
source /opt/conda/etc/profile.d/conda.sh
conda activate tpv2
cd /app/targetpathogenweb/parsl
source exports.sh
export TPW_PROFILE=local
python run_pipeline.py --test
```
Que hace:
- modo interactivo para debug paso a paso dentro del contenedor.
- `TPW_PROFILE=local` aplica defaults mas amigables para entorno local.

### 9) Apagar contenedores
Apagado normal (recomendado para cortar y seguir luego):
```bash
cd /Users/ani/Desktop/Exactas/targetpathogenweb
docker compose stop
```
Que hace:
- detiene `web` y `db` sin borrar nada (ni red, ni volúmenes, ni contenedores).

Apagado con limpieza de contenedores/red del compose:
```bash
cd /Users/ani/Desktop/Exactas/targetpathogenweb
docker compose down
```
Que hace:
- detiene y elimina contenedores y red del proyecto.
- los datos persisten si estan en volúmenes/bind mounts.

Apagado total (destructivo para volumenes de compose):
```bash
cd /Users/ani/Desktop/Exactas/targetpathogenweb
docker compose down -v
```
Que hace:
- igual que `down`, pero tambien elimina volúmenes de compose.
- usar solo si realmente queres limpiar estado persistente.

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
