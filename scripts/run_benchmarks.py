"""Orquestrador do benchmark K-Means 1D: sequencial x Pthreads x OpenMP.

Para cada dataset:
  1. roda a versão sequencial N vezes (linha de base);
  2. roda Pthreads e OpenMP para cada número de threads, N vezes cada;
  (antes de cada cenário há 1 rodada de aquecimento, descartada)
e grava em results/:
  raw_runs.csv      - uma linha por rodada (dados brutos)
  summary.csv       - média / desvio padrão / mediana por cenário
  environment.json  - máquina, compilador, método de energia, potência ociosa

  speedup    = tempo_médio_sequencial / tempo_da_rodada
  eficiência = speedup / threads

Uso:
    py scripts/run_benchmarks.py                        # completo (small, medium, large)
    py scripts/run_benchmarks.py --datasets small,medium --runs 5
    py scripts/run_benchmarks.py --quick                # teste rápido (~segundos)
"""
import argparse
import csv
import json
import platform
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402
import energy  # noqa: E402
import gen_datasets  # noqa: E402

ROOT = build.ROOT
RAW_COLUMNS = ["timestamp", "dataset", "N", "K", "version", "threads", "run",
               "time_s", "iters", "sse", "energy_j", "avg_power_w", "energy_method",
               "speedup", "efficiency"]
SUMMARY_COLUMNS = ["dataset", "N", "K", "version", "threads", "runs",
                   "time_mean_s", "time_std_s", "time_median_s",
                   "speedup_mean", "speedup_std", "speedup_median",
                   "efficiency_mean", "efficiency_std",
                   "energy_mean_j", "energy_std_j", "energy_median_j",
                   "energy_vs_seq", "avg_power_mean_w", "energy_method"]


def parse_list(text, cast=str):
    return [cast(x.strip()) for x in text.split(",") if x.strip()]


def parse_args(argv):
    p = argparse.ArgumentParser(description="Benchmark K-Means 1D (seq, pthreads, omp).")
    p.add_argument("--datasets", default="small,medium,large",
                   help="lista separada por virgula (small,medium,large,tiny)")
    p.add_argument("--runs", type=int, default=10, help="rodadas por cenario (padrao 10)")
    p.add_argument("--threads", default="1,2,4,6", help="numeros de threads (padrao 1,2,4,6)")
    p.add_argument("--warmup", type=int, default=1, help="rodadas de aquecimento descartadas")
    p.add_argument("--max-iter", type=int, default=50)
    p.add_argument("--eps", type=float, default=1e-6)
    p.add_argument("--energy", choices=["auto", "rapl", "estimate"], default="auto",
                   help="auto: RAPL (Power Gadget) se instalado, senao estimativa")
    p.add_argument("--out-dir", default=str(ROOT / "results"))
    p.add_argument("--data-dir", default=str(gen_datasets.DATA_DIR))
    p.add_argument("--quick", action="store_true",
                   help="teste rapido: dataset tiny, 2 rodadas, threads 1,2, sem aquecimento")
    args = p.parse_args(argv)

    if args.quick:
        args.datasets, args.runs, args.threads, args.warmup = "tiny", 2, "1,2", 0
    args.datasets = parse_list(args.datasets)
    args.threads = parse_list(args.threads, int)
    for d in args.datasets:
        if d not in gen_datasets.DATASETS:
            p.error(f"dataset desconhecido: {d}")
    if args.runs < 1 or any(t < 1 for t in args.threads):
        p.error("--runs e --threads devem ser >= 1")
    return args


def resolve_energy(mode):
    """Retorna o caminho da EnergyLib (usar RAPL) ou None (usar estimativa)."""
    if mode == "estimate":
        return None
    dll = energy.find_energylib()
    if mode == "rapl" and not dll:
        sys.exit("Erro: --energy rapl, mas a EnergyLib64.dll do Intel Power Gadget "
                 "nao foi encontrada (defina ENERGYLIB_PATH).")
    if dll:
        print(f"[energia] RAPL via Intel Power Gadget: {dll}")
    else:
        energy.warn_estimate_once()
    return dll


def stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None, None
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return statistics.mean(vals), std, statistics.median(vals)


def _cmd_output(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def collect_environment(args, energylib):
    """Informações da máquina para o relatório (não afetam a medição)."""
    env = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "os": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": energy.CORES,
        "energy_method": energy.METHOD_RAPL if energylib else energy.METHOD_ESTIMATE,
        "energylib": energylib,
        "args": {k: v for k, v in vars(args).items()},
    }
    try:
        env["gcc"] = _cmd_output([build.find_gcc(), "--version"]).splitlines()[0]
    except (RuntimeError, IndexError):
        env["gcc"] = ""
    if build.IS_WINDOWS:
        env["cpu"] = _cmd_output(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_Processor).Name"])
        env["ram_gb"] = _cmd_output(["powershell", "-NoProfile", "-Command",
                                     "[math]::Round((Get-CimInstance Win32_ComputerSystem)"
                                     ".TotalPhysicalMemory/1GB,1)"])
        env["power_plan"] = _cmd_output(["powercfg", "/getactivescheme"])
    else:
        env["cpu"] = platform.processor()
    if energylib:
        try:
            idle = energy.measure_idle_power(energylib, seconds=5.0)
            env["idle_package_power_w"] = round(idle, 3) if idle else None
            print(f"[energia] potencia ociosa do pacote: {idle:.2f} W")
        except OSError as e:
            env["idle_package_power_w"] = None
            print(f"[energia] nao foi possivel medir a potencia ociosa: {e}")
    return env


