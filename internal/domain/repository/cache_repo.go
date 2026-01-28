// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"time"
)

// CacheRepository defines the interface for caching operations.
type CacheRepository interface {
	// Set stores a value in the cache.
	Set(ctx context.Context, key string, value any, ttl time.Duration) error

	// Get retrieves a value from the cache.
	Get(ctx context.Context, key string) (any, error)

	// GetString retrieves a string value from the cache.
	GetString(ctx context.Context, key string) (string, error)

	// GetInt retrieves an int value from the cache.
	GetInt(ctx context.Context, key string) (int64, error)

	// GetFloat retrieves a float value from the cache.
	GetFloat(ctx context.Context, key string) (float64, error)

	// GetBytes retrieves a byte slice from the cache.
	GetBytes(ctx context.Context, key string) ([]byte, error)

	// Delete removes a value from the cache.
	Delete(ctx context.Context, key string) error

	// DeleteByPrefix removes all values with a key prefix.
	DeleteByPrefix(ctx context.Context, prefix string) error

	// Exists checks if a key exists in the cache.
	Exists(ctx context.Context, key string) (bool, error)

	// Expire sets a new TTL on a key.
	Expire(ctx context.Context, key string, ttl time.Duration) error

	// TTL returns the remaining TTL of a key.
	TTL(ctx context.Context, key string) (time.Duration, error)

	// Increment increments a numeric value.
	Increment(ctx context.Context, key string) (int64, error)

	// IncrementBy increments a numeric value by a specified amount.
	IncrementBy(ctx context.Context, key string, value int64) (int64, error)

	// Decrement decrements a numeric value.
	Decrement(ctx context.Context, key string) (int64, error)

	// DecrementBy decrements a numeric value by a specified amount.
	DecrementBy(ctx context.Context, key string, value int64) (int64, error)

	// SetNX sets a value only if it doesn't exist.
	SetNX(ctx context.Context, key string, value any, ttl time.Duration) (bool, error)

	// GetSet sets a value and returns the old value.
	GetSet(ctx context.Context, key string, value any) (any, error)

	// Keys returns all keys matching a pattern.
	Keys(ctx context.Context, pattern string) ([]string, error)

	// Clear removes all values from the cache.
	Clear(ctx context.Context) error
}

// HashRepository defines the interface for hash operations.
type HashRepository interface {
	// HSet sets a field in a hash.
	HSet(ctx context.Context, key, field string, value any) error

	// HGet retrieves a field from a hash.
	HGet(ctx context.Context, key, field string) (any, error)

	// HGetAll retrieves all fields from a hash.
	HGetAll(ctx context.Context, key string) (map[string]string, error)

	// HDel deletes a field from a hash.
	HDel(ctx context.Context, key string, fields ...string) error

	// HExists checks if a field exists in a hash.
	HExists(ctx context.Context, key, field string) (bool, error)

	// HLen returns the number of fields in a hash.
	HLen(ctx context.Context, key string) (int64, error)

	// HKeys returns all field names in a hash.
	HKeys(ctx context.Context, key string) ([]string, error)

	// HVals returns all values in a hash.
	HVals(ctx context.Context, key string) ([]string, error)

	// HIncrBy increments a field by a specified amount.
	HIncrBy(ctx context.Context, key, field string, incr int64) (int64, error)

	// HSetNX sets a field only if it doesn't exist.
	HSetNX(ctx context.Context, key, field string, value any) (bool, error)
}

