"""Execução de um kmeans com medição de energia.

Método preferido (energy_method=rapl_energylib):
    o próprio executável recebe --rapl e lê os contadores RAPL do processador
    (domínio PKG = pacote inteiro da CPU) pela EnergyLib64.dll do Intel Power
    Gadget 3.6, imediatamente antes e depois do laço do K-Means. A energia
    medida cobre exatamente o mesmo trecho que o tempo (sem leitura de arquivos).

Fallback (energy_method=estimate_tdp), se o Power Gadget não estiver instalado:
    potência ≈ (TDP / núcleos) x threads        (TDP do i5-9400F = 65 W, 6 núcleos)
    energia  ≈ potência x tempo do laço
    Nesse modelo, energia_paralela / energia_sequencial = 1 / eficiência.
"""
import ctypes
import os
import re
import subprocess
import sys
import time

TDP_WATTS = 65.0  # TDP do Intel Core i5-9400F
CORES = os.cpu_count() or 6

ENERGYLIB_CANDIDATES = [
    r"C:\Program Files\Intel\Power Gadget 3.6\EnergyLib64.dll",
    r"C:\Program Files\Intel\Power Gadget 3.5\EnergyLib64.dll",
]

METHOD_RAPL = "rapl_energylib"
METHOD_ESTIMATE = "estimate_tdp"

_RESULT_RE = re.compile(r"RESULT\s+time_s=(\S+)\s+iters=(\d+)\s+sse=(\S+)")
_ENERGY_RE = re.compile(r"ENERGY\s+energy_j=(\S+)\s+interval_s=(\S+)")

_warned = False


def find_energylib(candidates=None, env=None):
    """Retorna o caminho da EnergyLib64.dll (Intel Power Gadget) ou None."""
    env = os.environ if env is None else env
    custom = env.get("ENERGYLIB_PATH")
    if custom:
        return custom if os.path.isfile(custom) else None
    for cand in ENERGYLIB_CANDIDATES if candidates is None else candidates:
        if os.path.isfile(cand):
            return cand
    return None


def warn_estimate_once():
    global _warned
    if not _warned:
        _warned = True
        print("AVISO: Intel Power Gadget (EnergyLib64.dll) nao encontrado.\n"
              f"       A energia sera ESTIMADA: ({TDP_WATTS:.0f} W / {CORES} nucleos) x threads"
              " x tempo (energy_method=estimate_tdp).\n"
              "       Para medir via RAPL, instale o Power Gadget 3.6 (veja o README).",
              file=sys.stderr, flush=True)


def estimate_power(threads, tdp_w=TDP_WATTS, cores=CORES):
    """Potência estimada: fração do TDP proporcional aos núcleos ocupados."""
    return tdp_w * min(threads, cores) / cores


def parse_result(text):
    """Extrai time_s, iters e sse da linha RESULT impressa pelo kmeans."""
    m = _RESULT_RE.search(text or "")
    if not m:
        return None
    return {"time_s": float(m.group(1)), "iters": int(m.group(2)), "sse": float(m.group(3))}


def parse_energy(text):
    """Extrai energia (J) e potência média (W) da linha ENERGY (impressa com --rapl)."""
    m = _ENERGY_RE.search(text or "")
    if not m:
        return None
    energy, interval = float(m.group(1)), float(m.group(2))
    power = energy / interval if interval > 0 else None
    return {"energy_j": energy, "avg_power_w": power, "rapl_interval_s": interval}


def run_with_energy(cmd, use_rapl=False, threads=1, env=None):
    """Roda um executável kmeans e devolve dict com
    time_s, iters, sse, energy_j, avg_power_w, rapl_interval_s, energy_method."""
    cmd = [str(c) for c in cmd] + (["--rapl"] if use_rapl else [])
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"comando falhou ({proc.returncode}): {' '.join(cmd)}\n"
                           f"{proc.stderr.strip()}")
    result = parse_result(proc.stdout)
    if result is None:
        raise RuntimeError(f"saida sem linha RESULT: {' '.join(cmd)}")

    if use_rapl:
        energy = parse_energy(proc.stdout)
        if energy is None:
            raise RuntimeError(f"saida sem linha ENERGY: {' '.join(cmd)}")
        method = METHOD_RAPL
    else:
        warn_estimate_once()
        power = estimate_power(threads)
        energy = {"energy_j": power * result["time_s"], "avg_power_w": power,
                  "rapl_interval_s": None}
        method = METHOD_ESTIMATE
    result.update(energy)
    result["energy_method"] = method
    return result


def measure_idle_power(dll_path, seconds=5.0):
    """Potência média do pacote com o sistema ocioso (W), lida pela EnergyLib.
    Serve de referência para o relatório (parte "estática" da potência)."""
    os.add_dll_directory(os.path.dirname(dll_path))
    lib = ctypes.WinDLL(dll_path)
    if not lib.IntelEnergyLibInitialize():
        return None
    n = ctypes.c_int(0)
    lib.GetNumMsrs(ctypes.byref(n))
    name, func, pkg = ctypes.create_unicode_buffer(256), ctypes.c_int(0), None
    for i in range(n.value):
        lib.GetMsrName(i, name)
        lib.GetMsrFunc(i, ctypes.byref(func))
        if func.value == 1 and name.value == "Processor":
            pkg = i
    if pkg is None:
        return None
    lib.ReadSample()
    time.sleep(seconds)
    lib.ReadSample()
    data, count = (ctypes.c_double * 3)(), ctypes.c_int(0)
    interval = ctypes.c_double(0)
    lib.GetPowerData(0, pkg, data, ctypes.byref(count))
    lib.GetTimeInterval(ctypes.byref(interval))
    return data[1] / interval.value if interval.value > 0 else None
