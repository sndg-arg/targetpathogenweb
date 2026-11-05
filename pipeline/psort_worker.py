"""Standalone, stdlib-only PSORTb batch runner, uploaded to SLURM nodes."""

import argparse
import csv
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


SCLBLAST_MODULE = "/usr/local/lib/x86_64-linux-gnu/perl/5.22.1/Bio/Tools/Run/SCLBlast.pm"
LOCALIZATIONS = {
    "Cytoplasmic",
    "CytoplasmicMembrane",
    "Periplasmic",
    "OuterMembrane",
    "Extracellular",
    "Cellwall",
    "Unknown",
}


def read_fasta(path):
    records = []
    name, parts = None, []
    path = Path(path)
    if not path.exists() and Path(str(path) + ".gz").exists():
        path = Path(str(path) + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith(">"):
                if name is not None:
                    records.append((name, "".join(parts)))
                header = line[1:].split()
                if not header:
                    raise ValueError("Empty FASTA identifier")
                name, parts = header[0], []
            elif line:
                if name is None:
                    raise ValueError("Sequence before FASTA header")
                parts.append(line)
    if name is not None:
        records.append((name, "".join(parts)))
    if not records or any(not seq for _, seq in records):
        raise ValueError("PSORT requires a nonempty FASTA with no empty sequences")
    if len({name for name, _ in records}) != len(records):
        raise ValueError("Duplicate FASTA identifiers")
    return records


def read_predictions(path, expected, normalized=False):
    """Require exactly one valid prediction per input protein, even on rc=0."""
    with open(path, encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, [])
        required = ("gene", "Localization") if normalized else ("SeqID", "Localization")
        if any(column not in header for column in required):
            raise ValueError(f"Invalid PSORT header in {path}: {header}")
        id_col, loc_col = (header.index(column) for column in required)
        rows = {}
        for fields in reader:
            if not fields or not any(fields):
                continue
            if len(fields) <= max(id_col, loc_col):
                raise ValueError(f"Malformed PSORT row in {path}")
            identifiers = fields[id_col].split()
            if not identifiers:
                raise ValueError(f"Empty PSORT identifier in {path}")
            name, location = identifiers[0], fields[loc_col].strip()
            if name in rows or name not in expected or location not in LOCALIZATIONS:
                raise ValueError(f"Invalid PSORT prediction: {name} {location!r}")
            rows[name] = location
    if not rows or set(rows) != set(expected):
        missing = sorted(set(expected) - set(rows))
        raise ValueError(
            "Incomplete PSORT output: {}/{}; missing {}".format(
                len(rows), len(expected), ", ".join(missing[:10])
            )
        )
    return rows


def write_predictions(path, rows, records):
    """Publish only a complete file; leave any previous valid result intact."""
    path = Path(path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=str(path.parent), delete=False
    ) as handle:
        temporary = handle.name
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["gene", "Localization"])
        for name, _ in records:
            writer.writerow([name, rows[name]])
    try:
        os.chmod(temporary, 0o644)
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_psort_file(path, fasta):
    records = read_fasta(fasta)
    return read_predictions(path, {name for name, _ in records}, normalized=True)


def instrument_module(source):
    needle = "my $bres = $brep->next_result();"
    if source.count(needle) != 1:
        raise ValueError("Unsupported PSORTb SCLBlast module; cannot add diagnostics")
    return source.replace(
        needle,
        needle + "\n"
        'die "SCLBLAST_NO_RESULT: " . $seq->display_id . '
        '" length=" . $seq->length . "\\n" unless $bres;',
    )


def _container_command(runtime, image, engine, program, arguments, batch=None, module=None):
    if engine == "apptainer":
        command = [runtime, "exec", "--cleanenv", "--containall"]
        if batch is not None:
            command += [
                "--pwd",
                "/tmp",
                "--bind",
                f"{batch}:/tmp",
                "--bind",
                f"{module}:{SCLBLAST_MODULE}:ro",
            ]
        return command + [image, program] + arguments
    if engine == "udocker":
        command = [runtime, "--quiet", "run"]
        if batch is not None:
            command += ["--volume", f"{batch}:/tmp", "--volume", f"{module}:{SCLBLAST_MODULE}"]
        return command + ["--entrypoint=" + program, image] + arguments
    if engine != "docker":
        raise ValueError(f"Unsupported PSORT container engine: {engine}")
    command = [runtime, "run", "--rm", "--pull=never", "--network=none", "--cpus=1", "--memory=2g"]
    if batch is not None:
        command += [
            "--name",
            "tpw-psort-" + batch.name,
            "--workdir",
            "/tmp",
            "--volume",
            f"{batch}:/tmp",
            "--volume",
            f"{module}:{SCLBLAST_MODULE}:ro",
        ]
    return command + ["--entrypoint", program, image] + arguments


