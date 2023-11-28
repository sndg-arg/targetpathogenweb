from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider, SlurmProvider
from parsl.channels import LocalChannel, SSHChannel
from parsl.launchers import SrunLauncher
from parsl.addresses import address_by_hostname, address_by_query
from parsl.monitoring.monitoring import MonitoringHub
import os

ht_executor = HighThroughputExecutor(
    working_dir=os.getcwd(),
    label="local_executor",
    provider=LocalProvider(channel=LocalChannel(),
                           min_blocks=1,
                           max_blocks=1,
                           parallelism=0,
                           nodes_per_block=1,
                           worker_init="export DJANGO_DEBUG=True;export DJANGO_SETTINGS_MODULE=tpwebconfig.settings;\
                export DJANGO_DATABASE_URL=psql://postgres:123@127.0.0.1:5432/tp;\
                export CELERY_BROKER_URL=redis://localhost:6379/0;\
                export PYTHONPATH=$PYTHONPATH:../sndgjobs:../sndgbiodb:../targetpathogen:../sndg-bio;\
                conda activate tpv2"),
    max_workers=4,

)

slurm_executor = HighThroughputExecutor(
    label="slurm_executor",
    working_dir = "/home/rterra/",
    worker_logdir_root="/home/rterra",
    provider = LocalProvider(channel=SSHChannel(
        username=os.getenv('SSH_USERNAME'),
        password=os.getenv('SSH_PASSWORD'),
        hostname='cluster.qb.fcen.uba.ar',
        script_dir='/home/rterra/slurm_target_tests'
    )
)
)
cfg = Config(monitoring=MonitoringHub(
    hub_address=address_by_hostname(),
    monitoring_debug=False,
    resource_monitoring_interval=10,
    ),
    executors=[ht_executor, slurm_executor]
)



