import tempfile
import unittest
import json
from pathlib import Path

from finetuning.scripts.prepare_sft_dataset import DEFAULT_DATASET, prepare_dataset


class FineTuningDataPrepTests(unittest.TestCase):
    def test_stratified_split_keeps_all_topics_in_all_splits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = prepare_dataset(DEFAULT_DATASET, Path(tmpdir), seed=42)

        self.assertEqual(manifest["total"], 1352)
        self.assertEqual(sum(manifest["splits"].values()), 1352)

        expected_topics = {"LD", "CH", "NL", "TD", "DDT", "THCB", "DT", "CHLT"}
        self.assertEqual(set(manifest["topics"]), expected_topics)

        for topic, counts in manifest["topics"].items():
            with self.subTest(topic=topic):
                self.assertGreater(counts["train"], 0)
                self.assertGreater(counts["val"], 0)
                self.assertGreater(counts["test"], 0)

        self.assertEqual(manifest["topics"]["CHLT"]["total"], 20)
        self.assertEqual(manifest["topics"]["CHLT"]["train"], 16)
        self.assertEqual(manifest["topics"]["CHLT"]["val"], 2)
        self.assertEqual(manifest["topics"]["CHLT"]["test"], 2)
        self.assertGreater(manifest["trainable_total"], 0)

    def test_sft_records_include_rag_hints_and_no_gold_hardcode_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            prepare_dataset(DEFAULT_DATASET, out_dir, seed=42)
            records = [
                json.loads(line)
                for line in (out_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertTrue(records)
        trainable = [record for record in records if record["trainable"]]
        self.assertTrue(trainable)

        sample = trainable[0]
        for field in ["unit_hints", "topic_hints", "premises", "distractor_premises", "prompt_text", "code_strategy"]:
            self.assertIn(field, sample)

        combined_text = "\n".join(record["text"] for record in trainable[:20])
        self.assertNotIn("Gold supervised answer", combined_text)
        self.assertNotIn("HasGoldAnswer", combined_text)
        self.assertNotIn("DatasetId", combined_text)
        self.assertIn("Relevant physics laws/formulas", combined_text)


if __name__ == "__main__":
    unittest.main()
