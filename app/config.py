"""
Configuration for the Physics AI Pipeline.
Supports .env files and environment variables.
"""
import os
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass
class AppConfig:
    """Central configuration for all pipeline components."""

    # --- General ---
    debug: bool = True
    mode: str = "local"  # "mock" | "local" | "api"

    # --- Paths ---
    base_dir: Path = BASE_DIR
    kb_path: Path = BASE_DIR / "dataset_2" / "physics_knowledge_base.json"
    dataset_path: Path = BASE_DIR / "dataset_2" / "Physics_Problems_Text_Only.csv"

    # --- Qdrant ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "physics_kb"
    use_qdrant: bool = False  # False = use in-memory search

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    use_redis: bool = False  # False = use in-memory dict cache

    # --- Embedding ---
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # --- Reasoner LLM ---
    # reasoner_model: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
    # reasoner_model: str = "deepseek-r1:7b"
    reasoner_model: str = "qwen2.5:7b"
    reasoner_max_tokens: int = 1024
    reasoner_temperature: float = 0.1

    # --- Structurer LLM ---
    structurer_model: str = "Qwen/Qwen2.5-7B-Instruct"
    structurer_max_tokens: int = 512
    structurer_temperature: float = 0.0

    # --- Code Sandbox ---
    sandbox_timeout: int = 5  # seconds
    sandbox_max_retries: int = 2

    # --- RAG ---
    rag_top_k: int = 5
    rag_rerank_top_k: int = 3
    rag_dense_weight: float = 0.7
    rag_sparse_weight: float = 0.3

    # --- API server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    def __post_init__(self):
        """Load overrides from environment variables."""
        self.mode = os.getenv("PIPELINE_MODE", self.mode)
        self.debug = os.getenv("DEBUG", str(self.debug)).lower() == "true"
        self.use_qdrant = os.getenv("USE_QDRANT", str(self.use_qdrant)).lower() == "true"
        self.use_redis = os.getenv("USE_REDIS", str(self.use_redis)).lower() == "true"
        self.qdrant_host = os.getenv("QDRANT_HOST", self.qdrant_host)
        self.redis_host = os.getenv("REDIS_HOST", self.redis_host)


# Singleton config
config = AppConfig()
