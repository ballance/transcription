"""
Unit tests for model_pool.py

Tests the thread-safe model pool implementation including:
- Model acquisition and release
- LRU eviction
- OOM fallback
- Statistics tracking
- Concurrency safety
"""
import pytest
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from model_pool import ModelPool, ModelInstance, acquire_model


class TestModelInstance:
    """Test ModelInstance dataclass."""
    
    def test_model_instance_creation(self, mock_whisper_model):
        """Test ModelInstance can be created with required fields."""
        instance = ModelInstance(
            model=mock_whisper_model,
            model_size="small",
            loaded_at=None,
            last_used=None
        )
        assert instance.model == mock_whisper_model
        assert instance.model_size == "small"
        assert instance.use_count == 0
    
    def test_memory_calculation(self, mock_whisper_model):
        """Test memory footprint calculation."""
        # Mock model parameters
        mock_param = Mock()
        mock_param.element_size.return_value = 4  # 4 bytes per element
        mock_param.nelement.return_value = 1000000  # 1M elements
        mock_whisper_model.parameters.return_value = [mock_param]
        
        instance = ModelInstance(
            model=mock_whisper_model,
            model_size="tiny",
            loaded_at=None,
            last_used=None
        )
        # 4MB expected (4 bytes * 1M elements / 1024 / 1024)
        assert instance.memory_mb > 0


class TestModelPool:
    """Test ModelPool functionality."""
    
    def test_pool_initialization(self):
        """Test pool initializes with correct settings."""
        pool = ModelPool(default_size="medium", pool_size=3, max_pool_size=6)
        assert pool.default_size == "medium"
        assert pool.pool_size == 3
        assert pool.max_pool_size == 6
    
    @patch('model_pool.whisper.load_model')
    def test_acquire_new_model(self, mock_load_model, mock_whisper_model):
        """Test acquiring a model when pool is empty."""
        mock_load_model.return_value = mock_whisper_model
        pool = ModelPool(default_size="tiny", pool_size=2, max_pool_size=4)
        
        instance = pool.acquire(model_size="tiny", timeout=1)
        
        assert instance is not None
        assert instance.model_size == "tiny"
        assert instance.use_count == 0
        mock_load_model.assert_called_once_with("tiny")
    
    @patch('model_pool.whisper.load_model')
    def test_acquire_reuses_released_model(self, mock_load_model, mock_whisper_model):
        """Test that released models are reused from pool."""
        mock_load_model.return_value = mock_whisper_model
        pool = ModelPool(default_size="tiny", pool_size=2, max_pool_size=4)
        
        # Acquire and release a model
        instance1 = pool.acquire(model_size="tiny", timeout=1)
        pool.release(instance1)
        
        # Acquire again - should reuse
        instance2 = pool.acquire(model_size="tiny", timeout=0.1)
        
        # Should be the same instance
        assert instance2 is instance1
        # Load should only be called once
        assert mock_load_model.call_count == 1
        # Use count should increment
        assert instance2.use_count == 1
    
    @patch('model_pool.whisper.load_model')
    def test_pool_statistics(self, mock_load_model, mock_whisper_model):
        """Test pool tracks hits and misses correctly."""
        mock_load_model.return_value = mock_whisper_model
        pool = ModelPool(default_size="tiny", pool_size=2, max_pool_size=4)
        
        # First acquire - miss
        instance1 = pool.acquire(model_size="tiny", timeout=1)
        stats1 = pool.get_stats()
        assert stats1['misses'] == 1
        assert stats1['hits'] == 0
        
        # Release and re-acquire - hit
        pool.release(instance1)
        instance2 = pool.acquire(model_size="tiny", timeout=0.1)
        stats2 = pool.get_stats()
        assert stats2['misses'] == 1
        assert stats2['hits'] == 1
        assert stats2['hit_rate'] == 0.5
        
        pool.release(instance2)
    
    @patch('model_pool.whisper.load_model')
    def test_lru_eviction(self, mock_load_model, mock_whisper_model):
        """Test that LRU eviction works when pool is full."""
        mock_load_model.return_value = mock_whisper_model
        pool = ModelPool(default_size="tiny", pool_size=1, max_pool_size=2)
        
        # Load 2 different models (fills pool to max)
        instance_tiny = pool.acquire(model_size="tiny", timeout=1)
        pool.release(instance_tiny)
        
        instance_base = pool.acquire(model_size="base", timeout=1)
        pool.release(instance_base)
        
        # Loading a third model should evict the LRU one
        instance_small = pool.acquire(model_size="small", timeout=1)
        pool.release(instance_small)
        
        stats = pool.get_stats()
        assert stats['evictions'] >= 1  # Should have evicted at least once
    
    @patch('model_pool.whisper.load_model')
    def test_oom_fallback(self, mock_load_model):
        """Test OOM fallback to smaller model."""
        # Simulate OOM for large model
        def load_model_side_effect(size):
            if size == "large":
                raise RuntimeError("CUDA out of memory")
            else:
                mock_model = Mock()
                return mock_model
        
        mock_load_model.side_effect = load_model_side_effect
        pool = ModelPool(default_size="large", pool_size=1, max_pool_size=2)
        
        # Should fall back to medium
        instance = pool.acquire(model_size="large", timeout=1)
        assert instance is not None
        assert instance.model_size == "medium"
        
        stats = pool.get_stats()
        assert stats['oom_fallbacks'] == 1
    
    @patch('model_pool.whisper.load_model')
    def test_concurrent_access(self, mock_load_model, mock_whisper_model):
        """Test pool is thread-safe with concurrent access."""
        mock_load_model.return_value = mock_whisper_model
        pool = ModelPool(default_size="tiny", pool_size=2, max_pool_size=4)
        
        results = []
        errors = []
        
        def worker():
            try:
                instance = pool.acquire(model_size="tiny", timeout=2)
                time.sleep(0.01)  # Simulate work
                pool.release(instance)
                results.append(True)
            except Exception as e:
                errors.append(e)
        
        # Start 10 threads trying to acquire models
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All threads should succeed
        assert len(results) == 10
        assert len(errors) == 0


@pytest.mark.integration
class TestAcquireModelContextManager:
    """Test the acquire_model context manager."""
    
    @patch('model_pool.get_model_pool')
    def test_context_manager_acquires_and_releases(self, mock_get_pool):
        """Test context manager properly acquires and releases."""
        mock_pool = Mock()
        mock_instance = Mock()
        mock_pool.acquire.return_value = mock_instance
        mock_get_pool.return_value = mock_pool
        
        with acquire_model("small") as model:
            assert model == mock_instance.model
        
        # Should have acquired and released
        mock_pool.acquire.assert_called_once_with("small")
        mock_pool.release.assert_called_once_with(mock_instance)
    
    @patch('model_pool.get_model_pool')
    def test_context_manager_releases_on_exception(self, mock_get_pool):
        """Test model is released even if exception occurs."""
        mock_pool = Mock()
        mock_instance = Mock()
        mock_pool.acquire.return_value = mock_instance
        mock_get_pool.return_value = mock_pool
        
        with pytest.raises(ValueError):
            with acquire_model("small") as model:
                raise ValueError("Test error")
        
        # Should still have released the model
        mock_pool.release.assert_called_once_with(mock_instance)
