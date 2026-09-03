from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


# --- Async LRU Cache ---

@dataclass
class CacheEntry(Generic[T]):
    """Cache entry with expiration."""
    value: T
    expires_at: float
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0


class AsyncLRUCache(Generic[T]):
    """Thread-safe async LRU cache with TTL support."""
    
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: float = 300.0,  # 5 minutes default
    ):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: dict[str, CacheEntry[T]] = {}
        self._access_order: list[str] = []  # LRU tracking
        self._lock = asyncio.Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expired": 0,
        }
    
    def _make_key(self, key: str | tuple) -> str:
        """Create cache key from various input types."""
        if isinstance(key, str):
            return key
        if isinstance(key, tuple):
            return hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()
        return str(key)
    
    def _is_expired(self, entry: CacheEntry[T]) -> bool:
        """Check if cache entry is expired."""
        return time.time() > entry.expires_at
    
    def _evict_lru(self):
        """Evict least recently used entry."""
        if self._access_order:
            lru_key = self._access_order.pop(0)
            if lru_key in self._cache:
                del self._cache[lru_key]
                self._stats["evictions"] += 1
    
    def _update_access(self, key: str):
        """Update LRU access order."""
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
    
    async def get(self, key: str | tuple) -> T | None:
        """Get value from cache."""
        cache_key = self._make_key(key)
        
        async with self._lock:
            if cache_key not in self._cache:
                self._stats["misses"] += 1
                return None
            
            entry = self._cache[cache_key]
            
            if self._is_expired(entry):
                del self._cache[cache_key]
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                self._stats["expired"] += 1
                self._stats["misses"] += 1
                return None
            
            # Update access order and hit count
            entry.hit_count += 1
            self._update_access(cache_key)
            self._stats["hits"] += 1
            return entry.value
    
    async def set(
        self,
        key: str | tuple,
        value: T,
        ttl: float | None = None,
    ):
        """Set value in cache."""
        cache_key = self._make_key(key)
        ttl = ttl or self.default_ttl
        expires_at = time.time() + ttl
        
        async with self._lock:
            # Check if we need to evict
            if len(self._cache) >= self.max_size and cache_key not in self._cache:
                self._evict_lru()
            
            self._cache[cache_key] = CacheEntry(
                value=value,
                expires_at=expires_at,
            )
            self._update_access(cache_key)
    
    async def delete(self, key: str | tuple) -> bool:
        """Delete key from cache."""
        cache_key = self._make_key(key)
        
        async with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                return True
            return False
    
    async def clear(self):
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._stats = {"hits": 0, "misses": 0, "evictions": 0, "expired": 0}
    
    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        async with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._cache.items() 
                if v.expires_at <= now
            ]
            for key in expired_keys:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
            self._stats["expired"] += len(expired_keys)
            return len(expired_keys)
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0.0
        return {
            **self._stats,
            "size": len(self._cache),
            "max_size": self.max_size,
            "hit_rate": round(hit_rate, 4),
        }


# --- Global Cache Instances ---

_query_cache = AsyncLRUCache[Any](max_size=500, default_ttl=60.0)  # 1 min for queries
_object_cache = AsyncLRUCache[Any](max_size=1000, default_ttl=300.0)  # 5 min for objects
_analytics_cache = AsyncLRUCache[Any](max_size=100, default_ttl=600.0)  # 10 min for analytics


async def get_query_cache() -> AsyncLRUCache:
    """Get query cache instance."""
    return _query_cache


async def get_object_cache() -> AsyncLRUCache:
    """Get object cache instance."""
    return _object_cache


async def get_analytics_cache() -> AsyncLRUCache:
    """Get analytics cache instance."""
    return _analytics_cache


# --- Cache Decorators ---

def cached(
    cache: AsyncLRUCache | None = None,
    ttl: float | None = None,
    key_builder: Callable[..., str | tuple] | None = None,
):
    """Decorator to cache async function results."""
    if cache is None:
        cache = _object_cache
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                # Default: use function name + args + kwargs
                cache_key = (
                    func.__module__,
                    func.__qualname__,
                    args,
                    tuple(sorted(kwargs.items())),
                )
            
            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Call function and cache result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, ttl)
            return result
        
        return wrapper
    return decorator


def invalidate_cache(cache: AsyncLRUCache | None = None, key_builder: Callable | None = None):
    """Decorator to invalidate cache after function execution."""
    if cache is None:
        cache = _object_cache
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
                await cache.delete(cache_key)
            
            return result
        return wrapper
    return decorator


# --- Database Connection Pool Optimization ---

