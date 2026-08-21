from typing import List, Optional
import numpy as np
from src.utils.logger import get_logger

logger = get_logger("semantic_matcher")

class SemanticMatcher:
    """Semantic Matcher using SentenceTransformers or TF-IDF Cosine Similarity fallback."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._st_model = None
        self._tfidf_vectorizer = None
        self._init_model()

    def _init_model(self):
        """Attempts to load SentenceTransformer model."""
        try:
            from sentence_transformers import SentenceTransformer
            self._st_model = SentenceTransformer(self.model_name)
            logger.info(f"Loaded SentenceTransformer model '{self.model_name}' successfully.")
            return
        except Exception as e:
            logger.warning(f"SentenceTransformers unavailable or model failed to load ({e}). Using TF-IDF fallback.")

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._tfidf_vectorizer = TfidfVectorizer(stop_words='english')
            logger.info("Initialized TF-IDF vectorizer fallback for semantic similarity.")
        except Exception as e:
            logger.error(f"Failed to initialize scikit-learn TF-IDF: {e}")

    def compute_semantic_similarity(self, text1: str, text2: str) -> float:
        """Computes cosine semantic similarity between two texts (0.0 to 100.0)."""
        if not text1 or not text2:
            return 0.0

        if text1 == text2:
            return 100.0

        # Truncate ultra-long text to avoid memory issues
        t1 = text1[:4000]
        t2 = text2[:4000]

        # 1. SentenceTransformers
        if self._st_model:
            try:
                emb = self._st_model.encode([t1, t2], show_progress_bar=False)
                v1, v2 = emb[0], emb[1]
                norm1, norm2 = np.linalg.norm(v1), np.linalg.norm(v2)
                if norm1 == 0 or norm2 == 0:
                    return 0.0
                cosine_sim = float(np.dot(v1, v2) / (norm1 * norm2))
                return max(0.0, min(100.0, cosine_sim * 100.0))
            except Exception as e:
                logger.error(f"Error computing SentenceTransformer embeddings: {e}")

        # 2. TF-IDF Fallback
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            vectorizer = TfidfVectorizer(stop_words='english')
            tfidf_matrix = vectorizer.fit_transform([t1, t2])
            sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return float(sim * 100.0)
        except Exception as e:
            logger.error(f"Error computing TF-IDF similarity: {e}")

        return 0.0

    def compute_embedding(self, text: str) -> List[float]:
        """Computes a fixed embedding vector for a single text (for index-time caching)."""
        if not text:
            return []
        t = text[:4000]
        if self._st_model:
            try:
                emb = self._st_model.encode([t], show_progress_bar=False)
                return [float(x) for x in emb[0]]
            except Exception as e:
                logger.error(f"Error computing single embedding: {e}")
        return []

    def cosine_from_embeddings(self, target_emb: List[float], candidate_embs: List[List[float]]) -> List[float]:
        """Computes cosine similarity between a target embedding and candidate embeddings (0.0 to 100.0)."""
        if not target_emb or not candidate_embs:
            return []
        try:
            v_target = np.array(target_emb, dtype=float)
            norm_target = np.linalg.norm(v_target)
            if norm_target == 0:
                return [0.0] * len(candidate_embs)
            matrix = np.array(candidate_embs, dtype=float)
            norms = np.linalg.norm(matrix, axis=1)
            norms = np.where(norms == 0, 1e-9, norms)
            dots = np.dot(matrix, v_target)
            cosine_sims = dots / (norms * norm_target)
            return np.clip(cosine_sims * 100.0, 0.0, 100.0).tolist()
        except Exception as e:
            logger.error(f"Error computing cosine from cached embeddings: {e}")
            return []

    def compute_semantic_similarity_batch(self, target_text: str, candidate_texts: List[str]) -> List[float]:
        """Batch computes cosine semantic similarity between target_text and candidate_texts (0.0 to 100.0)."""
        if not candidate_texts:
            return []

        if not target_text:
            return [0.0] * len(candidate_texts)

        target_truncated = target_text[:4000]
        candidates_truncated = [c[:4000] if c else "" for c in candidate_texts]

        # 1. SentenceTransformers Batch Vector Encoding
        if self._st_model:
            try:
                all_texts = [target_truncated] + candidates_truncated
                embeddings = self._st_model.encode(all_texts, batch_size=64, show_progress_bar=False)

                v_target = embeddings[0]
                v_candidates = embeddings[1:]

                norm_target = np.linalg.norm(v_target)
                norm_candidates = np.linalg.norm(v_candidates, axis=1)

                if norm_target == 0:
                    return [0.0] * len(candidate_texts)

                norm_candidates = np.where(norm_candidates == 0, 1e-9, norm_candidates)

                dots = np.dot(v_candidates, v_target)
                cosine_sims = dots / (norm_candidates * norm_target)

                scores = np.clip(cosine_sims * 100.0, 0.0, 100.0)
                return scores.tolist()
            except Exception as e:
                logger.error(f"Error computing SentenceTransformer batch embeddings: {e}")

        # 2. TF-IDF Matrix Fallback
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            vectorizer = TfidfVectorizer(stop_words='english')
            all_texts = [target_truncated] + candidates_truncated
            tfidf_matrix = vectorizer.fit_transform(all_texts)

            target_vec = tfidf_matrix[0:1]
            cand_vecs = tfidf_matrix[1:]

            sims = cosine_similarity(cand_vecs, target_vec).flatten()
            scores = np.clip(sims * 100.0, 0.0, 100.0)
            return scores.tolist()
        except Exception as e:
            logger.error(f"Error computing TF-IDF batch similarity: {e}")

        return [self.compute_semantic_similarity(target_text, c) for c in candidate_texts]

