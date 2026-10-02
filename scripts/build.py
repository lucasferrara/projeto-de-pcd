"""Compilação dos executáveis C (usado pelo orquestrador e pelos testes).

Chama o gcc diretamente (mesmas flags do Makefile), assim funciona tanto no
PowerShell quanto no shell do MSYS2/Linux, sem depender do `make`.

No Windows, copia para bin/ as DLLs de runtime do MinGW (libgomp, winpthread...),
para os executáveis rodarem direto do PowerShell mesmo sem o MSYS2 no PATH.
(Não dá para linkar estático: o MSYS2 não distribui a libgomp estática.)
"""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
BIN = ROOT / "bin"
IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""

CFLAGS = ["-O2", "-std=c11", "-Wall"]
COMMON_SOURCES = ["kmeans_common.c", "rapl.c"]
COMMON_HEADERS = ["kmeans_common.h", "rapl.h"]
RUNTIME_DLLS = ["libgomp-1.dll", "libwinpthread-1.dll", "libgcc_s_seh-1.dll"]

# versão -> (arquivo fonte, flags extras)
VERSIONS = {
    "seq": ("kmeans_seq.c", []),
    "pthreads": ("kmeans_pthreads.c", ["-pthread"]),
    "omp": ("kmeans_omp.c", ["-fopenmp"]),
}

# Locais comuns do gcc do MSYS2 caso ele não esteja no PATH.
GCC_CANDIDATES = [
    r"C:\msys64\ucrt64\bin\gcc.exe",
    r"C:\msys64\mingw64\bin\gcc.exe",
]


def find_gcc():
    env_cc = os.environ.get("CC")
    if env_cc and shutil.which(env_cc):
        return shutil.which(env_cc)
    found = shutil.which("gcc")
    if found:
        return found
    for cand in GCC_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    raise RuntimeError(
        "gcc nao encontrado. Instale o MSYS2 e rode no terminal UCRT64:\n"
        "  pacman -S mingw-w64-ucrt-x86_64-gcc make\n"
        "e adicione C:\\msys64\\ucrt64\\bin ao PATH (veja o README)."
    )


def binary_path(version):
    return BIN / f"kmeans_{version}{EXE}"


def gcc_env(gcc):
    """O gcc do MSYS2 precisa da própria pasta no PATH (DLLs do cc1/as/ld);
    sem isso ele falha sem mensagem quando chamado de fora do terminal MSYS2."""
    env = os.environ.copy()
    env["PATH"] = str(Path(gcc).parent) + os.pathsep + env.get("PATH", "")
    return env


def ensure_built(force=False, verbose=True):
    """Compila as versões que estiverem faltando ou desatualizadas. Retorna {versão: caminho}."""
    deps_common = [SRC / f for f in COMMON_SOURCES + COMMON_HEADERS]
    BIN.mkdir(exist_ok=True)
    gcc = None
    paths = {}
    for version, (source, extra) in VERSIONS.items():
        out = binary_path(version)
        deps = deps_common + [SRC / source]
        stale = force or not out.exists() or any(
            d.stat().st_mtime > out.stat().st_mtime for d in deps
        )
        if stale:
            gcc = gcc or find_gcc()
            cmd = [gcc, *CFLAGS, *extra, "-o", str(out), str(SRC / source),
                   *(str(SRC / f) for f in COMMON_SOURCES)]
            if verbose:
                print("[build]", " ".join(cmd))
            subprocess.run(cmd, check=True, cwd=ROOT, env=gcc_env(gcc))
        paths[version] = out
    if gcc and IS_WINDOWS:
        for dll in RUNTIME_DLLS:
            src = Path(gcc).parent / dll
            if src.exists():
                shutil.copy2(src, BIN / dll)
    return paths


if __name__ == "__main__":
    ensure_built(force=True)