class ConnectionPoolManager:
    """Manages database connection pools with health checks."""
    
    def __init__(self):
        self._pools: dict[str, Any] = {}
        self._configs: dict[str, dict] = {}
    
    def configure_pool(
        self,
        name: str,
        dsn: str,
        min_size: int = 5,
        max_size: int = 20,
        timeout: float = 30.0,
        command_timeout: float = 60.0,
    ):
        """Configure a connection pool."""
        self._configs[name] = {
            "dsn": dsn,
            "min_size": min_size,
            "max_size": max_size,
            "timeout": timeout,
            "command_timeout": command_timeout,
        }
    
    async def get_pool(self, name: str):
        """Get or create connection pool."""
        if name not in self._pools:
            config = self._configs.get(name)
            if not config:
                raise ValueError(f"Pool config '{name}' not found")
            
            # In production, would use asyncpg.create_pool
            # pool = await asyncpg.create_pool(**config)
            # self._pools[name] = pool
            
            # Placeholder
            self._pools[name] = None
        
        return self._pools[name]
    
    async def close_all(self):
        """Close all connection pools."""
        for pool in self._pools.values():
            if pool:
                await pool.close()
        self._pools.clear()


# Global connection pool manager
_pool_manager = ConnectionPoolManager()


async def get_pool_manager() -> ConnectionPoolManager:
    """Get global connection pool manager."""
    return _pool_manager


# --- Query Optimization Utilities ---

class QueryOptimizer:
    """Utilities for query optimization."""
    
    @staticmethod
    def build_pagination_query(
        base_query: str,
        page: int,
        per_page: int,
        order_by: str = "created_at DESC",
    ) -> str:
        """Add pagination to query."""
        offset = (page - 1) * per_page
        return f"{base_query} ORDER BY {order_by} LIMIT {per_page} OFFSET {offset}"
    
    @staticmethod
    def build_count_query(base_query: str) -> str:
        """Build count query from select query."""
        # Simple implementation - in production would use SQL parser
        if "ORDER BY" in base_query.upper():
            base_query = base_query[:base_query.upper().rindex("ORDER BY")]
        return f"SELECT COUNT(*) FROM ({base_query}) AS subquery"
    
    @staticmethod
    def suggest_indexes(query: str, table: str) -> list[str]:
        """Suggest indexes based on query patterns (simplified)."""
        suggestions = []
        query_upper = query.upper()
        
        # Check WHERE clauses
        import re
        where_matches = re.findall(r'WHERE\s+(.+?)(?:\s+(?:ORDER|GROUP|LIMIT)|$)', query, re.IGNORECASE)
        for where in where_matches:
            # Find column names
            columns = re.findall(r'(\w+)\s*[=<>!]', where)
            for col in columns:
                suggestions.append(f"CREATE INDEX idx_{table}_{col} ON {table} ({col})")
        
        # Check JOIN conditions
        join_matches = re.findall(r'JOIN\s+\w+\s+ON\s+(.+?)(?:\s+(?:WHERE|JOIN|ORDER|GROUP|LIMIT)|$)', query, re.IGNORECASE)
        for join in join_matches:
            cols = re.findall(r'(\w+\.\w+)\s*=', join)
            for col in cols:
                table_name, col_name = col.split('.')
                suggestions.append(f"CREATE INDEX idx_{table_name}_{col_name} ON {table_name} ({col_name})")
        
        return list(set(suggestions))


# --- Pagination Helper ---

@dataclass
class PaginationParams:
    """Pagination parameters."""
    page: int = 1
    per_page: int = 20
    max_per_page: int = 100
    
    def __post_init__(self):
        self.page = max(1, self.page)
        self.per_page = min(max(1, self.per_page), self.max_per_page)
        self.offset = (self.page - 1) * self.per_page


@dataclass
class PaginatedResponse(Generic[T]):
    """Paginated response."""
    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_prev: bool


async def paginate_query(
    query_func: Callable,
    count_func: Callable,
    params: PaginationParams,
) -> PaginatedResponse:
    """Execute paginated query."""
    # Get total count
    total = await count_func()
    
    # Get items
    items = await query_func(params.offset, params.per_page)
    
    total_pages = (total + params.per_page - 1) // params.per_page
    
    return PaginatedResponse(
        items=items,
        total=total,
        page=params.page,
        per_page=params.per_page,
        total_pages=total_pages,
        has_next=params.page < total_pages,
        has_prev=params.page > 1,
    )


# --- Background Task Optimization ---

