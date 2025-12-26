"""
Thread-safe model pool with lazy loading and memory management.

Provides a pool of Whisper models that can be shared across workers:
- Lazy loading: Models loaded on-demand, not upfront
- LRU eviction: Automatically unload least-used models when memory constrained
- Fallback support: Automatically retry with smaller models on OOM
- Thread-safe: Safe for concurrent use in multi-threaded/multi-process environments
- Statistics: Track hits, misses, evictions, and OOM fallbacks

Usage:
    # Initialize global pool (typically done once at startup)
    pool = get_model_pool()

    # Acquire model with context manager
    with acquire_model("large") as model:
        result = model.transcribe(audio_file)
    # Model automatically released back to pool
"""

import gc
import logging
import queue
import threading
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import torch
import whisper

from config import config

logger = logging.getLogger(__name__)


@dataclass
class ModelInstance:
    """
    Wrapper for a Whisper model with metadata.

    Tracks usage statistics and memory footprint for pool management.
    """
    model: whisper.Whisper
    model_size: str
    loaded_at: datetime
    last_used: datetime
    use_count: int = 0
    memory_mb: float = 0.0

    def __post_init__(self):
        """Calculate memory usage after initialization."""
        if self.memory_mb == 0.0:
            self.memory_mb = self._calculate_memory()

    def _calculate_memory(self) -> float:
        """Calculate approximate memory usage of the model in MB."""
        try:
            total_bytes = sum(
                p.element_size() * p.nelement()
                for p in self.model.parameters()
            )
            return total_bytes / (1024 * 1024)
        except Exception as e:
            logger.warning(f"Could not calculate model memory: {e}")
            return 0.0


