"""Teste ponta a ponta do orquestrador em modo --quick."""
import csv
import json
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_benchmarks  # noqa: E402


class TestBenchmarkQuick(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.raw, cls.summary = run_benchmarks.main(
            ["--quick", "--energy", "estimate",
             "--out-dir", str(tmp / "results"), "--data-dir", str(tmp / "data")])
        with open(cls.raw, newline="", encoding="utf-8") as f:
            cls.rows = list(csv.DictReader(f))
        with open(cls.summary, newline="", encoding="utf-8") as f:
            cls.summary_rows = list(csv.DictReader(f))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_raw_columns_and_row_count(self):
        self.assertEqual(list(self.rows[0].keys()), run_benchmarks.RAW_COLUMNS)
        # quick: 2 rodadas seq + 2 versões x 2 contagens de threads x 2 rodadas
        self.assertEqual(len(self.rows), 2 + 2 * 2 * 2)

    def test_metrics_consistent(self):
        for r in self.rows:
            self.assertAlmostEqual(float(r["efficiency"]),
                                   float(r["speedup"]) / int(r["threads"]), places=5)
            self.assertEqual(r["energy_method"], "estimate_tdp")
            self.assertGreater(float(r["energy_j"]), 0)
        seq = [float(r["speedup"]) for r in self.rows if r["version"] == "seq"]
        self.assertAlmostEqual(statistics.mean(seq), 1.0, delta=0.5)

    def test_summary(self):
        self.assertEqual(list(self.summary_rows[0].keys()), run_benchmarks.SUMMARY_COLUMNS)
        self.assertEqual(len(self.summary_rows), 1 + 2 * 2)
        self.assertTrue(all(r["runs"] == "2" for r in self.summary_rows))
        seq = next(r for r in self.summary_rows if r["version"] == "seq")
        self.assertAlmostEqual(float(seq["energy_vs_seq"]), 1.0)

    def test_environment_file(self):
        env = json.loads((self.raw.parent / "environment.json").read_text(encoding="utf-8"))
        self.assertEqual(env["energy_method"], "estimate_tdp")
        self.assertIn("gcc", env)


if __name__ == "__main__":
    unittest.main()
