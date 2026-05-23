import os
import sys
import configparser
import threading
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


def _clean_text(value):
    text = str(value or "").strip()
    return text or None


def _env_text(name, fallback=None):
    return _clean_text(os.environ.get(name)) or fallback


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default=0):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default

class borg(object):
    def __init__(self, my_class):
        self.my_class = my_class
        self.my_instance = None
        self._lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        if self.my_instance is None:
            with self._lock:
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

    def get_text(self, section, option, *, env_name=None, fallback=None):
        env_value = _env_text(env_name) if env_name else None
        if env_value is not None:
            return env_value
        config_value = _clean_text(self.config.get(section, option, fallback=None))
        if config_value is not None:
            return config_value
        return fallback

    def get_bool(self, section, option, *, env_name=None, fallback=False):
        if env_name and os.environ.get(env_name) is not None:
            return _env_bool(env_name, default=fallback)
        raw = _clean_text(self.config.get(section, option, fallback=None))
        if raw is None:
            return fallback
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def get_int(self, section, option, *, env_name=None, fallback=0):
        if env_name and os.environ.get(env_name) is not None:
            return _env_int(env_name, default=fallback)
        raw = _clean_text(self.config.get(section, option, fallback=None))
        if raw is None:
            return fallback
        try:
            return int(raw)
        except (TypeError, ValueError):
            return fallback

    def get_parsl_cfg(self):
        env = ""
        environment_file = self.get_text(
            "GENERAL",
            "EnvironmentFile",
            env_name="TPW_PIPELINE_ENV_FILE",
        )
        if environment_file:
            with open(environment_file, 'r') as f:
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
        monitoring_flag = self.get_bool(
            "GENERAL",
            "Monitoring",
            env_name="TPW_PIPELINE_MONITORING",
            fallback=False,
        )
        working_dir = self.get_text(
            "GENERAL",
            "WorkingDir",
            env_name="TPW_PIPELINE_WORKING_DIR",
            fallback=os.getcwd(),
        )
        max_workers = self.get_int(
            "GENERAL",
            "MaxWorkers",
            env_name="TPW_PIPELINE_MAX_WORKERS",
            fallback=1,
        )
        self.ht_executor = HighThroughputExecutor(
            working_dir=working_dir,
            label="local_executor",
            max_workers=max_workers,
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

        retries = self.get_int(
            "GENERAL",
            "Retries",
            env_name="TPW_PIPELINE_RETRIES",
            fallback=1,
        )

        cfg = Config(monitoring=monitoring,
                     executors=[self.ht_executor],
                     run_dir=run_dir,
                     retries=retries,
                     )
        return cfg