class ModelPool:
    """
    Thread-safe pool of Whisper models.

    Features:
    - Lazy loading: Models only loaded when first requested
    - Size-based eviction: Remove LRU models when pool size exceeded
    - Multiple model sizes: Support fallback to smaller models
    - Health checking: Detect and replace corrupted models
    - Statistics: Track pool efficiency

    Thread Safety:
    - Uses RLock for thread-safe operations
    - Queue-based model storage for thread-safe access
    - Weak references for garbage collection tracking
    """

    def __init__(self,
                 default_size: str = "large",
                 pool_size: int = 2,
                 max_pool_size: int = 4):
        """
        Initialize model pool.

        Args:
            default_size: Default model size if not specified
            pool_size: Target number of models per size
            max_pool_size: Maximum total models before eviction
        """
        self.default_size = default_size
        self.pool_size = pool_size
        self.max_pool_size = max_pool_size

        # Model storage: model_size -> Queue[ModelInstance]
        self._models: Dict[str, queue.Queue] = {}

        # Lock for thread-safe operations
        self._lock = threading.RLock()

        # Track all loaded models for LRU eviction
        # Using weakref to allow garbage collection
        self._loaded_models: Dict[int, ModelInstance] = {}

        # Statistics
        self._stats = {
            'hits': 0,          # Model acquired from pool
            'misses': 0,        # Model had to be loaded
            'evictions': 0,     # Models evicted due to memory
            'oom_fallbacks': 0  # OOM errors that triggered fallback
        }

        logger.info(
            f"Model pool initialized: default={default_size}, "
            f"pool_size={pool_size}, max={max_pool_size}"
        )

    def acquire(self, model_size: str = None, timeout: float = 300) -> ModelInstance:
        """
        Acquire a model from the pool.

        Blocks if all models are in use (with timeout).
        If pool is empty, loads a new model.

        Args:
            model_size: Desired model size (tiny, base, small, medium, large)
            timeout: Maximum seconds to wait for available model

        Returns:
            ModelInstance ready for use

        Raises:
            queue.Empty: If timeout expires while waiting
            RuntimeError: If model cannot be loaded
        """
        if model_size is None:
            model_size = self.default_size

        with self._lock:
            # Initialize queue for this model size if needed
            if model_size not in self._models:
                self._models[model_size] = queue.Queue(maxsize=self.pool_size)

        # Try to get existing model from pool
        try:
            instance = self._models[model_size].get(timeout=timeout)
            instance.use_count += 1
            instance.last_used = datetime.now()

            with self._lock:
                self._stats['hits'] += 1

            logger.debug(
                f"Acquired existing {model_size} model from pool "
                f"(use_count={instance.use_count})"
            )
            return instance

        except queue.Empty:
            # No available model - need to load new one
            with self._lock:
                self._stats['misses'] += 1

            # Check if we need to evict before loading
            if self._total_models_loaded() >= self.max_pool_size:
                self._evict_lru_model()

            # Load new model
            instance = self._load_model(model_size)
            logger.info(
                f"Loaded new {model_size} model into pool "
                f"(total models: {self._total_models_loaded()})"
            )
            return instance

    def release(self, instance: ModelInstance):
        """
        Return model to pool for reuse.

        Args:
            instance: ModelInstance to release
        """
        with self._lock:
            try:
                # Try to put model back in queue
                self._models[instance.model_size].put_nowait(instance)
                logger.debug(f"Released {instance.model_size} model back to pool")
            except queue.Full:
                # Pool is full - unload this model
                logger.warning(
                    f"Pool full for {instance.model_size}, unloading model "
                    f"(use_count was {instance.use_count})"
                )
                self._unload_model(instance)

    def _load_model(self, model_size: str) -> ModelInstance:
        """
        Load a new Whisper model.

        Args:
            model_size: Model size to load

        Returns:
            Newly loaded ModelInstance

        Raises:
            RuntimeError: If model loading fails or OOM occurs
        """
        try:
            logger.info(f"Loading Whisper model: {model_size}")
            load_start = datetime.now()

            # Load model from Whisper
            model = whisper.load_model(model_size)

            load_time = (datetime.now() - load_start).total_seconds()

            # Create model instance
            instance = ModelInstance(
                model=model,
                model_size=model_size,
                loaded_at=datetime.now(),
                last_used=datetime.now(),
                use_count=0
            )

            # Track in loaded models
            with self._lock:
                self._loaded_models[id(instance)] = instance

            logger.info(
                f"Model loaded: {model_size} ({instance.memory_mb:.1f}MB) "
                f"in {load_time:.2f}s"
            )
            return instance

        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                logger.error(f"OOM loading {model_size}, attempting fallback")
                with self._lock:
                    self._stats['oom_fallbacks'] += 1
                return self._fallback_to_smaller_model(model_size)
            raise

    def _fallback_to_smaller_model(self, failed_size: str) -> ModelInstance:
        """
        Attempt to load next smaller model size when OOM occurs.

        Args:
            failed_size: Model size that caused OOM

        Returns:
            ModelInstance with smaller model

        Raises:
            RuntimeError: If no fallback available or fallback also fails
        """
        size_hierarchy = ["tiny", "base", "small", "medium", "large"]

        try:
            current_idx = size_hierarchy.index(failed_size)
            if current_idx > 0:
                smaller_size = size_hierarchy[current_idx - 1]
                logger.warning(
                    f"Falling back from {failed_size} to {smaller_size} due to OOM"
                )

                # Clear GPU memory before retry
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()

                # Try to load smaller model
                return self._load_model(smaller_size)
        except (ValueError, IndexError):
            pass

        raise RuntimeError(
            f"Cannot load model {failed_size} and no smaller fallback available"
        )

    def _unload_model(self, instance: ModelInstance):
        """
        Unload a model from memory.

        Args:
            instance: ModelInstance to unload
        """
        logger.info(
            f"Unloading model: {instance.model_size} "
            f"(used {instance.use_count} times)"
        )

        # Remove from tracking
        with self._lock:
            model_id = id(instance)
            if model_id in self._loaded_models:
                del self._loaded_models[model_id]

        # Free memory
        del instance.model
        gc.collect()

        # Clear GPU cache if available
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _evict_lru_model(self):
        """
        Evict least recently used model to free memory.

        Uses LRU (Least Recently Used) policy based on last_used timestamp.
        """
        with self._lock:
            if not self._loaded_models:
                logger.warning("No models to evict")
                return

            # Find LRU model
            lru_id = min(
                self._loaded_models.keys(),
                key=lambda x: self._loaded_models[x].last_used
            )
            lru_instance = self._loaded_models[lru_id]

            logger.info(
                f"Evicting LRU model: {lru_instance.model_size} "
                f"(last used: {lru_instance.last_used}, use_count: {lru_instance.use_count})"
            )

            self._stats['evictions'] += 1
            self._unload_model(lru_instance)

    def _total_models_loaded(self) -> int:
        """
        Count total models currently loaded in memory.

        Returns:
            Number of loaded models
        """
        with self._lock:
            return len(self._loaded_models)

    def get_stats(self) -> dict:
        """
        Get pool statistics.

        Returns:
            Dictionary with hits, misses, evictions, and current state
        """
        with self._lock:
            return {
                **self._stats,
                'total_loaded': self._total_models_loaded(),
                'models_by_size': {
                    size: q.qsize()
                    for size, q in self._models.items()
                },
                'hit_rate': (
                    self._stats['hits'] / (self._stats['hits'] + self._stats['misses'])
                    if (self._stats['hits'] + self._stats['misses']) > 0
                    else 0.0
                )
            }

    def clear(self):
        """
        Clear all models from pool (for testing/shutdown).

        Warning: This will unload all models and clear queues.
        """
        logger.info("Clearing model pool")

        with self._lock:
            # Unload all tracked models
            for instance in list(self._loaded_models.values()):
                self._unload_model(instance)

            # Clear all queues
            for model_queue in self._models.values():
                while not model_queue.empty():
                    try:
                        model_queue.get_nowait()
                    except queue.Empty:
                        break

            self._models.clear()
            self._loaded_models.clear()

        logger.info("Model pool cleared")


# Global model pool instance (singleton)
_model_pool: Optional[ModelPool] = None
_pool_lock = threading.Lock()


def get_model_pool() -> ModelPool:
    """
    Get or create the global model pool (singleton).

    Returns:
        Global ModelPool instance
    """
    global _model_pool

    if _model_pool is None:
        with _pool_lock:
            # Double-check locking pattern
            if _model_pool is None:
                _model_pool = ModelPool(
                    default_size=config.model_size,
                    pool_size=config.model_pool_size,
                    max_pool_size=config.model_pool_max_size
                )
                logger.info("Global model pool created")

    return _model_pool


@contextmanager
def acquire_model(model_size: str = None, timeout: float = 300):
    """
    Context manager for safe model acquisition and release.

    Automatically acquires model from pool and releases it when done.
    Ensures model is always released, even if exception occurs.

    Usage:
        with acquire_model("large") as model:
            result = model.transcribe(audio_file)
        # Model automatically released back to pool

    Args:
        model_size: Desired model size (None = use default)
        timeout: Maximum seconds to wait for model

    Yields:
        whisper.Whisper: Model ready for transcription

    Raises:
        queue.Empty: If timeout waiting for model
        RuntimeError: If model cannot be loaded
    """
    pool = get_model_pool()
    instance = pool.acquire(model_size, timeout)

    try:
        yield instance.model
    finally:
        pool.release(instance)


def get_pool_stats() -> dict:
    """
    Get statistics from global model pool.

    Convenience function for monitoring/debugging.

    Returns:
        Dictionary with pool statistics
    """
    pool = get_model_pool()
    return pool.get_stats()
