from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider, SlurmProvider
from parsl.channels import LocalChannel, SSHChannel
from parsl.launchers import SrunLauncher, SimpleLauncher
from parsl.addresses import address_by_hostname, address_by_query
from parsl.monitoring.monitoring import MonitoringHub
import os
import configparser


class borg(object):
    def __init__(self, my_class):
        self.my_class = my_class
        self.my_instance = None

    def __call__(self, *args, **kwargs):
        if self.my_instance == None:
            self.my_instance = self.my_class(*args, **kwargs)
        return self.my_instance


@borg
class TargetConfig():
    def __init__(self, config_file) -> None:
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.config.read(self.config_file)

    def get_config_dict(self):
        return self.config

    def get_parsl_cfg(self):
        env = ""
        ssh_env = ""
        if self.config.get("GENERAL", "EnvironmentFile", fallback=None):
            with open(self.config.get("GENERAL", "EnvironmentFile"), 'r') as f:
                env = f.read()
        if self.config.get("SSH", "EnvironmentFile", fallback=None):
            with open(self.config.get("SSH", "EnvironmentFile"), 'r') as f:
                ssh_env = f.read()

        ht_executor = HighThroughputExecutor(
            working_dir=self.config.get(
                "GENERAL", "WorkingDir", fallback=os.getcwd()),
            label="local_executor",
            max_workers=int(self.config.get(
                "GENERAL", "MaxWorkers", fallback=1)),
            provider=LocalProvider(channel=LocalChannel(),
                                   min_blocks=1,
                                   max_blocks=1,
                                   parallelism=0,
                                   nodes_per_block=1,
                                   worker_init=env),
        )

        slurm_executor = HighThroughputExecutor(
            label="slurm_executor",
            max_workers=int(self.config.get("SSH", "MaxWorkers", fallback=1)),
            cores_per_worker=int(self.config.get(
                "SSH", "CoresPerWorker", fallback=1)),
            working_dir=self.config.get("SSH", "WorkingDir"),
            worker_logdir_root=self.config.get("SSH", "WorkingDir"),
            provider=LocalProvider(
                worker_init=ssh_env,
                channel=SSHChannel(
                    username=self.config.get(
                        "SSH", "Username", fallback=os.getenv('SSH_USERNAME')),
                    password=self.config.get(
                        "SSH", "Password", fallback=os.getenv('SSH_PASSWORD')),
                    hostname=self.config.get(
                        "SSH", "HostName", fallback='cluster.qb.fcen.uba.ar'),
                    script_dir=self.config.get("SSH", "WorkingDir")
                ),
                launcher=SimpleLauncher(),

            )
        )
        if self.config.getboolean("GENERAL", "Monitoring", fallback=False):
            monitoring = MonitoringHub(
                hub_address=address_by_hostname(),
                monitoring_debug=True,
                resource_monitoring_interval=10,
            )
        else:
            monitoring = None

        cfg = Config(monitoring=monitoring,
                     executors=[ht_executor, slurm_executor]
                     )
        return cfg
