"""Testes de corretude dos executáveis K-Means (seq, pthreads, omp)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build  # noqa: E402
import energy  # noqa: E402
import gen_datasets  # noqa: E402

BINS = build.ensure_built(verbose=False)
ENERGYLIB = energy.find_energylib()
REL_TOL = 1e-6


def run_kmeans(version, data, cents, *extra, env=None):
    proc = subprocess.run([str(BINS[version]), str(data), str(cents), *map(str, extra)],
                          capture_output=True, text=True, env=env)
    return proc


def parse_output(stdout):
    res = energy.parse_result(stdout)
    line = next(l for l in stdout.splitlines() if l.startswith("CENTROIDS"))
    res["centroids"] = [float(v) for v in line.split()[1:]]
    return res


class KMeansTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_files(self, points, centroids):
        data, cents = self.tmp / "data.bin", self.tmp / "cents.bin"
        gen_datasets.write_array(data, points)
        gen_datasets.write_array(cents, centroids)
        return data, cents

    def run_ok(self, version, data, cents, *extra):
        proc = run_kmeans(version, data, cents, *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return parse_output(proc.stdout)

    def assertClose(self, a, b):
        self.assertLessEqual(abs(a - b), REL_TOL * max(1.0, abs(b)), f"{a} != {b}")


class TestSequential(KMeansTestBase):
    def test_manual_case(self):
        data, cents = self.make_files([1, 2, 3, 10, 11, 12], [1, 10])
        res = self.run_ok("seq", data, cents)
        self.assertEqual(res["centroids"], [2.0, 11.0])
        self.assertAlmostEqual(res["sse"], 4.0)
        self.assertEqual(res["iters"], 2)

    def test_empty_cluster_keeps_centroid(self):
        data, cents = self.make_files([1, 2, 3], [2, 100])
        res = self.run_ok("seq", data, cents)
        self.assertEqual(res["centroids"], [2.0, 100.0])
        self.assertAlmostEqual(res["sse"], 2.0)

    def test_max_iter_respected(self):
        data, cents = self.make_files([1, 2, 3, 10, 11, 12], [1, 10])
        self.assertEqual(self.run_ok("seq", data, cents, "--max-iter", 1)["iters"], 1)

    def test_out_centroids_file(self):
        data, cents = self.make_files([1, 2, 3, 10, 11, 12], [1, 10])
        out = self.tmp / "final.bin"
        self.run_ok("seq", data, cents, "--out-centroids", out)
        self.assertEqual(list(gen_datasets.read_array(out)), [2.0, 11.0])

    def test_invalid_inputs_fail(self):
        data, cents = self.make_files([1, 2, 3], [1, 2])
        truncated = self.tmp / "bad.bin"
        truncated.write_bytes(data.read_bytes()[:-4])
        for version in BINS:
            with self.subTest(version=version):
                self.assertNotEqual(run_kmeans(version, truncated, cents).returncode, 0)
                self.assertNotEqual(
                    run_kmeans(version, self.tmp / "nao_existe.bin", cents).returncode, 0)
                missing_arg = subprocess.run([str(BINS[version]), str(data)],
                                             capture_output=True)
                self.assertNotEqual(missing_arg.returncode, 0)
                self.assertNotEqual(
                    run_kmeans(version, data, cents, "--threads", 0).returncode, 0)


class TestParallelMatchesSequential(KMeansTestBase):
    THREADS = [1, 2, 4, 6, 8]

    def compare(self, data, cents):
        ref = self.run_ok("seq", data, cents)
        for version in ("pthreads", "omp"):
            for t in self.THREADS:
                with self.subTest(version=version, threads=t):
                    res = self.run_ok(version, data, cents, "--threads", t)
                    self.assertEqual(res["iters"], ref["iters"])
                    self.assertClose(res["sse"], ref["sse"])
                    for a, b in zip(res["centroids"], ref["centroids"]):
                        self.assertClose(a, b)

    def test_manual_case_including_more_threads_than_points(self):
        self.compare(*self.make_files([1, 2, 3, 10, 11, 12], [1, 10]))

    def test_synthetic_dataset_not_divisible(self):
        data, cents = gen_datasets.generate("t", 10_007, 5, data_dir=self.tmp, verbose=False)
        self.compare(data, cents)


class TestRapl(KMeansTestBase):
    """Medição de energia embutida nos executáveis (--rapl)."""

    @unittest.skipUnless(ENERGYLIB, "Intel Power Gadget nao instalado")
    def test_rapl_reports_energy(self):
        data, cents = gen_datasets.generate("r", 200_000, 8, data_dir=self.tmp, verbose=False)
        for version in BINS:
            with self.subTest(version=version):
                proc = run_kmeans(version, data, cents, "--threads", 2, "--rapl")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                res = energy.parse_result(proc.stdout)
                en = energy.parse_energy(proc.stdout)
                self.assertIsNotNone(en, proc.stdout)
                self.assertGreater(en["energy_j"], 0)
                # potência média plausível para um desktop (W)
                self.assertTrue(1 < en["avg_power_w"] < 200, en)
                # intervalo do RAPL ~ tempo do laço (resolução do contador ~1 ms)
                self.assertLess(abs(en["rapl_interval_s"] - res["time_s"]), 0.01)

    def test_rapl_unavailable_fails_loudly(self):
        data, cents = self.make_files([1, 2, 3, 10, 11, 12], [1, 10])
        env = dict(os.environ, ENERGYLIB_PATH=str(self.tmp / "nao_existe.dll"))
        for version in BINS:
            with self.subTest(version=version):
                proc = run_kmeans(version, data, cents, "--rapl", env=env)
                self.assertNotEqual(proc.returncode, 0)
                self.assertNotIn("ENERGY", proc.stdout)

    def test_no_energy_line_without_flag(self):
        data, cents = self.make_files([1, 2, 3, 10, 11, 12], [1, 10])
        self.assertIsNone(energy.parse_energy(run_kmeans("seq", data, cents).stdout))


if __name__ == "__main__":
    unittest.main()
