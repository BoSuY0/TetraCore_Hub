// Package security provides security infrastructure for TetraCore Hub.
package security

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/tetra/core-hub/internal/infrastructure/redis"
)

// RateLimitConfig holds rate limiting configuration.
type RateLimitConfig struct {
	Requests int           // Max requests
	Window   time.Duration // Time window
	BurstSize int          // Burst allowance
}

// DefaultRateLimitConfig returns default rate limiting configuration.
func DefaultRateLimitConfig() RateLimitConfig {
	return RateLimitConfig{
		Requests:  1000,
		Window:    time.Minute,
		BurstSize: 10,
	}
}

// RateLimitResult represents the result of a rate limit check.
type RateLimitResult struct {
	Allowed    bool
	Remaining  int
	ResetAt    time.Time
	RetryAfter time.Duration
}

// RateLimiter defines the rate limiter interface.
type RateLimiter interface {
	Allow(ctx context.Context, key string) (*RateLimitResult, error)
	Reset(ctx context.Context, key string) error
	GetStatus(ctx context.Context, key string) (*RateLimitResult, error)
}

// InMemoryRateLimiter implements rate limiting using in-memory storage.
type InMemoryRateLimiter struct {
	config  RateLimitConfig
	buckets map[string]*tokenBucket
	mu      sync.RWMutex
}

type tokenBucket struct {
	tokens     float64
	lastRefill time.Time
	requests   int
	windowStart time.Time
}

// NewInMemoryRateLimiter creates a new in-memory rate limiter.
func NewInMemoryRateLimiter(cfg RateLimitConfig) *InMemoryRateLimiter {
	return &InMemoryRateLimiter{
		config:  cfg,
		buckets: make(map[string]*tokenBucket),
	}
}

// Allow checks if a request is allowed.
func (r *InMemoryRateLimiter) Allow(ctx context.Context, key string) (*RateLimitResult, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	now := time.Now()
	bucket := r.getBucket(key, now)

	// Refill tokens based on elapsed time
	r.refillTokens(bucket, now)

	result := &RateLimitResult{
		ResetAt: bucket.windowStart.Add(r.config.Window),
	}

	if bucket.tokens >= 1 {
		bucket.tokens--
		bucket.requests++
		result.Allowed = true
		result.Remaining = int(bucket.tokens)
	} else {
		result.Allowed = false
		result.Remaining = 0
		result.RetryAfter = result.ResetAt.Sub(now)
	}

	return result, nil
}

// Reset resets the rate limit for a key.
func (r *InMemoryRateLimiter) Reset(ctx context.Context, key string) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	delete(r.buckets, key)
	return nil
}

// GetStatus returns the current rate limit status for a key.
func (r *InMemoryRateLimiter) GetStatus(ctx context.Context, key string) (*RateLimitResult, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	now := time.Now()
	bucket, exists := r.buckets[key]
	if !exists {
		return &RateLimitResult{
			Allowed:   true,
			Remaining: r.config.Requests + r.config.BurstSize,
			ResetAt:   now.Add(r.config.Window),
		}, nil
	}

	return &RateLimitResult{
		Allowed:   bucket.tokens >= 1,
		Remaining: int(bucket.tokens),
		ResetAt:   bucket.windowStart.Add(r.config.Window),
	}, nil
}

func (r *InMemoryRateLimiter) getBucket(key string, now time.Time) *tokenBucket {
	bucket, exists := r.buckets[key]
	if !exists {
		bucket = &tokenBucket{
			tokens:      float64(r.config.Requests + r.config.BurstSize),
			lastRefill:  now,
			windowStart: now,
		}
		r.buckets[key] = bucket
	}

	// Reset window if expired
	if now.Sub(bucket.windowStart) >= r.config.Window {
		bucket.tokens = float64(r.config.Requests + r.config.BurstSize)
		bucket.requests = 0
		bucket.windowStart = now
		bucket.lastRefill = now
	}

	return bucket
}

func (r *InMemoryRateLimiter) refillTokens(bucket *tokenBucket, now time.Time) {
	elapsed := now.Sub(bucket.lastRefill)
	if elapsed <= 0 {
		return
	}

	// Calculate tokens to add based on elapsed time
	rate := float64(r.config.Requests) / r.config.Window.Seconds()
	tokensToAdd := rate * elapsed.Seconds()

	bucket.tokens += tokensToAdd
	maxTokens := float64(r.config.Requests + r.config.BurstSize)
	if bucket.tokens > maxTokens {
		bucket.tokens = maxTokens
	}

	bucket.lastRefill = now
}