class BatchProcessor(Generic[T]):
    """Batch processor for efficient bulk operations."""
    
    def __init__(
        self,
        batch_size: int = 100,
        flush_interval: float = 5.0,
        processor: Callable[[list[T]], Any] | None = None,
    ):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.processor = processor
        self._buffer: list[T] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
    
    async def add(self, item: T):
        """Add item to batch."""
        async with self._lock:
            self._buffer.append(item)
            if len(self._buffer) >= self.batch_size:
                await self._flush()
    
    async def _flush(self):
        """Flush buffer to processor."""
        if not self._buffer or not self.processor:
            return
        
        batch = self._buffer[:]
        self._buffer.clear()
        
        try:
            await self.processor(batch)
        except Exception as e:
            logger.error("batch_processor_error", error=str(e))
            # Re-add failed items
            self._buffer = batch + self._buffer
    
    async def flush(self):
        """Force flush buffer."""
        async with self._lock:
            await self._flush()
    
    async def start(self):
        """Start periodic flush task."""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())
    
    async def _periodic_flush(self):
        while True:
            await asyncio.sleep(self.flush_interval)
            await self.flush()
    
    async def stop(self):
        """Stop periodic flush and flush remaining."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()


# --- Background Cleanup Task ---

async def start_cache_cleanup_task(
    interval: float = 300.0,  # 5 minutes
):
    """Start background cache cleanup task."""
    async def cleanup():
        while True:
            try:
                await asyncio.sleep(interval)
                await _query_cache.cleanup_expired()
                await _object_cache.cleanup_expired()
                await _analytics_cache.cleanup_expired()
                logger.debug("cache_cleanup_completed")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cache_cleanup_error", error=str(e))
    
    return asyncio.create_task(cleanup())


# --- Response Compression ---

def should_compress(response: Response, minimum_size: int = 500) -> bool:
    """Determine if response should be compressed."""
    content_length = response.headers.get("content-length")
    if content_length and int(content_length) < minimum_size:
        return False
    
    content_type = response.headers.get("content-type", "")
    compressible_types = [
        "application/json",
        "text/",
        "application/xml",
        "application/javascript",
    ]
    return any(content_type.startswith(t) for t in compressible_types)


# --- Performance Monitoring ---

class PerformanceMonitor:
    """Monitor API performance metrics."""
    
    def __init__(self):
        self._metrics: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()
    
    async def record(self, endpoint: str, duration_ms: float):
        """Record request duration."""
        async with self._lock:
            if endpoint not in self._metrics:
                self._metrics[endpoint] = []
            self._metrics[endpoint].append(duration_ms)
            # Keep only last 1000 measurements
            if len(self._metrics[endpoint]) > 1000:
                self._metrics[endpoint] = self._metrics[endpoint][-1000:]
    
    def get_stats(self, endpoint: str | None = None) -> dict[str, Any]:
        """Get performance statistics."""
        if endpoint:
            durations = self._metrics.get(endpoint, [])
            if not durations:
                return {}
            return self._calculate_stats(durations)
        
        return {
            ep: self._calculate_stats(durations)
            for ep, durations in self._metrics.items()
        }
    
    def _calculate_stats(self, durations: list[float]) -> dict[str, float]:
        if not durations:
            return {}
        sorted_d = sorted(durations)
        n = len(sorted_d)
        return {
            "count": n,
            "mean": sum(sorted_d) / n,
            "median": sorted_d[n // 2],
            "p95": sorted_d[int(n * 0.95)],
            "p99": sorted_d[int(n * 0.99)],
            "min": sorted_d[0],
            "max": sorted_d[-1],
        }


# Global performance monitor
_performance_monitor = PerformanceMonitor()


async def get_performance_monitor() -> PerformanceMonitor:
    """Get global performance monitor."""
    return _performance_monitor


# --- Middleware for Performance Monitoring ---

class PerformanceMonitoringMiddleware:
    """Middleware to monitor request performance."""
    
    def __init__(self, app: ASGIApp):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                duration = (time.time() - start_time) * 1000
                path = scope.get("path", "/")
                await _performance_monitor.record(path, duration)
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


# --- Setup Function ---

def setup_performance_optimization(app: Any):
    """Setup performance optimizations for FastAPI app."""
    # Add performance monitoring middleware
    app.add_middleware(PerformanceMonitoringMiddleware)
    
    # Start background cache cleanup
    @app.on_event("startup")
    async def startup_cache_cleanup():
        app.state._cache_cleanup_task = await start_cache_cleanup_task()
    
    @app.on_event("shutdown")
    async def shutdown_cache_cleanup():
        if hasattr(app.state, "_cache_cleanup_task"):
            app.state._cache_cleanup_task.cancel()
            try:
                await app.state._cache_cleanup_task
            except asyncio.CancelledError:
                pass
    
    logger.info("performance_optimization_configured")