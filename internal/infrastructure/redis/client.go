// Package redis provides Redis client infrastructure for TetraCore Hub.
package redis

import (
	"context"
	"crypto/tls"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/pkg/config"
	"github.com/tetra/core-hub/pkg/logger"
)

// Mode represents the Redis connection mode.
type Mode string

const (
	ModeStandalone Mode = "standalone"
	ModeSentinel   Mode = "sentinel"
	ModeCluster    Mode = "cluster"
)

// Client wraps the Redis client with additional functionality.
type Client struct {
	client      redis.UniversalClient
	mode        Mode
	cfg         *config.RedisConfig
	log         logger.LogFields
	isConnected bool
	mu          sync.RWMutex
}

// NewClient creates a new Redis client based on configuration.
func NewClient(cfg *config.RedisConfig) (*Client, error) {
	log := logger.WithComponent("redis")

	c := &Client{
		cfg: cfg,
		log: logger.LogFields{"component": "redis"},
	}

	var err error

	// Determine connection mode
	if len(cfg.ClusterNodes) > 0 {
		c.mode = ModeCluster
		c.client, err = c.createClusterClient()
	} else if len(cfg.SentinelURLs) > 0 {
		c.mode = ModeSentinel
		c.client, err = c.createSentinelClient()
	} else {
		c.mode = ModeStandalone
		c.client, err = c.createStandaloneClient()
	}

	if err != nil {
		return nil, fmt.Errorf("failed to create redis client: %w", err)
	}

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := c.client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("failed to connect to redis: %w", err)
	}

	c.isConnected = true
	log.Info().Str("mode", string(c.mode)).Msg("Redis client connected")

	return c, nil
}

func (c *Client) createStandaloneClient() (redis.UniversalClient, error) {
	opts, err := c.parseURL(c.cfg.URL)
	if err != nil {
		return nil, err
	}

	opts.PoolSize = c.cfg.MaxConnections
	opts.MinIdleConns = c.cfg.MinIdleConns
	opts.ConnMaxIdleTime = c.cfg.ConnMaxIdleTime
	opts.ConnMaxLifetime = c.cfg.ConnMaxLifetime

	if c.cfg.TLSEnabled {
		opts.TLSConfig = &tls.Config{
			MinVersion: tls.VersionTLS12,
		}
	}

	return redis.NewClient(opts), nil
}

func (c *Client) createSentinelClient() (redis.UniversalClient, error) {
	// Parse sentinel addresses
	var sentinelAddrs []string
	var password string

	for _, urlStr := range c.cfg.SentinelURLs {
		parsed, err := url.Parse(urlStr)
		if err != nil {
			continue
		}
		sentinelAddrs = append(sentinelAddrs, parsed.Host)
		if parsed.User != nil {
			password, _ = parsed.User.Password()
		}
	}

	opts := &redis.FailoverOptions{
		MasterName:       c.cfg.SentinelServiceName,
		SentinelAddrs:    sentinelAddrs,
		Password:         password,
		PoolSize:         c.cfg.MaxConnections,
		MinIdleConns:     c.cfg.MinIdleConns,
		ConnMaxIdleTime:  c.cfg.ConnMaxIdleTime,
		ConnMaxLifetime:  c.cfg.ConnMaxLifetime,
	}

	if c.cfg.TLSEnabled {
		opts.TLSConfig = &tls.Config{
			MinVersion: tls.VersionTLS12,
		}
	}

	return redis.NewFailoverClient(opts), nil
}

func (c *Client) createClusterClient() (redis.UniversalClient, error) {
	opts := &redis.ClusterOptions{
		Addrs:           c.cfg.ClusterNodes,
		PoolSize:        c.cfg.MaxConnections,
		MinIdleConns:    c.cfg.MinIdleConns,
		ConnMaxIdleTime: c.cfg.ConnMaxIdleTime,
		ConnMaxLifetime: c.cfg.ConnMaxLifetime,
	}

	// Parse password from first node URL if present
	if len(c.cfg.ClusterNodes) > 0 {
		if parsed, err := url.Parse("redis://" + c.cfg.ClusterNodes[0]); err == nil {
			if parsed.User != nil {
				opts.Password, _ = parsed.User.Password()
			}
		}
	}

	if c.cfg.TLSEnabled {
		opts.TLSConfig = &tls.Config{
			MinVersion: tls.VersionTLS12,
		}
	}

	return redis.NewClusterClient(opts), nil
}

