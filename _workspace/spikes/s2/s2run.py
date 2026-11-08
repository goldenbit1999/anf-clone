"""S2 measurement runner (Windows side).

Runs fio inside the s2 client containers through `wsl -u root` and times every
run twice: fio's own runtime (guest CLOCK_MONOTONIC) and the Windows host clock
(time.perf_counter, QPC) around the whole call minus the measured exec overhead.

  python s2run.py clock SECONDS
  python s2run.py overhead CONTAINER
  python s2run.py measure LABEL CONTAINER PATH RW SIZE_MIB REPS [--drop] [--iodepth N]
  python s2run.py noisy LABEL NOISE_C:PATH:RW:SECONDS:IODEPTH CONTAINER PATH RW SIZE_MIB REPS [--drop]
  python s2run.py mixed LABEL CONTAINER RPATH WPATH SECONDS REPS [--drop]

Every result is appended to results.jsonl next to this file.
"""

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

WSL = ["wsl", "-d", "Ubuntu", "-u", "root", "-e"]
OUT = Path(__file__).with_name("results.jsonl")
MIB = 1 << 20


def wsl(*args):
    return subprocess.run(WSL + list(args), capture_output=True, text=True, check=True)


def drop_caches():
    wsl("bash", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches")


def guest_monotonic():
    return float(wsl("python3", "-c", "import time; print(time.monotonic())").stdout)


def clock(seconds):
    h0 = time.perf_counter(); g0 = guest_monotonic(); h0b = time.perf_counter()
    time.sleep(seconds)
    h1 = time.perf_counter(); g1 = guest_monotonic(); h1b = time.perf_counter()
    host = (h1 + h1b) / 2 - (h0 + h0b) / 2
    rec = {"kind": "clock", "host_s": host, "guest_s": g1 - g0, "guest_per_host": (g1 - g0) / host,
           "call_jitter_s": max(h0b - h0, h1b - h1)}
    save(rec)
    print(json.dumps(rec))


def overhead(container, n=7):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); wsl("docker", "exec", container, "true"); ts.append(time.perf_counter() - t0)
    return statistics.median(ts)


def fio_args(container, jobs, extra=()):
    args = ["docker", "exec", container, "fio", "--bs=1M", "--direct=1", "--ioengine=libaio",
            "--clocksource=clock_gettime", "--output-format=json", *extra]
    for j in jobs:
        args += [f"--name={j['name']}", f"--filename={j['path']}", f"--rw={j['rw']}", f"--iodepth={j.get('iodepth', 16)}"]
        if "size_mib" in j:
            args.append(f"--size={j['size_mib']}M")
    return args


def parse(stdout):
    data = json.loads(stdout[stdout.index("{"):])
    out = []
    for job in data["jobs"]:
        side = job["read"] if job["read"]["io_bytes"] else job["write"]
        out.append({"name": job["jobname"], "bytes": side["io_bytes"], "guest_s": side["runtime"] / 1000,
                    "guest_mib_s": side["bw_bytes"] / MIB})
    return out


def one(container, path, rw, size_mib, iodepth, ovh):
    args = fio_args(container, [{"name": "j", "path": path, "rw": rw, "size_mib": size_mib, "iodepth": iodepth}])
    t0 = time.perf_counter(); r = wsl(*args); host = time.perf_counter() - t0
    res = parse(r.stdout)[0]
    res["host_s"] = host - ovh
    res["host_mib_s"] = res["bytes"] / MIB / res["host_s"]
    return res


def summarize(label, runs, keys=("guest_mib_s", "host_mib_s")):
    med = {k: round(statistics.median(r[k] for r in runs), 2) for k in keys if k in runs[0]}
    print(f"{label}: " + " | ".join(f"{k}={[round(r[k], 1) for r in runs]} median={med[k]}" for k in med))
    return med


def save(rec):
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def measure(label, container, path, rw, size_mib, reps, drop, iodepth):
    ovh = overhead(container)
    runs = []
    for _ in range(reps):
        if drop:
            drop_caches()
        runs.append(one(container, path, rw, size_mib, iodepth, ovh))
    med = summarize(label, runs)
    save({"kind": "measure", "label": label, "container": container, "path": path, "rw": rw,
          "size_mib": size_mib, "iodepth": iodepth, "drop": drop, "overhead_s": ovh, "runs": runs, "median": med})


def noisy(label, noise, container, path, rw, size_mib, reps, drop):
    nc, npath, nrw, nsec, ndepth = noise.split(":")
    ovh = overhead(container)
    runs, noise_runs = [], []
    for _ in range(reps):
        if drop:
            drop_caches()
        nargs = fio_args(nc, [{"name": "noise", "path": npath, "rw": nrw, "iodepth": int(ndepth), "size_mib": 1024}],
                         extra=("--time_based", f"--runtime={nsec}"))
        bg = subprocess.Popen(WSL + nargs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(3)
        runs.append(one(container, path, rw, size_mib, 16, ovh))
        out, _ = bg.communicate()
        noise_runs.append(parse(out)[0])
    med = summarize(label, runs)
    nmed = summarize(label + " [noise]", noise_runs, keys=("guest_mib_s",))
    save({"kind": "noisy", "label": label, "noise": noise, "container": container, "path": path, "rw": rw,
          "size_mib": size_mib, "drop": drop, "overhead_s": ovh, "runs": runs, "noise_runs": noise_runs,
          "median": med, "noise_median": nmed})


def mixed(label, container, rpath, wpath, seconds, reps, drop):
    runs = []
    for _ in range(reps):
        if drop:
            drop_caches()
        args = fio_args(container, [{"name": "r", "path": rpath, "rw": "read", "size_mib": 1024},
                                    {"name": "w", "path": wpath, "rw": "write", "size_mib": 1024}],
                        extra=("--time_based", f"--runtime={seconds}"))
        jobs = {j["name"]: j for j in parse(wsl(*args).stdout)}
        runs.append({"read_mib_s": jobs["r"]["guest_mib_s"], "write_mib_s": jobs["w"]["guest_mib_s"],
                     "sum_mib_s": jobs["r"]["guest_mib_s"] + jobs["w"]["guest_mib_s"]})
    med = summarize(label, runs, keys=("read_mib_s", "write_mib_s", "sum_mib_s"))
    save({"kind": "mixed", "label": label, "container": container, "seconds": seconds, "drop": drop,
          "runs": runs, "median": med})


def main(argv):
    flags = {a for a in argv if a.startswith("--")}
    drop = "--drop" in flags
    iodepth = 16
    if "--iodepth" in argv:
        i = argv.index("--iodepth"); iodepth = int(argv[i + 1]); del argv[i:i + 2]
    pos = [a for a in argv if not a.startswith("--")]
    cmd = pos[0]
    if cmd == "clock":
        clock(float(pos[1]))
    elif cmd == "overhead":
        print(overhead(pos[1]))
    elif cmd == "measure":
        measure(pos[1], pos[2], pos[3], pos[4], int(pos[5]), int(pos[6]), drop, iodepth)
    elif cmd == "noisy":
        noisy(pos[1], pos[2], pos[3], pos[4], pos[5], int(pos[6]), int(pos[7]), drop)
    elif cmd == "mixed":
        mixed(pos[1], pos[2], pos[3], pos[4], int(pos[5]), int(pos[6]), drop)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
