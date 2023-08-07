# targetpathogenweb
Target Pathogen Webapp Project
mkdir -p dbs/db
docker run -u $(id -u ${USER}):$(id -g ${USER}) -p 5432:5432 --rm --name sndgr -v $PWD/dbs/db:/var/lib/postgresql/data \
-e POSTGRES_PASSWORD=123 -e POSTGRES_DB=tp  -v /etc/passwd:/etc/passwd:ro --shm-size 512m postgres:14

docker run --rm -v $PWD/dbs/dbc:/data -u $(id -u ${USER}):$(id -g ${USER}) --shm-size 512m --name sndgc -p 6379:6379 redis
# tiene que existir dbc con todos los permisos

docker build ./ -t sndgwebapp -f image/Dockerfile

pip install -r requirements/base.txt
pip install -r requirements/dev.txt

./manage.py shell_plus --ipython --print-sql

export PYTHONPATH=$PYTHONPATH:../sndg/sndg-jobs

export DJANGO_SETTINGS_MODULE=tpwebconfig.settings;
export DJANGO_DATABASE_URL=psql://postgres:123@127.0.0.1:5432/tp;
export CELERY_BROKER_URL=redis://localhost:6379/0;
export DJANGO_DEBUG=True


celery -A config.celery_app worker --loglevel=info


Test celery task
from sndgjobs.tasks.submit_job_task import submit_job_task


TODO
- allauth
- celery
- throttle
- API Key