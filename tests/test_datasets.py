"""Testes do gerador de datasets."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import gen_datasets  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestGenDatasets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_file_sizes_and_centroid_count(self):
        n, k = 5_000, 7
        data, cents = gen_datasets.generate("x", n, k, data_dir=self.tmp, verbose=False)
        self.assertEqual(data.stat().st_size, 8 + 8 * n)
        self.assertEqual(cents.stat().st_size, 8 + 8 * k)
        c = gen_datasets.read_array(cents)
        self.assertEqual(len(c), k)
        self.assertEqual(len(set(c)), k)  # centróides distintos
        pts = set(gen_datasets.read_array(data))
        self.assertTrue(all(v in pts for v in c))  # sorteados do próprio dataset

    def test_same_seed_same_hash(self):
        d1, c1 = gen_datasets.generate("a", 3_000, 4, seed=1, data_dir=self.tmp / "1",
                                       verbose=False)
        d2, c2 = gen_datasets.generate("a", 3_000, 4, seed=1, data_dir=self.tmp / "2",
                                       verbose=False)
        d3, _ = gen_datasets.generate("a", 3_000, 4, seed=2, data_dir=self.tmp / "3",
                                      verbose=False)
        self.assertEqual(sha(d1), sha(d2))
        self.assertEqual(sha(c1), sha(c2))
        self.assertNotEqual(sha(d1), sha(d3))

    def test_skip_existing_unless_force(self):
        data, _ = gen_datasets.generate("s", 1_000, 2, data_dir=self.tmp, verbose=False)
        mtime = data.stat().st_mtime_ns
        gen_datasets.generate("s", 1_000, 2, data_dir=self.tmp, verbose=False)
        self.assertEqual(data.stat().st_mtime_ns, mtime)
        self.assertTrue((self.tmp / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