func (c *Client) parseURL(redisURL string) (*redis.Options, error) {
	if redisURL == "" {
		return &redis.Options{
			Addr: "localhost:6379",
		}, nil
	}

	// Handle redis:// and rediss:// URLs
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		// Try parsing as host:port
		parts := strings.Split(redisURL, ":")
		if len(parts) == 2 {
			return &redis.Options{
				Addr: redisURL,
			}, nil
		}
		return nil, fmt.Errorf("invalid redis URL: %w", err)
	}

	return opts, nil
}

// Underlying returns the underlying Redis client.
func (c *Client) Underlying() redis.UniversalClient {
	return c.client
}

// Mode returns the connection mode.
func (c *Client) Mode() Mode {
	return c.mode
}

// IsConnected returns whether the client is connected.
func (c *Client) IsConnected() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.isConnected
}

// Ping tests the connection.
func (c *Client) Ping(ctx context.Context) error {
	return c.client.Ping(ctx).Err()
}

// Close closes the Redis connection.
func (c *Client) Close() error {
	c.mu.Lock()
	c.isConnected = false
	c.mu.Unlock()
	return c.client.Close()
}

// HealthCheck performs a health check.
func (c *Client) HealthCheck(ctx context.Context) error {
	start := time.Now()
	err := c.Ping(ctx)
	latency := time.Since(start)

	log := logger.WithFields(c.log)
	if err != nil {
		c.mu.Lock()
		c.isConnected = false
		c.mu.Unlock()
		log.Error().Err(err).Dur("latency", latency).Msg("Redis health check failed")
		return err
	}

	c.mu.Lock()
	c.isConnected = true
	c.mu.Unlock()
	log.Debug().Dur("latency", latency).Msg("Redis health check passed")
	return nil
}

// StartHealthCheck starts a background health check goroutine.
func (c *Client) StartHealthCheck(ctx context.Context, interval time.Duration) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				checkCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
				c.HealthCheck(checkCtx)
				cancel()
			}
		}
	}()
}

// GetInfo returns Redis server info.
func (c *Client) GetInfo(ctx context.Context, section string) (string, error) {
	if section == "" {
		section = "all"
	}
	return c.client.Info(ctx, section).Result()
}

// GetDBSize returns the number of keys in the database.
func (c *Client) GetDBSize(ctx context.Context) (int64, error) {
	return c.client.DBSize(ctx).Result()
}

// GetMemoryUsage returns memory usage for a key.
func (c *Client) GetMemoryUsage(ctx context.Context, key string) (int64, error) {
	return c.client.MemoryUsage(ctx, key).Result()
}

// FlushDB removes all keys from the current database.
func (c *Client) FlushDB(ctx context.Context) error {
	return c.client.FlushDB(ctx).Err()
}

// FlushAll removes all keys from all databases.
func (c *Client) FlushAll(ctx context.Context) error {
	return c.client.FlushAll(ctx).Err()
}

// Basic operations wrappers

// Set stores a value.
func (c *Client) Set(ctx context.Context, key string, value any, ttl time.Duration) error {
	return c.client.Set(ctx, key, value, ttl).Err()
}

// Get retrieves a value.
func (c *Client) Get(ctx context.Context, key string) (string, error) {
	return c.client.Get(ctx, key).Result()
}

// Del deletes keys.
func (c *Client) Del(ctx context.Context, keys ...string) error {
	return c.client.Del(ctx, keys...).Err()
}

// Exists checks if keys exist.
func (c *Client) Exists(ctx context.Context, keys ...string) (int64, error) {
	return c.client.Exists(ctx, keys...).Result()
}