def _run_batch(
    index, records, root, runtime, image, gram, module, timeout, engine="apptainer", containers=None
):
    cache = root / (f"batch-{index:05d}.tsv")
    expected = {name for name, _ in records}
    if cache.exists():
        try:
            return read_predictions(cache, expected, normalized=True)
        except ValueError:
            pass
    # Separate /tmp for each invocation prevents legacy tools sharing temp files.
    batch = Path(tempfile.mkdtemp(prefix=f"batch-{index:05d}-", dir=str(root)))
    (batch / "results").mkdir()
    with (batch / "input.faa").open("w", encoding="utf-8") as handle:
        for name, seq in records:
            handle.write(f">{name}\n{seq}\n")
    if containers is not None:
        image = containers.get()
    command = _container_command(
        runtime,
        image,
        engine,
        "/usr/local/psortb/bin/psort",
        ["-" + gram, "-o", "terse", "-i", "/tmp/input.faa"],
        batch,
        module,
    )
    log = batch / "psort.log"
    try:
        with log.open("w", encoding="utf-8") as handle:
            result = subprocess.run(
                command, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout
            )
        if result.returncode:
            raise ValueError(f"PSORT exited {result.returncode}")
        text = log.read_text(encoding="utf-8", errors="replace")
        if "Fatal error" in text or "SCLBLAST_NO_RESULT" in text:
            raise ValueError("PSORT reported an error despite exit code 0")
        outputs = list((batch / "results").glob("*_psortb_*.txt"))
        if len(outputs) != 1:
            raise ValueError(f"Expected one raw PSORT output, found {len(outputs)}")
        rows = read_predictions(outputs[0], expected)
        write_predictions(cache, rows, records)
        return rows
    except (ValueError, subprocess.TimeoutExpired) as exc:
        if engine == "docker" and isinstance(exc, subprocess.TimeoutExpired):
            # Killing the Docker client alone leaves its daemon-owned container running.
            subprocess.run(
                [runtime, "rm", "-f", "tpw-psort-" + batch.name],
                capture_output=True,
                timeout=30,
                check=True,
            )
        # Preserve raw output, input and logs to reproduce the failing batch.
        details = log.read_text(encoding="utf-8", errors="replace")[-1500:]
        raise RuntimeError(f"PSORT batch {index} failed; files: {batch}: {exc}\n{details}") from exc
    finally:
        if containers is not None:
            containers.put(image)


def _remove_udocker_containers(runtime, names):
    for name in names:
        try:
            subprocess.run(
                [runtime, "--quiet", "rm", name], check=True, capture_output=True, timeout=120
            )
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"Could not remove temporary PSORT container {name}: {exc}", file=sys.stderr)


def _create_udocker_containers(runtime, image, count):
    names = []
    try:
        for _ in range(count):
            name = "tpw_psort_job_" + uuid.uuid4().hex
            subprocess.run(
                [runtime, "--quiet", "create", "--name=" + name, image],
                capture_output=True,
                check=True,
                timeout=int(os.getenv("TPW_PSORT_CREATE_TIMEOUT_SEC") or "1800"),
            )
            names.append(name)
            subprocess.run(
                [runtime, "--quiet", "setup", "--execmode=P1", name],
                capture_output=True,
                check=True,
                timeout=60,
            )
        return names
    except BaseException:
        _remove_udocker_containers(runtime, names)
        raise


@contextmanager
def _lease_udocker_containers(runtime, names):
    """Reuse provisioned instances, locked across jobs on the shared filesystem."""
    import fcntl

    directory = Path(os.getenv("UDOCKER_DIR") or str(Path.home() / ".udocker"))
    locks = directory / "tpw_psort_locks"
    locks.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        # A consistent acquisition order avoids deadlocks for overlapping pools.
        for name in sorted(set(names)):
            key = hashlib.sha256(name.encode()).hexdigest()
            handle = (locks / (key + ".lock")).open("a")
            handles.append(handle)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                subprocess.run(
                    [runtime, "--quiet", "inspect", "-p", name],
                    capture_output=True,
                    check=True,
                    timeout=60,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"Provisioned udocker container {name!r} unavailable; "
                    "run setup_psort_udocker.sh or configure "
                    "TPW_PSORT_UDOCKER_CONTAINERS to an existing PSORT instance"
                ) from exc
        yield list(dict.fromkeys(names))
    finally:
        for handle in reversed(handles):
            handle.close()


