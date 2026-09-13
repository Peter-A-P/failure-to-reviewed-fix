"""The text channel: embeddings of the normalised failure text.

Two backends behind one protocol.

HashingEmbedder is the default and needs nothing but numpy: character n-grams hashed into
a fixed number of buckets, sub-linear term weighting, L2 normalised. It is not as good as
a trained sentence encoder at recognising two different descriptions of one bug, and it is
entirely deterministic, offline, and fast enough that the clustering metrics can be
bootstrapped a thousand times in CI. Every reported number says which embedder produced it.

SentenceTransformerEmbedder is the trained one, behind the st extra, imported lazily so
that neither the import nor the model download happens unless it is asked for.

Character n-grams rather than word tokens because failure text is full of identifiers:
get_user_id, UserIdError and user-id share almost no words and a great many character
n-grams, and that is exactly the similarity this channel is for.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

Vectors = npt.NDArray[np.float32]


@runtime_checkable
class Embedder(Protocol):
    """Anything that turns failure texts into L2-normalised row vectors."""

    @property
    def name(self) -> str:
        """Recorded alongside every clustering result, so a number says what made it."""
        ...

    def encode(self, texts: Sequence[str]) -> Vectors: ...


class HashingEmbedder:
    """Hashed character n-grams. Deterministic, offline, no model.

    dimensions is the number of buckets. 2048 is enough that collisions between the
    n-grams of one corpus of failure text are rare, and small enough to keep a pairwise
    distance matrix over a few thousand records cheap.
    """

    def __init__(self, *, dimensions: int = 2048, ngram: tuple[int, int] = (3, 5)) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        low, high = ngram
        if low < 1 or high < low:
            raise ValueError("ngram must be an ascending pair of positive lengths")
        self.dimensions = dimensions
        self.ngram = ngram

    @property
    def name(self) -> str:
        return f"hashing-{self.dimensions}-{self.ngram[0]}to{self.ngram[1]}"

    def _bucket(self, gram: str) -> int:
        # blake2b with a small digest rather than hash(): Python's hash is salted per
        # process, and a clustering result that changes between runs is not a measurement.
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.dimensions

    def _vector(self, text: str) -> npt.NDArray[np.float32]:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        cleaned = " ".join(text.lower().split())
        if not cleaned:
            return vector
        low, high = self.ngram
        for size in range(low, high + 1):
            for i in range(len(cleaned) - size + 1):
                vector[self._bucket(cleaned[i : i + size])] += 1.0
        # Sub-linear weighting: a term repeated twenty times in a long traceback is not
        # twenty times the evidence, and without this the longest text dominates.
        np.log1p(vector, out=vector)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm > 0 else vector

    def encode(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return np.vstack([self._vector(t) for t in texts])


class SentenceTransformerEmbedder:
    """A trained sentence encoder, behind the st extra.

    Imported inside __init__ so that importing mend never pulls torch.
    """

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on an optional extra
            raise ImportError(
                "SentenceTransformerEmbedder needs the st extra: uv sync --extra st"
            ) from exc
        self._model_name = model
        self._model = SentenceTransformer(model)

    @property
    def name(self) -> str:
        return "st-" + self._model_name.rsplit("/", maxsplit=1)[-1]

    def encode(self, texts: Sequence[str]) -> Vectors:  # pragma: no cover - optional extra
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        out = self._model.encode(list(texts), normalize_embeddings=True)
        return np.asarray(out, dtype=np.float32)


def cosine_distances(vectors: Vectors) -> npt.NDArray[np.float64]:
    """Pairwise cosine distance for L2-normalised rows, clipped to the unit interval.

    Clipped because a dot product of exactly 1.0 comes back as 1.0000000000000002 often
    enough to matter, and a negative distance makes scipy linkage produce nonsense rather
    than an error.
    """
    if vectors.shape[0] == 0:
        return np.zeros((0, 0), dtype=np.float64)
    dense = np.asarray(vectors, dtype=np.float64)
    distance = 1.0 - dense @ dense.T
    np.clip(distance, 0.0, 1.0, out=distance)
    np.fill_diagonal(distance, 0.0)
    return distance