// Expire sets a TTL on a key.
func (c *Client) Expire(ctx context.Context, key string, ttl time.Duration) error {
	return c.client.Expire(ctx, key, ttl).Err()
}

// TTL returns the remaining TTL.
func (c *Client) TTL(ctx context.Context, key string) (time.Duration, error) {
	return c.client.TTL(ctx, key).Result()
}

// Keys returns keys matching a pattern.
func (c *Client) Keys(ctx context.Context, pattern string) ([]string, error) {
	return c.client.Keys(ctx, pattern).Result()
}

// Incr increments a value.
func (c *Client) Incr(ctx context.Context, key string) (int64, error) {
	return c.client.Incr(ctx, key).Result()
}

// IncrBy increments a value by amount.
func (c *Client) IncrBy(ctx context.Context, key string, value int64) (int64, error) {
	return c.client.IncrBy(ctx, key, value).Result()
}

// Decr decrements a value.
func (c *Client) Decr(ctx context.Context, key string) (int64, error) {
	return c.client.Decr(ctx, key).Result()
}

// SetNX sets a value only if it doesn't exist.
func (c *Client) SetNX(ctx context.Context, key string, value any, ttl time.Duration) (bool, error) {
	return c.client.SetNX(ctx, key, value, ttl).Result()
}

// Hash operations

// HSet sets hash fields.
func (c *Client) HSet(ctx context.Context, key string, values ...any) error {
	return c.client.HSet(ctx, key, values...).Err()
}

// HGet gets a hash field.
func (c *Client) HGet(ctx context.Context, key, field string) (string, error) {
	return c.client.HGet(ctx, key, field).Result()
}

// HGetAll gets all hash fields.
func (c *Client) HGetAll(ctx context.Context, key string) (map[string]string, error) {
	return c.client.HGetAll(ctx, key).Result()
}

// HDel deletes hash fields.
func (c *Client) HDel(ctx context.Context, key string, fields ...string) error {
	return c.client.HDel(ctx, key, fields...).Err()
}

// HExists checks if a hash field exists.
func (c *Client) HExists(ctx context.Context, key, field string) (bool, error) {
	return c.client.HExists(ctx, key, field).Result()
}

// HIncrBy increments a hash field.
func (c *Client) HIncrBy(ctx context.Context, key, field string, incr int64) (int64, error) {
	return c.client.HIncrBy(ctx, key, field, incr).Result()
}

// List operations

// LPush prepends values to a list.
func (c *Client) LPush(ctx context.Context, key string, values ...any) error {
	return c.client.LPush(ctx, key, values...).Err()
}

// RPush appends values to a list.
func (c *Client) RPush(ctx context.Context, key string, values ...any) error {
	return c.client.RPush(ctx, key, values...).Err()
}

// LPop removes and returns the first element.
func (c *Client) LPop(ctx context.Context, key string) (string, error) {
	return c.client.LPop(ctx, key).Result()
}

// RPop removes and returns the last element.
func (c *Client) RPop(ctx context.Context, key string) (string, error) {
	return c.client.RPop(ctx, key).Result()
}

// LLen returns the length of a list.
func (c *Client) LLen(ctx context.Context, key string) (int64, error) {
	return c.client.LLen(ctx, key).Result()
}

// LRange returns a range of elements.
func (c *Client) LRange(ctx context.Context, key string, start, stop int64) ([]string, error) {
	return c.client.LRange(ctx, key, start, stop).Result()
}

// Set operations

// SAdd adds members to a set.
func (c *Client) SAdd(ctx context.Context, key string, members ...any) error {
	return c.client.SAdd(ctx, key, members...).Err()
}

// SRem removes members from a set.
func (c *Client) SRem(ctx context.Context, key string, members ...any) error {
	return c.client.SRem(ctx, key, members...).Err()
}

// SMembers returns all members of a set.
func (c *Client) SMembers(ctx context.Context, key string) ([]string, error) {
	return c.client.SMembers(ctx, key).Result()
}

