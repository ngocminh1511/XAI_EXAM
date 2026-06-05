import json
import unittest
from pathlib import Path

from app.config import config
from app.modules.knowledge_base import InMemoryKB


class KnowledgeBaseExpansionTests(unittest.TestCase):
    def test_structured_laws_have_answer_type(self):
        data = json.loads(Path(config.kb_path).read_text(encoding="utf-8"))
        kb_data = data.get("knowledge_base", data)
        laws = [
            law
            for topic in kb_data.get("topics", [])
            for law in topic.get("laws", [])
        ]

        self.assertGreaterEqual(len(laws), 79)
        self.assertTrue(all(law.get("answer_type") for law in laws))

    def test_reference_docs_expand_kb_to_plan_floor(self):
        kb = InMemoryKB()
        count = kb.load_from_json(config.kb_path)

        self.assertGreaterEqual(count, 300)

    def test_answer_type_is_searchable_and_returned_in_premise(self):
        kb = InMemoryKB()
        kb.load_from_json(config.kb_path)

        results = kb.search("electric potential scalar superposition", top_k=3)
        self.assertTrue(results)
        self.assertTrue(any(entry.answer_type for entry, _ in results))
        self.assertTrue(any("Answer type:" in entry.premise_string for entry, _ in results))

    def test_reference_docs_improve_topic_specific_retrieval(self):
        kb = InMemoryKB()
        kb.load_from_json(config.kb_path)

        queries = {
            "LCNS random error": "THCB",
            "Is RLC circuit at resonance Yes No": "CHLT",
            "capacitor disconnected distance doubled": "TD",
        }

        for query, expected_prefix in queries.items():
            with self.subTest(query=query):
                results = kb.search(query, top_k=3)
                self.assertTrue(
                    any(entry.topic_prefix == expected_prefix for entry, _ in results),
                    [entry.topic_prefix for entry, _ in results],
                )


if __name__ == "__main__":
    unittest.main()
