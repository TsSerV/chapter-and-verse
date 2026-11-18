"""Turn text into vectors, with a small model that runs on a CPU."""

import os
from typing import Protocol

from fastembed import TextEmbedding

# 384 numbers per text, and it reads at most 512 tokens of it.
MODEL = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class FastEmbedder:
    def __init__(self) -> None:
        # Reads the model from FASTEMBED_CACHE_PATH when it is set. Without it, fastembed
        # downloads the model on first use into the temp folder.
        self._model = TextEmbedding(MODEL, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH"))

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]

    def query(self, text: str) -> list[float]:
        # The model was trained with a short instruction in front of each question.
        vector: list[float] = next(iter(self._model.query_embed(text))).tolist()
        return vector
