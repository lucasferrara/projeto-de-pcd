"""Testes do módulo de energia (parsers, detecção do Power Gadget e estimativa)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import energy  # noqa: E402


def fake_kmeans(stdout):
    """'Executável' falso que só imprime `stdout` (aceita args extras, ex.: --rapl)."""
    return [sys.executable, "-c", f"print({stdout!r})"]


class TestParsers(unittest.TestCase):
    def test_parse_result(self):
        self.assertEqual(energy.parse_result("RESULT time_s=0.25 iters=7 sse=1.5e3\nCENTROIDS 1"),
                         {"time_s": 0.25, "iters": 7, "sse": 1500.0})
        self.assertIsNone(energy.parse_result("sem resultado"))

    def test_parse_energy(self):
        self.assertEqual(energy.parse_energy("ENERGY energy_j=40.5 interval_s=2.0"),
                         {"energy_j": 40.5, "avg_power_w": 20.25, "rapl_interval_s": 2.0})
        self.assertIsNone(energy.parse_energy("RESULT time_s=1 iters=1 sse=1"))

    def test_parse_energy_zero_interval(self):
        self.assertIsNone(energy.parse_energy("ENERGY energy_j=0 interval_s=0")["avg_power_w"])


class TestFindEnergyLib(unittest.TestCase):
    def test_absent(self):
        self.assertIsNone(energy.find_energylib(candidates=[], env={}))
        self.assertIsNone(energy.find_energylib(env={"ENERGYLIB_PATH": "C:/nao/existe.dll"}))

    def test_env_override(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            self.assertEqual(energy.find_energylib(env={"ENERGYLIB_PATH": path}), path)
        finally:
            os.remove(path)


class TestRunWithEnergy(unittest.TestCase):
    def test_estimate(self):
        res = energy.run_with_energy(fake_kmeans("RESULT time_s=0.5 iters=3 sse=1.0"),
                                     use_rapl=False, threads=1)
        self.assertEqual(res["energy_method"], energy.METHOD_ESTIMATE)
        per_core = energy.TDP_WATTS / energy.CORES
        self.assertAlmostEqual(res["avg_power_w"], per_core)
        self.assertAlmostEqual(res["energy_j"], per_core * 0.5)
        self.assertEqual(res["iters"], 3)

    def test_estimate_scales_with_threads(self):
        self.assertAlmostEqual(energy.estimate_power(6, tdp_w=65, cores=6), 65)
        self.assertAlmostEqual(energy.estimate_power(2, tdp_w=65, cores=6), 65 / 3)
        self.assertAlmostEqual(energy.estimate_power(12, tdp_w=65, cores=6), 65)  # limitado

    def test_rapl_reads_energy_line(self):
        out = "RESULT time_s=2.0 iters=5 sse=3.0\nENERGY energy_j=50.0 interval_s=2.0"
        res = energy.run_with_energy(fake_kmeans(out), use_rapl=True, threads=4)
        self.assertEqual(res["energy_method"], energy.METHOD_RAPL)
        self.assertEqual((res["energy_j"], res["avg_power_w"]), (50.0, 25.0))

    def test_rapl_missing_energy_line_raises(self):
        with self.assertRaises(RuntimeError):
            energy.run_with_energy(fake_kmeans("RESULT time_s=2.0 iters=5 sse=3.0"),
                                   use_rapl=True)

    def test_failing_command_raises(self):
        with self.assertRaises(RuntimeError):
            energy.run_with_energy([sys.executable, "-c", "raise SystemExit(3)"])


@unittest.skipUnless(energy.find_energylib(), "Intel Power Gadget nao instalado")
class TestIdlePower(unittest.TestCase):
    def test_idle_power_plausible(self):
        p = energy.measure_idle_power(energy.find_energylib(), seconds=0.5)
        self.assertTrue(0.5 < p < 100, p)


if __name__ == "__main__":
    unittest.main()
