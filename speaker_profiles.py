"""
Speaker voice profile management for speaker recognition.

Provides embedding extraction, storage, and matching against enrolled speaker profiles.
Uses pyannote speaker embeddings via the WhisperX DiarizationPipeline.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SpeakerProfile:
    """A speaker's voice profile with one or more embedding samples."""

    name: str
    embeddings: list[list[float]] = field(default_factory=list)
    centroid: list[float] = field(default_factory=list)
    sample_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        self.sample_count = len(self.embeddings)
        if self.embeddings and not self.centroid:
            self.centroid = compute_centroid(self.embeddings)

    def add_embedding(self, embedding: list[float]):
        """Add a new embedding sample and recompute the centroid."""
        self.embeddings.append(embedding)
        self.sample_count = len(self.embeddings)
        self.centroid = compute_centroid(self.embeddings)
        self.updated_at = datetime.now().isoformat()


def compute_centroid(embeddings: list[list[float]]) -> list[float]:
    """Average multiple embeddings into a single centroid vector."""
    arr = np.array(embeddings)
    centroid = arr.mean(axis=0)
    # L2-normalize the centroid for consistent cosine similarity
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    return centroid.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def load_profiles(path: str) -> dict[str, SpeakerProfile]:
    """Load speaker profiles from a JSON file."""
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    profiles = {}
    for name, info in data.items():
        profiles[name] = SpeakerProfile(
            name=info["name"],
            embeddings=info["embeddings"],
            centroid=info.get("centroid", []),
            sample_count=info.get("sample_count", len(info["embeddings"])),
            created_at=info.get("created_at", ""),
            updated_at=info.get("updated_at", ""),
        )
    return profiles


def save_profiles(profiles: dict[str, SpeakerProfile], path: str):
    """Save speaker profiles to a JSON file."""
    data = {}
    for name, profile in profiles.items():
        data[name] = {
            "name": profile.name,
            "embeddings": profile.embeddings,
            "centroid": profile.centroid,
            "sample_count": profile.sample_count,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved {len(profiles)} speaker profile(s) to {path}")


def match_speakers(
    speaker_embeddings: dict[str, np.ndarray],
    profiles: dict[str, SpeakerProfile],
    threshold: float = 0.55,
) -> dict[str, str]:
    """
    Match diarized speaker labels to enrolled profiles using cosine similarity.

    Uses greedy 1:1 matching: highest similarity pair wins, each profile name
    is used at most once.

    Args:
        speaker_embeddings: dict mapping SPEAKER_XX → embedding vector
        profiles: enrolled speaker profiles
        threshold: minimum cosine similarity to accept a match

    Returns:
        dict mapping SPEAKER_XX → recognized name (only for matches above threshold)
    """
    if not speaker_embeddings or not profiles:
        return {}

    # Build similarity matrix: (speaker_label, profile_name, similarity)
    scores = []
    for speaker_label, embedding in speaker_embeddings.items():
        emb = embedding if isinstance(embedding, list) else embedding.tolist()
        for profile_name, profile in profiles.items():
            if not profile.centroid:
                continue
            sim = cosine_similarity(emb, profile.centroid)
            scores.append((speaker_label, profile_name, sim))

    # Sort by similarity descending for greedy matching
    scores.sort(key=lambda x: x[2], reverse=True)

    matched_speakers: dict[str, str] = {}
    used_profiles: set[str] = set()

    for speaker_label, profile_name, sim in scores:
        if speaker_label in matched_speakers:
            continue
        if profile_name in used_profiles:
            continue
        if sim < threshold:
            continue

        matched_speakers[speaker_label] = profile_name
        used_profiles.add(profile_name)
        logger.info(
            f"Matched {speaker_label} → {profile_name} (similarity: {sim:.3f})"
        )

    return matched_speakers


def extract_embedding_from_audio(
    audio_path: str, hf_token: str, device: str = "cpu"
) -> list[float]:
    """
    Extract a speaker embedding from an audio file.

    Runs the DiarizationPipeline with num_speakers=1 and return_embeddings=True
    to get a single speaker embedding.
    """
    import functools
    import torch

    # Ensure the torch.load patch is active for pyannote compatibility
    _original_torch_load = torch.load

    @functools.wraps(_original_torch_load)
    def _patched_torch_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return _original_torch_load(*args, **kwargs)

    torch.load = _patched_torch_load

    try:
        from whisperx.diarize import DiarizationPipeline

        pipeline = DiarizationPipeline(
            use_auth_token=hf_token,
            device=device,
        )

        diarize_result = pipeline(
            audio_path,
            num_speakers=1,
            return_embeddings=True,
        )

        # When return_embeddings=True, result is a tuple: (segments_df, embeddings_dict)
        if isinstance(diarize_result, tuple) and len(diarize_result) == 2:
            _, embeddings = diarize_result
            if embeddings:
                # Get the first (and only, since num_speakers=1) embedding
                for speaker_label, emb in embeddings.items():
                    embedding = emb if isinstance(emb, list) else emb.tolist()
                    # L2-normalize
                    arr = np.array(embedding)
                    norm = np.linalg.norm(arr)
                    if norm > 0:
                        arr = arr / norm
                    return arr.tolist()

        raise ValueError(
            "DiarizationPipeline did not return embeddings. "
            "Check that the audio contains speech."
        )
    finally:
        torch.load = _original_torch_load
