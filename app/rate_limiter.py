"""
Rate limiting using Redis to prevent API abuse.
"""

import time
from typing import Optional
import redis
from app.config import settings
from app.exceptions import RateLimitError


class RateLimiter:
    """
    Token bucket rate limiter using Redis.
    """
    
    def __init__(self, redis_client: redis.Redis):
        """
        Initialize rate limiter.
        
        Args:
            redis_client: Redis client instance
        """
        self.redis = redis_client
    
    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
        cost: int = 1
    ) -> bool:
        """
        Check if request is within rate limit using sliding window.
        
        Args:
            key: Unique identifier for the rate limit (e.g., "api:user:123")
            max_requests: Maximum number of requests allowed in window
            window_seconds: Time window in seconds
            cost: Cost of this request (default 1)
        
        Returns:
            True if within rate limit
            
        Raises:
            RateLimitError: If rate limit exceeded
        """
        now = time.time()
        window_start = now - window_seconds
        
        # Redis key for this rate limit
        redis_key = f"ratelimit:{key}"
        
        # Use sorted set with timestamps as scores
        pipe = self.redis.pipeline()
        
        # Remove old entries outside the window
        pipe.zremrangebyscore(redis_key, 0, window_start)
        
        # Count current requests in window
        pipe.zcard(redis_key)
        
        # Add current request
        pipe.zadd(redis_key, {f"{now}:{id(self)}": now})
        
        # Set expiry on the key
        pipe.expire(redis_key, window_seconds + 1)
        
        results = pipe.execute()
        current_count = results[1]
        
        # Check if over limit (before adding current request)
        if current_count >= max_requests:
            raise RateLimitError(
                f"Rate limit exceeded: {current_count}/{max_requests} requests in {window_seconds}s",
                details={
                    "limit": max_requests,
                    "window_seconds": window_seconds,
                    "current_count": current_count
                }
            )
        
        return True
    
    def get_remaining(
        self,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> int:
        """
        Get remaining requests in current window.
        
        Args:
            key: Unique identifier for the rate limit
            max_requests: Maximum number of requests allowed
            window_seconds: Time window in seconds
        
        Returns:
            Number of remaining requests
        """
        now = time.time()
        window_start = now - window_seconds
        
        redis_key = f"ratelimit:{key}"
        
        # Count requests in current window
        count = self.redis.zcount(redis_key, window_start, now)
        
        return max(0, max_requests - count)
    
    def reset(self, key: str):
        """
        Reset rate limit for a key.
        
        Args:
            key: Unique identifier for the rate limit
        """
        redis_key = f"ratelimit:{key}"
        self.redis.delete(redis_key)


# Decorator for rate limiting endpoints
def rate_limit(max_requests: int = 60, window_seconds: int = 60):
    """
    Decorator to rate limit a function.
    
    Args:
        max_requests: Maximum requests allowed
        window_seconds: Time window in seconds
    
    Usage:
        @rate_limit(max_requests=10, window_seconds=60)
        def my_endpoint():
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # This is a placeholder - actual implementation would need
            # to extract user/IP from request context
            limiter = RateLimiter(redis.Redis.from_url(settings.REDIS_URL))
            limiter.check_rate_limit(
                key=f"api:{func.__name__}",
                max_requests=max_requests,
                window_seconds=window_seconds
            )
            return func(*args, **kwargs)
        return wrapper
    return decorator
