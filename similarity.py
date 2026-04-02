"""
Paper and node similarity computation with embedding caching.

Supports multiple embedding methods:
  - "tfidf": TF-IDF cosine similarity (no extra dependencies beyond sklearn)
  - "embedding": Sentence-transformer embeddings (requires sentence-transformers)

Caching:
  - Computed embeddings are cached to disk (NumPy .npz files) keyed by a hash
    of the input data + method + model name.
  - Cache files are stored in a configurable directory (default: .cache/embeddings/).
  - On subsequent runs with the same papers and method, embeddings are loaded
    from cache instead of being recomputed — saving significant time for large
    datasets or expensive embedding models.

Provides:
  - Pairwise paper similarity/distance matrices
  - Raw embedding vectors for papers and taxonomy nodes
  - Node-level embeddings for LCA distance computation
"""
import hashlib
import json
import logging
import os
import numpy as np
from typing import Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import config
from models import Paper, TaxonomyNode

logger = logging.getLogger(__name__)

# Default cache directory
EMBEDDING_CACHE_DIR = ".cache/embeddings"


def _compute_cache_key(texts: list[str], method: str, model_name: str = "") -> str:
    """Compute a deterministic hash key for a set of texts + method + model.

    The key is a SHA-256 hex digest so cache files don't leak content.
    """
    hasher = hashlib.sha256()
    hasher.update(method.encode("utf-8"))
    hasher.update(model_name.encode("utf-8"))
    # Hash each text individually to keep memory bounded
    for t in texts:
        hasher.update(t.encode("utf-8"))
    return hasher.hexdigest()[:24]


def _cache_path(cache_dir: str, cache_key: str) -> str:
    """Return the full path for a cache file."""
    return os.path.join(cache_dir, f"emb_{cache_key}.npz")


