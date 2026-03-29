import os
import sys
import configparser
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider
from parsl.channels import LocalChannel
from parsl.monitoring.monitoring import MonitoringHub
from parsl.addresses import address_by_hostname


def _pipeline_shared_dir():
    default_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "parsl")
    )
    return os.environ.get("TPW_PIPELINE_SHARED_DIR", default_dir)


def _pipeline_run_dir():
    shared_run_dir = os.environ.get("TPW_PIPELINE_RUN_DIR")
    if shared_run_dir:
        return shared_run_dir
    return os.path.join(_pipeline_shared_dir(), "runinfo")

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
        python_bin_dir = os.path.dirname(sys.executable)
        runtime_path = os.environ.get("PATH", "").strip()
        if python_bin_dir:
            runtime_path = (
                f"{python_bin_dir}:{runtime_path}" if runtime_path else python_bin_dir
            )
        runtime_pythonpath = os.environ.get("PYTHONPATH", "").strip()
        if runtime_path:
            env += f"export PATH={runtime_path}:$PATH\n"
        if runtime_pythonpath:
            env += f"export PYTHONPATH={runtime_pythonpath}:$PYTHONPATH\n"
        monitoring_flag = self.config.getboolean("GENERAL", "Monitoring", fallback=False)
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

        if monitoring_flag:
            monitoring = MonitoringHub(
                hub_address=address_by_hostname(),
                monitoring_debug=False,
                resource_monitoring_interval=10,
            )
        else:
            monitoring = None

        run_dir = _pipeline_run_dir()
        os.makedirs(run_dir, exist_ok=True)

        cfg = Config(monitoring=monitoring,
                     executors=[self.ht_executor],
                     run_dir=run_dir,
                     )
        return cfg