// SIsMember checks if a member exists.
func (c *Client) SIsMember(ctx context.Context, key string, member any) (bool, error) {
	return c.client.SIsMember(ctx, key, member).Result()
}

// SCard returns the cardinality of a set.
func (c *Client) SCard(ctx context.Context, key string) (int64, error) {
	return c.client.SCard(ctx, key).Result()
}

// Sorted set operations

// ZAdd adds members to a sorted set.
func (c *Client) ZAdd(ctx context.Context, key string, members ...redis.Z) error {
	return c.client.ZAdd(ctx, key, members...).Err()
}

// ZRem removes members from a sorted set.
func (c *Client) ZRem(ctx context.Context, key string, members ...any) error {
	return c.client.ZRem(ctx, key, members...).Err()
}

// ZRange returns members by index.
func (c *Client) ZRange(ctx context.Context, key string, start, stop int64) ([]string, error) {
	return c.client.ZRange(ctx, key, start, stop).Result()
}

// ZRangeWithScores returns members with scores.
func (c *Client) ZRangeWithScores(ctx context.Context, key string, start, stop int64) ([]redis.Z, error) {
	return c.client.ZRangeWithScores(ctx, key, start, stop).Result()
}

// ZRangeByScore returns members by score range.
func (c *Client) ZRangeByScore(ctx context.Context, key string, opt *redis.ZRangeBy) ([]string, error) {
	return c.client.ZRangeByScore(ctx, key, opt).Result()
}

// ZScore returns the score of a member.
func (c *Client) ZScore(ctx context.Context, key string, member string) (float64, error) {
	return c.client.ZScore(ctx, key, member).Result()
}

// ZCard returns the cardinality.
func (c *Client) ZCard(ctx context.Context, key string) (int64, error) {
	return c.client.ZCard(ctx, key).Result()
}

// Scan helpers

// Scan iterates over keys.
func (c *Client) Scan(ctx context.Context, cursor uint64, pattern string, count int64) ([]string, uint64, error) {
	return c.client.Scan(ctx, cursor, pattern, count).Result()
}

// ScanAll returns all keys matching a pattern.
func (c *Client) ScanAll(ctx context.Context, pattern string) ([]string, error) {
	var keys []string
	var cursor uint64 = 0

	for {
		var batch []string
		var err error
		batch, cursor, err = c.Scan(ctx, cursor, pattern, 100)
		if err != nil {
			return nil, err
		}
		keys = append(keys, batch...)
		if cursor == 0 {
			break
		}
	}

	return keys, nil
}

// Pipeline creates a new pipeline.
func (c *Client) Pipeline() redis.Pipeliner {
	return c.client.Pipeline()
}

// TxPipeline creates a new transactional pipeline.
func (c *Client) TxPipeline() redis.Pipeliner {
	return c.client.TxPipeline()
}

// Watch executes a transaction with WATCH.
func (c *Client) Watch(ctx context.Context, fn func(*redis.Tx) error, keys ...string) error {
	return c.client.Watch(ctx, fn, keys...)
}

// Eval executes a Lua script.
func (c *Client) Eval(ctx context.Context, script string, keys []string, args ...any) *redis.Cmd {
	return c.client.Eval(ctx, script, keys, args...)
}

// EvalSha executes a cached Lua script.
func (c *Client) EvalSha(ctx context.Context, sha string, keys []string, args ...any) *redis.Cmd {
	return c.client.EvalSha(ctx, sha, keys, args...)
}

// ScriptLoad loads a script into the cache.
func (c *Client) ScriptLoad(ctx context.Context, script string) (string, error) {
	return c.client.ScriptLoad(ctx, script).Result()
}

// Stats returns pool stats.
func (c *Client) Stats() *redis.PoolStats {
	return c.client.PoolStats()
}

// ParseIntFromString parses an int from a string.
func ParseIntFromString(s string) (int64, error) {
	return strconv.ParseInt(s, 10, 64)
}

// ParseFloatFromString parses a float from a string.
func ParseFloatFromString(s string) (float64, error) {
	return strconv.ParseFloat(s, 64)
}
