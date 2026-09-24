import json
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from building_code_demo.answer import OpenAIChatProvider, draft_answer
from building_code_demo.core import Clause, Hit
from building_code_demo.evaluation import evaluate
from building_code_demo.service import DemoService
from building_code_demo.prepare import fetch_verified
from building_code_demo.vector import OpenAIEmbeddingProvider, VectorIndex, build_index, vector_search


class FakeEmbeddingProvider:
    model = "fake-embedding"

    def embed(self, texts):
        return [[1.0, 0.0] if "阳台" in text else [0.0, 1.0] for text in texts]


class FakeChatProvider:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, system, user):
        assert "候选资料" in user
        return json.dumps(self.payload, ensure_ascii=False)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.clauses = [
            Clause("6.6.1", "阳台栏杆高度不应小于1.10m。", 16, 16),
            Clause("5.2.1", "入口台阶应有防护。", 13, 13),
        ]
        self.hit = Hit(self.clauses[0], 5.0)

    def test_vector_index_ranks_and_rejects_stale_corpus(self):
        provider = FakeEmbeddingProvider()
        index = build_index(self.clauses, provider, batch_size=1)
        self.assertEqual(vector_search(self.clauses, index, "阳台栏杆", provider)[0].clause.number, "6.6.1")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "index.json"
            index.save(path)
            loaded = VectorIndex.load(path, self.clauses, provider.model)
            self.assertEqual(loaded.numbers, ["6.6.1", "5.2.1"])
            with self.assertRaises(ValueError):
                VectorIndex.load(path, self.clauses[::-1], provider.model)

    def test_answer_rejects_unknown_citation_and_unseen_measurement(self):
        wrong_citation = FakeChatProvider({"answer": "应检查原图。", "citations": ["9.9.9"], "insufficient": False})
        self.assertEqual(draft_answer("栏杆", [self.hit], wrong_citation).status, "refused")
        invented_number = FakeChatProvider({"answer": "高度是2.50m。", "citations": ["6.6.1"], "insufficient": False})
        self.assertEqual(draft_answer("栏杆", [self.hit], invented_number).status, "refused")

    def test_valid_answer_is_still_marked_draft(self):
        provider = FakeChatProvider({"answer": "候选条文提到1.10m；请核对原图。", "citations": ["6.6.1"], "insufficient": False})
        result = draft_answer("栏杆高度", [self.hit], provider)
        self.assertEqual(result.status, "draft")
        self.assertEqual(result.citations, ["6.6.1"])
        self.assertEqual(draft_answer("缺失条文", [], provider).status, "refused")

    def test_evaluation_reports_failures_without_hiding_them(self):
        cases = [
            {"id": "P", "question": "阳台栏杆", "expected": ["6.6.1"]},
            {"id": "N", "question": "入口", "expected": []},
        ]
        result = evaluate(self.clauses, cases, 1)
        self.assertEqual(result["positive_recall_at_k"], 1.0)
        self.assertEqual(result["negative_no_hit_rate"], 0.0)
        self.assertEqual(result["failures"][0]["id"], "N")

    def test_web_interface_exposes_source_and_declines_unconfigured_model(self):
        try:
            import httpx  # noqa: F401 - FastAPI TestClient requires the optional package.
        except ImportError:
            self.skipTest("optional HTTP test dependency is not installed")
        from fastapi.testclient import TestClient
        from building_code_demo.webapp import create_app

        service = DemoService(self.clauses, [13, 16], "test", "lexical")
        client = TestClient(create_app(service))
        self.assertEqual(client.get("/").status_code, 200)
        self.assertIn("节选", client.get("/api/info").json()["scope"])
        result = client.post("/api/search", json={"question": "阳台栏杆", "top_k": 3})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["hits"][0]["clause"], "6.6.1")
        self.assertIn("#page=16", result.json()["hits"][0]["source_url"])
        self.assertEqual(client.post("/api/answer", json={"question": "阳台栏杆"}).status_code, 409)

    def test_source_download_requires_matching_hash_and_preserves_existing_file(self):
        class FakeResponse(io.BytesIO):
            pass

        data = b"%PDF-test"
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "source.pdf"
            opener = lambda request, timeout: FakeResponse(data)
            self.assertEqual(fetch_verified(output, "https://example.test/source.pdf", digest, opener), "downloaded_verified")
            self.assertEqual(fetch_verified(output, "https://example.test/source.pdf", digest, opener), "already_verified")
            self.assertEqual(output.read_bytes(), data)
            with self.assertRaises(ValueError):
                fetch_verified(output, "https://example.test/source.pdf", "wrong", opener)
            self.assertEqual(output.read_bytes(), data)

    def test_openai_compatible_http_adapters_with_mock_transport(self):
        try:
            import httpx
            from openai import OpenAI
        except ImportError:
            self.skipTest("optional LLM dependencies are not installed")

        paths = []

        def handle(request):
            paths.append(request.url.path)
            payload = json.loads(request.content)
            if request.url.path.endswith("/embeddings"):
                return httpx.Response(200, json={
                    "object": "list", "model": "test-embed", "usage": {"prompt_tokens": 1, "total_tokens": 1},
                    "data": [{"object": "embedding", "index": i, "embedding": [1.0, float(i)]} for i, _ in enumerate(payload["input"])],
                })
            return httpx.Response(200, json={
                "id": "mock", "object": "chat.completion", "created": 0, "model": "test-chat",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"answer":"请核对原图","citations":["6.6.1"],"insufficient":false}'}}],
            })

        client = OpenAI(api_key="test", base_url="https://example.test/v1", http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        embeddings = OpenAIEmbeddingProvider("test", "test-embed", "https://example.test/v1")
        embeddings.client = client
        self.assertEqual(len(embeddings.embed(["a", "b"])), 2)
        chat = OpenAIChatProvider("test", "test-chat", "https://example.test/v1")
        chat.client = client
        self.assertEqual(draft_answer("栏杆", [self.hit], chat).status, "draft")
        self.assertEqual(paths, ["/v1/embeddings", "/v1/chat/completions"])


if __name__ == "__main__":
    unittest.main()
