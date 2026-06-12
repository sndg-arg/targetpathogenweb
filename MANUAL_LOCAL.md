# Manual Local

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

## Perfiles de ejecución

### Cluster-safe (por defecto)
```bash
cd /app/targetpathogenweb/parsl
source exports.sh
# TPW_PROFILE default = cluster
python run_pipeline.py --test
```

### Local (Mac, sin degradar calidad por defecto)
```bash
source exports.sh
export TPW_PROFILE=local
python run_pipeline.py --test
```

Variables opcionales para debugging local rápido (aceptan tablas fallback temporales):
```bash
export TPW_FASTTARGET_ALLOW_FALLBACK=1
export FASTTARGET_TIMEOUT_SEC=30
```

## Logs y verificación

- Log principal: `parsl/runinfo/<run_id>/parsl.log`
- Logs por tarea: `parsl/runinfo/<run_id>/task_logs/0000/task_*.stderr|stdout`
- Ver `_af.pdb` generados:
```bash
find data -type f -name '*_af.pdb' | wc -l
```

## Archivos cluster-safe para commitear

Estos archivos son seguros para la rama productiva:
- `.gitignore`
- `parsl/exports.sh`
- `parsl/apps.py`
- `tpweb/management/commands/fast_command.py`
- `tpweb/management/commands/get_binders.py`
- `tpweb/management/commands/index_genome_seq_clean.py`

No commitear a prod:
- `docker-compose.override.yml`
- `parsl/settings.ini` (credenciales/rutas personales)
