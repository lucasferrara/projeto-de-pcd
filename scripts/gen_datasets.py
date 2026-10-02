"""Gerador de datasets sintéticos para o K-Means 1D.

Cada dataset é uma mistura de K gaussianas 1D, gerada com seed fixa
(reprodutível). Arquivos gerados em data/:
    <nome>.bin             int64 N + N doubles (pontos)
    <nome>_centroids.bin   int64 K + K doubles (centróides iniciais = K pontos sorteados)
    manifest.json          parâmetros de cada dataset

Uso:
    py scripts/gen_datasets.py                 # gera small, medium, large (se faltarem)
    py scripts/gen_datasets.py --only medium   # só um
    py scripts/gen_datasets.py --force         # regera mesmo se existir
"""
import argparse
import json
import random
import struct
import sys
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_SEED = 2026

# nome -> (N, K). "tiny" é usado só no modo --quick e nos testes.
DATASETS = {
    "tiny": (2_000, 4),
    "small": (10_000, 4),
    "medium": (1_000_000, 8),
    "large": (10_000_000, 16),
}
DEFAULT_SET = ["small", "medium", "large"]


def write_array(path, values):
    arr = values if isinstance(values, array) else array("d", values)
    if sys.byteorder != "little":
        arr = array("d", arr)
        arr.byteswap()
    with open(path, "wb") as f:
        f.write(struct.pack("<q", len(arr)))
        arr.tofile(f)


def read_array(path):
    with open(path, "rb") as f:
        (n,) = struct.unpack("<q", f.read(8))
        arr = array("d")
        arr.frombytes(f.read())
    if sys.byteorder != "little":
        arr.byteswap()
    if len(arr) != n:
        raise ValueError(f"{path}: cabecalho diz {n}, arquivo tem {len(arr)}")
    return arr


def generate_points(n, k, seed_key):
    """Mistura de k gaussianas com centros espaçados ~10 e desvio entre 1 e 3."""
    rng = random.Random(seed_key)
    means = [10.0 * j + rng.uniform(-2.0, 2.0) for j in range(k)]
    sigmas = [rng.uniform(1.0, 3.0) for _ in range(k)]
    gauss, rand = rng.gauss, rng.random
    points = array("d")
    append = points.append
    for _ in range(n):
        j = int(rand() * k)
        append(gauss(means[j], sigmas[j]))
    return points, rng


def pick_initial_centroids(points, k, rng):
    """Sorteia k pontos distintos do próprio dataset como centróides iniciais."""
    chosen = []
    seen = set()
    while len(chosen) < k:
        v = points[rng.randrange(len(points))]
        if v not in seen:
            seen.add(v)
            chosen.append(v)
    return chosen


def dataset_paths(name, data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    return data_dir / f"{name}.bin", data_dir / f"{name}_centroids.bin"


def generate(name, n, k, seed=DEFAULT_SEED, data_dir=DATA_DIR, force=False, verbose=True):
    """Gera um dataset (se necessário). Retorna (caminho_dados, caminho_centroides)."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    data_path, cent_path = dataset_paths(name, data_dir)
    if data_path.exists() and cent_path.exists() and not force:
        if verbose:
            print(f"[datasets] {name}: ja existe, pulando (use --force para regerar)")
        return data_path, cent_path

    if verbose:
        print(f"[datasets] gerando {name}: N={n:,} K={k} seed={seed} ...", flush=True)
    points, rng = generate_points(n, k, f"{seed}-{name}")
    centroids = pick_initial_centroids(points, k, rng)
    write_array(data_path, points)
    write_array(cent_path, centroids)
    _update_manifest(data_dir, name, {"N": n, "K": k, "seed": seed,
                                      "data": data_path.name, "centroids": cent_path.name})
    return data_path, cent_path


def _update_manifest(data_dir, name, entry):
    path = Path(data_dir) / "manifest.json"
    manifest = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    manifest[name] = entry
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description="Gera datasets 1D para o K-Means.")
    p.add_argument("--only", choices=sorted(DATASETS), action="append",
                   help="gera apenas este dataset (pode repetir)")
    p.add_argument("--force", action="store_true", help="regera mesmo se ja existir")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--data-dir", default=str(DATA_DIR))
    args = p.parse_args(argv)

    for name in args.only or DEFAULT_SET:
        n, k = DATASETS[name]
        generate(name, n, k, seed=args.seed, data_dir=args.data_dir, force=args.force)


if __name__ == "__main__":
    main()