def run_batches(
    fasta,
    output,
    cache_dir,
    runtime,
    image,
    gram,
    workers=4,
    batch_size=50,
    timeout=1800,
    engine="apptainer",
    provisioned=None,
):
    if gram not in {"n", "p", "a"} or min(workers, batch_size, timeout) < 1:
        raise ValueError("Invalid PSORT gram type or worker/batch/timeout limit")
    records = read_fasta(fasta)
    # Pin Docker to its local immutable ID; never pull a changing tag mid-run.
    if engine == "docker":
        image = subprocess.check_output(
            [runtime, "image", "inspect", "--format", "{{.Id}}", image],
            universal_newlines=True,
            timeout=30,
        ).strip()
        if not image.startswith("sha256:"):
            raise ValueError("Cannot resolve local PSORT Docker image ID")
    elif engine not in {"apptainer", "udocker"}:
        raise ValueError(f"Unsupported PSORT container engine: {engine}")
    # Include image contents and worker code, not just filenames, in cache identity.
    digest = hashlib.sha256()
    if engine == "udocker":
        metadata = subprocess.check_output(
            [runtime, "--quiet", "inspect", image], universal_newlines=True, timeout=60
        )
        # Metadata includes layer IDs; changing the image invalidates checkpoints.
        digest.update(json.dumps(json.loads(metadata), sort_keys=True).encode())
    for path in (image, __file__) if engine == "apptainer" else (__file__,):
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    digest.update(
        json.dumps(
            [records, gram, batch_size, engine, image if engine != "apptainer" else ""]
        ).encode()
    )
    root = Path(cache_dir).resolve() / digest.hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    owned = []
    lease = None
    try:
        containers = None
        source_image = image
        if engine == "udocker":
            count = min(workers, (len(records) + batch_size - 1) // batch_size)
            if provisioned:
                names = [name.strip() for name in provisioned.split(",") if name.strip()]
                if not names:
                    raise ValueError("Empty udocker container pool")
                lease = _lease_udocker_containers(runtime, names[:count])
                instances = lease.__enter__()
                workers = min(workers, len(instances))
                print(f"PSORT: reusing {len(instances)} provisioned udocker instances", flush=True)
            else:
                owned = _create_udocker_containers(runtime, image, count)
                instances = owned
            containers = Queue()
            for name in instances:
                containers.put(name)
            source_image = instances[0]
        source = subprocess.check_output(
            _container_command(runtime, source_image, engine, "cat", [SCLBLAST_MODULE]),
            universal_newlines=True,
            timeout=60,
        )
        module = root / "SCLBlast.pm"
        module.write_text(instrument_module(source), encoding="utf-8")
        rows = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _run_batch,
                    i,
                    records[start : start + batch_size],
                    root,
                    runtime,
                    image,
                    gram,
                    module,
                    timeout,
                    engine,
                    containers,
                )
                for i, start in enumerate(range(0, len(records), batch_size))
            ]
            try:
                for future in as_completed(futures):
                    rows.update(future.result())
                    print(f"PSORT: {len(rows)}/{len(records)} proteins", flush=True)
            except Exception:
                for future in futures:
                    future.cancel()
                raise
        write_predictions(output, rows, records)
    finally:
        _remove_udocker_containers(runtime, owned)
        if lease is not None:
            lease.__exit__(None, None, None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fasta", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--runtime", default="apptainer")
    parser.add_argument("--engine", choices=["apptainer", "docker", "udocker"], default="apptainer")
    parser.add_argument("--image", required=True)
    parser.add_argument("--containers", help="Comma-separated provisioned udocker instances")
    parser.add_argument("--gram", choices=["n", "p", "a"], required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    run_batches(
        args.fasta,
        args.output,
        args.cache,
        args.runtime,
        args.image,
        args.gram,
        args.workers,
        args.batch_size,
        args.timeout,
        args.engine,
        args.containers,
    )