// ListRepository defines the interface for list operations.
type ListRepository interface {
	// LPush prepends values to a list.
	LPush(ctx context.Context, key string, values ...any) error

	// RPush appends values to a list.
	RPush(ctx context.Context, key string, values ...any) error

	// LPop removes and returns the first element.
	LPop(ctx context.Context, key string) (string, error)

	// RPop removes and returns the last element.
	RPop(ctx context.Context, key string) (string, error)

	// LLen returns the length of a list.
	LLen(ctx context.Context, key string) (int64, error)

	// LRange returns a range of elements.
	LRange(ctx context.Context, key string, start, stop int64) ([]string, error)

	// LIndex returns the element at index.
	LIndex(ctx context.Context, key string, index int64) (string, error)

	// LSet sets the element at index.
	LSet(ctx context.Context, key string, index int64, value string) error

	// LRem removes elements equal to value.
	LRem(ctx context.Context, key string, count int64, value string) error

	// LTrim trims a list to the specified range.
	LTrim(ctx context.Context, key string, start, stop int64) error
}

// SetRepository defines the interface for set operations.
type SetRepository interface {
	// SAdd adds members to a set.
	SAdd(ctx context.Context, key string, members ...any) error

	// SRem removes members from a set.
	SRem(ctx context.Context, key string, members ...any) error

	// SMembers returns all members of a set.
	SMembers(ctx context.Context, key string) ([]string, error)

	// SIsMember checks if a value is a member of a set.
	SIsMember(ctx context.Context, key string, member any) (bool, error)

	// SCard returns the number of members in a set.
	SCard(ctx context.Context, key string) (int64, error)

	// SInter returns the intersection of sets.
	SInter(ctx context.Context, keys ...string) ([]string, error)

	// SUnion returns the union of sets.
	SUnion(ctx context.Context, keys ...string) ([]string, error)

	// SDiff returns the difference of sets.
	SDiff(ctx context.Context, keys ...string) ([]string, error)
}

// SortedSetRepository defines the interface for sorted set operations.
type SortedSetRepository interface {
	// ZAdd adds members to a sorted set.
	ZAdd(ctx context.Context, key string, members ...SortedSetMember) error

	// ZRem removes members from a sorted set.
	ZRem(ctx context.Context, key string, members ...any) error

	// ZScore returns the score of a member.
	ZScore(ctx context.Context, key string, member any) (float64, error)

	// ZRank returns the rank of a member (0-based).
	ZRank(ctx context.Context, key string, member any) (int64, error)

	// ZRange returns members in a range by index.
	ZRange(ctx context.Context, key string, start, stop int64) ([]string, error)

	// ZRangeWithScores returns members with scores in a range by index.
	ZRangeWithScores(ctx context.Context, key string, start, stop int64) ([]SortedSetMember, error)

	// ZRangeByScore returns members in a score range.
	ZRangeByScore(ctx context.Context, key string, min, max float64) ([]string, error)

	// ZCard returns the number of members.
	ZCard(ctx context.Context, key string) (int64, error)

	// ZCount returns the count of members in a score range.
	ZCount(ctx context.Context, key string, min, max float64) (int64, error)

	// ZIncrBy increments the score of a member.
	ZIncrBy(ctx context.Context, key string, increment float64, member any) (float64, error)
}

// SortedSetMember represents a member in a sorted set.
type SortedSetMember struct {
	Score  float64
	Member string
}

// PubSubRepository defines the interface for pub/sub operations.
type PubSubRepository interface {
	// Publish publishes a message to a channel.
	Publish(ctx context.Context, channel string, message any) error

	// Subscribe subscribes to channels.
	Subscribe(ctx context.Context, channels ...string) (<-chan PubSubMessage, error)

	// PSubscribe subscribes to channel patterns.
	PSubscribe(ctx context.Context, patterns ...string) (<-chan PubSubMessage, error)

	// Unsubscribe unsubscribes from channels.
	Unsubscribe(ctx context.Context, channels ...string) error

	// PUnsubscribe unsubscribes from channel patterns.
	PUnsubscribe(ctx context.Context, patterns ...string) error

	// Close closes the pub/sub connection.
	Close() error
}

// PubSubMessage represents a pub/sub message.
type PubSubMessage struct {
	Channel string
	Pattern string
	Payload string
}
