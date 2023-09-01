# targetpathogenweb
Target Pathogen Webapp Project


# Dev install
```console
mkdir -p dbs/db
conda create -n tpv2 -c conda-forge -c bioconda python=3.10 samtools blast bedtools bcftools
conda activate tpv2

pip install -r requirements/base.txt
pip install -r requirements/dev.txt
```
## Dev run

```console
docker run -u $(id -u ${USER}):$(id -g ${USER}) -p 5432:5432 --rm --name sndgr -v $PWD/dbs/db:/var/lib/postgresql/data \
-e POSTGRES_PASSWORD=123 -e POSTGRES_DB=tp  -v /etc/passwd:/etc/passwd:ro --shm-size 512m postgres:14

export DJANGO_DEBUG=True
export DJANGO_SETTINGS_MODULE=tpwebconfig.settings
export DJANGO_DATABASE_URL=psql://postgres:123@127.0.0.1:5432/tp
export CELERY_BROKER_URL=redis://localhost:6379/0

# Add sndg-jobs / sndg-biodb / targetpathogen to pythonpath
export PYTHONPATH=$PYTHONPATH:../sndg/sndg-jobs:../sndg/sndg-biodb:../targetpathogen

# test 
./manage.py shell_plus --ipython --print-sql

./manage.py load_fpocket JFMELOJP_01523

./manage.py  load_residueset JFMELOJP_01515 data/ELO/JFMELOJP/JFMELOJP_01515_res_ann.tbl
 ./manage.py load_score_values JFMELOJP ab_props.txt 

```
# Docker image
docker build ./ -t sndgwebapp -f image/Dockerfile

echo 123 > dbs/db/.pgpass
docker exec sndgr bash -c 'PGPASSFILE=/var/lib/postgresql/data/.pgpass;pg_dump -U postgres -w -F p -d tp | gzip > /var/lib/postgresql/data/db.sql.gz'




Test celery task
from sndgjobs.tasks.submit_job_task import submit_job_task


TODO
- allauth
- celery
- throttle
- API Key