def save_embeddings(embeddings: np.ndarray, paper_ids: list[str],
                    cache_key: str, cache_dir: str = None):
    """Save embeddings and associated paper IDs to an .npz file."""
    cache_dir = cache_dir or getattr(config, "EMBEDDING_CACHE_DIR", EMBEDDING_CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(cache_dir, cache_key)
    np.savez_compressed(path,
                        embeddings=embeddings,
                        paper_ids=np.array(paper_ids, dtype=object))
    logger.info(f"Saved embedding cache → {path} "
                f"({embeddings.shape[0]} vectors, {embeddings.shape[1]}D)")


def load_embeddings(cache_key: str, cache_dir: str = None
                    ) -> Optional[tuple[np.ndarray, list[str]]]:
    """Load embeddings from cache if available.

    Returns (embeddings, paper_ids) or None if cache miss.
    """
    cache_dir = cache_dir or getattr(config, "EMBEDDING_CACHE_DIR", EMBEDDING_CACHE_DIR)
    path = _cache_path(cache_dir, cache_key)
    if not os.path.isfile(path):
        return None

    try:
        data = np.load(path, allow_pickle=True)
        embeddings = data["embeddings"]
        paper_ids = list(data["paper_ids"])
        logger.info(f"Loaded embedding cache ← {path} "
                    f"({embeddings.shape[0]} vectors, {embeddings.shape[1]}D)")
        return embeddings, paper_ids
    except Exception as e:
        logger.warning(f"Failed to load embedding cache {path}: {e}")
        return None


class SimilarityEngine:
    """Computes pairwise similarity between papers and taxonomy nodes.

    Supports embedding caching: when `use_cache=True` (default), computed
    embeddings are saved to disk and reloaded on subsequent runs with the
    same input data and method.
    """

    def __init__(self, papers: dict[str, Paper], method: str = None,
                 use_cache: bool = True, cache_dir: str = None):
        self.papers = papers
        self.method = method or config.SIMILARITY_METHOD
        self.use_cache = use_cache
        self.cache_dir = cache_dir or getattr(config, "EMBEDDING_CACHE_DIR",
                                               EMBEDDING_CACHE_DIR)
        self._paper_ids: list[str] = []
        self._sim_matrix: Optional[np.ndarray] = None   # N×N similarity
        self._dist_matrix: Optional[np.ndarray] = None   # N×N distance (1-sim)
        self._embeddings: Optional[np.ndarray] = None     # N×D raw embeddings
        self._id_to_idx: dict[str, int] = {}

        # Node embeddings (built on demand)
        self._node_embeddings: dict[str, np.ndarray] = {}

    # ════════════════════════════════════════════════════════════════
    # Paper-level
    # ════════════════════════════════════════════════════════════════

    def build(self):
        """Compute the similarity matrix for all papers.

        If caching is enabled, tries to load from disk first. On cache miss,
        computes fresh and writes the result to disk for future runs.
        """
        self._paper_ids = sorted(self.papers.keys())
        self._id_to_idx = {pid: i for i, pid in enumerate(self._paper_ids)}
        texts = [self.papers[pid].text_for_embedding() for pid in self._paper_ids]

        model_name = config.EMBEDDING_MODEL if self.method == "embedding" else "tfidf"
        cache_key = _compute_cache_key(texts, self.method, model_name)

        # Try loading from cache
        if self.use_cache:
            cached = load_embeddings(cache_key, self.cache_dir)
            if cached is not None:
                cached_emb, cached_ids = cached
                # Validate that cached IDs match current paper set
                if cached_ids == self._paper_ids and cached_emb.shape[0] == len(texts):
                    self._embeddings = cached_emb
                    self._sim_matrix = cosine_similarity(cached_emb).astype(np.float32)
                    self._dist_matrix = 1.0 - self._sim_matrix
                    logger.info(f"Using cached {self.method} embeddings "
                                f"({self._sim_matrix.shape[0]}×{self._sim_matrix.shape[1]})")
                    return
                else:
                    logger.info("Cache key matched but paper IDs differ — recomputing")

        # Compute fresh embeddings
        if self.method == "embedding":
            self._embeddings, self._sim_matrix = self._compute_embedding(texts)
        else:
            self._embeddings, self._sim_matrix = self._compute_tfidf(texts)

        self._dist_matrix = 1.0 - self._sim_matrix

        # Save to cache
        if self.use_cache:
            try:
                save_embeddings(self._embeddings, self._paper_ids,
                                cache_key, self.cache_dir)
            except Exception as e:
                logger.warning(f"Failed to save embedding cache: {e}")

        logger.info(f"Built {self.method} similarity matrix: "
                    f"{self._sim_matrix.shape[0]}×{self._sim_matrix.shape[1]}")

    @property
    def paper_ids(self) -> list[str]:
        if not self._paper_ids:
            self.build()
        return self._paper_ids

    @property
    def sim_matrix(self) -> np.ndarray:
        if self._sim_matrix is None:
            self.build()
        return self._sim_matrix

    @property
    def dist_matrix(self) -> np.ndarray:
        if self._dist_matrix is None:
            self.build()
        return self._dist_matrix

    @property
    def embeddings(self) -> np.ndarray:
        """Raw paper embeddings, shape (N, D)."""
        if self._embeddings is None:
            self.build()
        return self._embeddings

    def paper_embedding(self, pid: str) -> Optional[np.ndarray]:
        """Get the embedding vector for a single paper."""
        idx = self._id_to_idx.get(pid)
        if idx is None:
            return None
        return self.embeddings[idx]

    def similarity(self, pid_a: str, pid_b: str) -> float:
        """Get similarity between two papers by ID."""
        ia = self._id_to_idx.get(pid_a)
        ib = self._id_to_idx.get(pid_b)
        if ia is None or ib is None:
            return 0.0
        return float(self.sim_matrix[ia, ib])

    def distance(self, pid_a: str, pid_b: str) -> float:
        """Get distance (1 - similarity) between two papers by ID."""
        return 1.0 - self.similarity(pid_a, pid_b)

    def submatrix(self, paper_ids: list[str]) -> tuple[list[str], np.ndarray]:
        """Extract the similarity sub-matrix for a subset of papers."""
        indices = [self._id_to_idx[pid] for pid in paper_ids
                   if pid in self._id_to_idx]
        ordered = [self._paper_ids[i] for i in indices]
        sub = self.sim_matrix[np.ix_(indices, indices)]
        return ordered, sub

    def sub_dist_matrix(self, paper_ids: list[str]) -> tuple[list[str], np.ndarray]:
        """Extract the distance sub-matrix for a subset of papers."""
        indices = [self._id_to_idx[pid] for pid in paper_ids
                   if pid in self._id_to_idx]
        ordered = [self._paper_ids[i] for i in indices]
        sub = self.dist_matrix[np.ix_(indices, indices)]
        return ordered, sub

    def nearest_neighbors(self, pid: str, candidates: list[str],
                          k: int = 5) -> list[tuple[str, float]]:
        """Find the k most similar papers to pid from candidates."""
        ia = self._id_to_idx.get(pid)
        if ia is None:
            return []
        scored = []
        for cpid in candidates:
            ib = self._id_to_idx.get(cpid)
            if ib is not None and cpid != pid:
                scored.append((cpid, float(self.sim_matrix[ia, ib])))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    def average_similarity(self, pid: str, group: list[str]) -> float:
        """Average similarity of paper pid to a group of papers."""
        if not group:
            return 0.0
        ia = self._id_to_idx.get(pid)
        if ia is None:
            return 0.0
        sims = []
        for gpid in group:
            ib = self._id_to_idx.get(gpid)
            if ib is not None and gpid != pid:
                sims.append(float(self.sim_matrix[ia, ib]))
        return np.mean(sims) if sims else 0.0

    def average_distance(self, pid: str, group: list[str]) -> float:
        """Average distance of paper pid to a group of papers."""
        return 1.0 - self.average_similarity(pid, group)

    def intra_session_similarity(self, paper_ids: list[str]) -> float:
        """Average pairwise similarity within a set of papers."""
        if len(paper_ids) < 2:
            return 1.0
        indices = [self._id_to_idx[pid] for pid in paper_ids
                   if pid in self._id_to_idx]
        total, count = 0.0, 0
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                total += self.sim_matrix[indices[i], indices[j]]
                count += 1
        return total / count if count else 0.0

    def session_centroid(self, paper_ids: list[str]) -> np.ndarray:
        """Compute the centroid embedding for a set of papers."""
        indices = [self._id_to_idx[pid] for pid in paper_ids
                   if pid in self._id_to_idx]
        if not indices:
            return np.zeros(self.embeddings.shape[1])
        return self.embeddings[indices].mean(axis=0)

    # ════════════════════════════════════════════════════════════════
    # Node-level embeddings
    # ════════════════════════════════════════════════════════════════

    def build_node_embeddings(self, root: TaxonomyNode):
        """Embed each taxonomy node's `name + ". " + description`.

        Node embeddings are also cached when caching is enabled.
        """
        nodes = []
        self._collect_nodes(root, nodes)
        texts = [f"{n.name}. {n.description}" for n in nodes]
        node_ids = [n.node_id for n in nodes]

        model_name = config.EMBEDDING_MODEL if self.method == "embedding" else "tfidf"
        cache_key = _compute_cache_key(texts, self.method + "_nodes", model_name)

        # Try cache
        if self.use_cache:
            cached = load_embeddings(cache_key, self.cache_dir)
            if cached is not None:
                cached_emb, cached_ids = cached
                if list(cached_ids) == node_ids:
                    for nid, emb in zip(node_ids, cached_emb):
                        self._node_embeddings[nid] = emb
                    logger.info(f"Using cached node embeddings for {len(nodes)} nodes")
                    return

        if self.method == "embedding":
            embeddings, _ = self._compute_embedding(texts)
        else:
            embeddings, _ = self._compute_tfidf(texts)

        for nid, emb in zip(node_ids, embeddings):
            self._node_embeddings[nid] = emb

        # Save to cache
        if self.use_cache:
            try:
                save_embeddings(embeddings, node_ids, cache_key, self.cache_dir)
            except Exception as e:
                logger.warning(f"Failed to save node embedding cache: {e}")

        logger.info(f"Built node embeddings for {len(nodes)} taxonomy nodes")

    def node_embedding(self, node_id: str) -> Optional[np.ndarray]:
        """Get the embedding for a taxonomy node."""
        return self._node_embeddings.get(node_id)

    def node_similarity(self, nid_a: str, nid_b: str) -> float:
        """Cosine similarity between two taxonomy nodes."""
        ea = self._node_embeddings.get(nid_a)
        eb = self._node_embeddings.get(nid_b)
        if ea is None or eb is None:
            return 0.0
        return float(cosine_similarity(ea.reshape(1, -1), eb.reshape(1, -1))[0, 0])

    def _collect_nodes(self, node: TaxonomyNode, out: list):
        out.append(node)
        for child in node.children:
            self._collect_nodes(child, out)

    # ════════════════════════════════════════════════════════════════
    # Backend implementations
    # ════════════════════════════════════════════════════════════════

    def _compute_tfidf(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """Return (embeddings, similarity_matrix) using TF-IDF."""
        logger.info("Computing TF-IDF vectors...")
        vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words="english",
            ngram_range=(1, 2),
        )
        tfidf_matrix = vectorizer.fit_transform(texts)
        # Convert sparse to dense for embedding access
        embeddings = tfidf_matrix.toarray().astype(np.float32)
        sim = cosine_similarity(tfidf_matrix).astype(np.float32)
        return embeddings, sim

    def _compute_embedding(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """Return (embeddings, similarity_matrix) using sentence-transformers."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.warning("sentence-transformers not installed, falling back to TF-IDF")
            return self._compute_tfidf(texts)

        logger.info(f"Computing embeddings with {config.EMBEDDING_MODEL}...")
        model = SentenceTransformer(config.EMBEDDING_MODEL)
        embeddings = model.encode(texts, show_progress_bar=True).astype(np.float32)
        sim = cosine_similarity(embeddings).astype(np.float32)
        return embeddings, sim


# ════════════════════════════════════════════════════════════════
# Convenience: clear the embedding cache
# ════════════════════════════════════════════════════════════════

def clear_embedding_cache(cache_dir: str = None):
    """Delete all cached embedding files."""
    cache_dir = cache_dir or getattr(config, "EMBEDDING_CACHE_DIR",
                                      EMBEDDING_CACHE_DIR)
    if not os.path.isdir(cache_dir):
        return
    count = 0
    for f in os.listdir(cache_dir):
        if f.startswith("emb_") and f.endswith(".npz"):
            os.remove(os.path.join(cache_dir, f))
            count += 1
    logger.info(f"Cleared {count} cached embedding file(s) from {cache_dir}")