// Cleanup removes expired buckets.
func (r *InMemoryRateLimiter) Cleanup() int {
	r.mu.Lock()
	defer r.mu.Unlock()

	now := time.Now()
	removed := 0

	for key, bucket := range r.buckets {
		if now.Sub(bucket.windowStart) >= r.config.Window*2 {
			delete(r.buckets, key)
			removed++
		}
	}

	return removed
}

// StartCleanup starts a background cleanup goroutine.
func (r *InMemoryRateLimiter) StartCleanup(interval time.Duration, stopCh <-chan struct{}) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			select {
			case <-stopCh:
				return
			case <-ticker.C:
				r.Cleanup()
			}
		}
	}()
}

// RedisRateLimiter implements rate limiting using Redis.
type RedisRateLimiter struct {
	client *redis.Client
	config RateLimitConfig
	prefix string
}

// NewRedisRateLimiter creates a new Redis-backed rate limiter.
func NewRedisRateLimiter(client *redis.Client, cfg RateLimitConfig) *RedisRateLimiter {
	return &RedisRateLimiter{
		client: client,
		config: cfg,
		prefix: "ratelimit:",
	}
}

// Allow checks if a request is allowed using Redis.
func (r *RedisRateLimiter) Allow(ctx context.Context, key string) (*RateLimitResult, error) {
	redisKey := r.prefix + key
	now := time.Now()

	// Use sliding window algorithm
	windowStart := now.Add(-r.config.Window).UnixNano()
	currentTime := now.UnixNano()

	// Lua script for atomic rate limiting
	script := `
		local key = KEYS[1]
		local window_start = tonumber(ARGV[1])
		local current_time = tonumber(ARGV[2])
		local max_requests = tonumber(ARGV[3])
		local window_ms = tonumber(ARGV[4])

		-- Remove old entries
		redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

		-- Count current requests
		local count = redis.call('ZCARD', key)

		if count < max_requests then
			-- Add new request
			redis.call('ZADD', key, current_time, current_time)
			redis.call('PEXPIRE', key, window_ms)
			return {1, max_requests - count - 1}
		else
			-- Get oldest entry to calculate retry time
			local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
			local retry_after = 0
			if oldest[2] then
				retry_after = oldest[2] + window_ms * 1000000 - current_time
			end
			return {0, 0, retry_after}
		end
	`

	result := r.client.Eval(ctx, script, []string{redisKey}, windowStart, currentTime, r.config.Requests, r.config.Window.Milliseconds())
	vals, err := result.Result()
	if err != nil {
		return nil, err
	}

	arr, ok := vals.([]any)
	if !ok || len(arr) < 2 {
		return &RateLimitResult{Allowed: true, Remaining: r.config.Requests}, nil
	}

	allowed := arr[0].(int64) == 1
	remaining := int(arr[0].(int64))

	res := &RateLimitResult{
		Allowed:   allowed,
		Remaining: remaining,
		ResetAt:   now.Add(r.config.Window),
	}

	if !allowed && len(arr) >= 3 {
		retryNanos := arr[2].(int64)
		res.RetryAfter = time.Duration(retryNanos) * time.Nanosecond
	}

	return res, nil
}

// Reset resets the rate limit for a key.
func (r *RedisRateLimiter) Reset(ctx context.Context, key string) error {
	return r.client.Del(ctx, r.prefix+key)
}

// GetStatus returns the current rate limit status for a key.
func (r *RedisRateLimiter) GetStatus(ctx context.Context, key string) (*RateLimitResult, error) {
	redisKey := r.prefix + key
	now := time.Now()
	windowStart := now.Add(-r.config.Window).UnixNano()

	// Remove old entries and count
	pipe := r.client.Pipeline()
	pipe.ZRemRangeByScore(ctx, redisKey, "-inf", fmt.Sprintf("%d", windowStart))
	countCmd := pipe.ZCard(ctx, redisKey)
	_, err := pipe.Exec(ctx)
	if err != nil {
		return nil, err
	}

	count, _ := countCmd.Result()
	remaining := r.config.Requests - int(count)
	if remaining < 0 {
		remaining = 0
	}

	return &RateLimitResult{
		Allowed:   remaining > 0,
		Remaining: remaining,
		ResetAt:   now.Add(r.config.Window),
	}, nil
}