class Benchmark:
    def __init__(self, args):
        self.args = args
        self.out_dir = Path(args.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.bins = build.ensure_built()
        self.energylib = resolve_energy(args.energy)
        self.rows = []

    def run_once(self, version, threads, data_path, cent_path):
        cmd = [self.bins[version], data_path, cent_path, "--threads", threads,
               "--max-iter", self.args.max_iter, "--eps", repr(self.args.eps)]
        return energy.run_with_energy(cmd, use_rapl=bool(self.energylib), threads=threads)

    def run_scenario(self, version, threads, ds_name, data_path, cent_path):
        for _ in range(self.args.warmup):
            self.run_once(version, threads, data_path, cent_path)
        results = []
        for r in range(1, self.args.runs + 1):
            res = self.run_once(version, threads, data_path, cent_path)
            res["timestamp"] = datetime.now().isoformat(timespec="seconds")
            res["run"] = r
            results.append(res)
            print(f"  {ds_name:<7} {version:<9} T={threads:<2} run {r:>2}/{self.args.runs}: "
                  f"{res['time_s']:.4f} s  iters={res['iters']}  "
                  f"E={res['energy_j']:.3f} J", flush=True)
        return results

    def run(self):
        env = collect_environment(self.args, self.energylib)
        env_path = self.out_dir / "environment.json"
        env_path.write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")

        raw_path = self.out_dir / "raw_runs.csv"
        with open(raw_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RAW_COLUMNS)
            writer.writeheader()
            for ds_name in self.args.datasets:
                self.run_dataset(ds_name, writer, f)
        summary_path = self.write_summary()
        print(f"\nOK: {raw_path}\nOK: {summary_path}\nOK: {env_path}")
        return raw_path, summary_path

    def run_dataset(self, ds_name, writer, fh):
        n, k = gen_datasets.DATASETS[ds_name]
        data_path, cent_path = gen_datasets.generate(ds_name, n, k, data_dir=self.args.data_dir)
        print(f"\n=== dataset {ds_name}: N={n:,} K={k} ===")

        def emit(version, threads, res, seq_mean):
            speedup = seq_mean / res["time_s"] if res["time_s"] > 0 else None
            row = {"timestamp": res["timestamp"], "dataset": ds_name, "N": n, "K": k,
                   "version": version, "threads": threads, "run": res["run"],
                   "time_s": f"{res['time_s']:.9f}", "iters": res["iters"],
                   "sse": f"{res['sse']:.10g}",
                   "energy_j": f"{res['energy_j']:.6f}",
                   "avg_power_w": "" if res["avg_power_w"] is None
                   else f"{res['avg_power_w']:.3f}",
                   "energy_method": res["energy_method"],
                   "speedup": "" if speedup is None else f"{speedup:.6f}",
                   "efficiency": "" if speedup is None else f"{speedup / threads:.6f}"}
            writer.writerow(row)
            fh.flush()  # grava à medida que roda: nada se perde se interromper
            self.rows.append(row)

        # Linha de base sequencial (threads = 1).
        seq = self.run_scenario("seq", 1, ds_name, data_path, cent_path)
        seq_mean = statistics.mean(r["time_s"] for r in seq)
        seq_sse = seq[0]["sse"]
        for res in seq:
            emit("seq", 1, res, seq_mean)

        for version in ("pthreads", "omp"):
            for t in self.args.threads:
                for res in self.run_scenario(version, t, ds_name, data_path, cent_path):
                    if abs(res["sse"] - seq_sse) > 1e-6 * max(1.0, abs(seq_sse)):
                        print(f"  AVISO: SSE de {version} T={t} difere do sequencial "
                              f"({res['sse']} vs {seq_sse})", file=sys.stderr)
                    emit(version, t, res, seq_mean)

    def write_summary(self):
        groups = {}
        for row in self.rows:
            key = (row["dataset"], row["version"], row["threads"])
            groups.setdefault(key, []).append(row)

        def col(rows, name):
            return [float(r[name]) if r[name] != "" else None for r in rows]

        def fmt(v):
            return "" if v is None else f"{v:.6f}"

        seq_energy = {ds: stats(col(rows, "energy_j"))[0]
                      for (ds, version, _), rows in groups.items() if version == "seq"}

        path = self.out_dir / "summary.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
            writer.writeheader()
            for (ds, version, threads), rows in groups.items():
                t_mean, t_std, t_med = stats(col(rows, "time_s"))
                s_mean, s_std, s_med = stats(col(rows, "speedup"))
                e_mean, e_std, _ = stats(col(rows, "efficiency"))
                en_mean, en_std, en_med = stats(col(rows, "energy_j"))
                p_mean, _, _ = stats(col(rows, "avg_power_w"))
                base = seq_energy.get(ds)
                writer.writerow({
                    "dataset": ds, "N": rows[0]["N"], "K": rows[0]["K"],
                    "version": version, "threads": threads, "runs": len(rows),
                    "time_mean_s": fmt(t_mean), "time_std_s": fmt(t_std),
                    "time_median_s": fmt(t_med),
                    "speedup_mean": fmt(s_mean), "speedup_std": fmt(s_std),
                    "speedup_median": fmt(s_med),
                    "efficiency_mean": fmt(e_mean), "efficiency_std": fmt(e_std),
                    "energy_mean_j": fmt(en_mean), "energy_std_j": fmt(en_std),
                    "energy_median_j": fmt(en_med),
                    "energy_vs_seq": fmt(en_mean / base) if base else "",
                    "avg_power_mean_w": fmt(p_mean),
                    "energy_method": rows[0]["energy_method"],
                })
        return path


def main(argv=None):
    args = parse_args(argv)
    try:
        bench = Benchmark(args)
    except RuntimeError as e:  # ex.: gcc não encontrado
        sys.exit(f"Erro: {e}")
    return bench.run()


if __name__ == "__main__":
    main()
