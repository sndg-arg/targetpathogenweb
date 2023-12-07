import os
import configparser
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider
from parsl.channels import LocalChannel
from parsl.monitoring.monitoring import MonitoringHub
from parsl.addresses import address_by_hostname

class borg(object):
    def __init__(self, my_class):
        self.my_class = my_class
        self.my_instance = None

    def __call__(self, *args, **kwargs):
        if self.my_instance is None:
            self.my_instance = self.my_class(*args, **kwargs)
        return self.my_instance

@borg
class TargetConfig():
    def __init__(self, config_file=None) -> None:
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        if self.config_file is not None:
            self.config.read(self.config_file)

    def get_config_dict(self):
        return self.config

    def get_parsl_cfg(self):
        env = ""
        if self.config.get("GENERAL", "EnvironmentFile", fallback=None):
            with open(self.config.get("GENERAL", "EnvironmentFile"), 'r') as f:
                env = f.read()
        self.ht_executor = HighThroughputExecutor(
            working_dir=self.config.get("GENERAL", "WorkingDir", fallback=os.getcwd()),
            label="local_executor",
            max_workers=int(self.config.get("GENERAL", "MaxWorkers", fallback=1)),
            provider=LocalProvider(channel=LocalChannel(),
                                   min_blocks=1,
                                   max_blocks=1,
                                   parallelism=0,
                                   nodes_per_block=1,
                                   worker_init=env),
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
                     executors=[self.ht_executor]
                     )
        return cfg
