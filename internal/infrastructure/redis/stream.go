// Package redis provides Redis stream helpers.
package redis

import (
	"context"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/pkg/logger"
)

// StreamConfig holds Redis stream settings.
type StreamConfig struct {
	Stream   string
	Group    string
	Consumer string
	Block    time.Duration
	Batch    int64
	MaxLen   int64
}

// StreamMessage represents a stream entry.
type StreamMessage struct {
	ID     string
	Values map[string]any
}

// StreamManager manages Redis Streams for task ingestion.
type StreamManager struct {
	client redis.UniversalClient
	cfg    StreamConfig
	log    logger.LogFields
}

// NewStreamManager creates a StreamManager.
func NewStreamManager(client *Client, cfg StreamConfig) *StreamManager {
	return &StreamManager{
		client: client.Underlying(),
		cfg:    cfg,
		log:    logger.LogFields{"component": "redis-stream"},
	}
}

// Enabled returns true if stream configuration is present.
func (m *StreamManager) Enabled() bool {
	return m != nil && m.cfg.Stream != "" && m.cfg.Group != "" && m.cfg.Consumer != ""
}

// EnsureGroup creates the consumer group if it does not exist.
func (m *StreamManager) EnsureGroup(ctx context.Context) error {
	if !m.Enabled() {
		return nil
	}
	err := m.client.XGroupCreateMkStream(ctx, m.cfg.Stream, m.cfg.Group, "$").Err()
	if err == nil {
		return nil
	}
	if strings.Contains(err.Error(), "BUSYGROUP") {
		return nil
	}
	return err
}

// Add appends a message to the stream.
func (m *StreamManager) Add(ctx context.Context, values map[string]any) (string, error) {
	if !m.Enabled() {
		return "", nil
	}
	args := &redis.XAddArgs{
		Stream: m.cfg.Stream,
		Values: values,
	}
	if m.cfg.MaxLen > 0 {
		args.MaxLen = m.cfg.MaxLen
		args.Approx = true
	}
	return m.client.XAdd(ctx, args).Result()
}

// ReadGroup reads messages for the consumer group.
func (m *StreamManager) ReadGroup(ctx context.Context) ([]StreamMessage, error) {
	if !m.Enabled() {
		return nil, nil
	}
	batch := m.cfg.Batch
	if batch <= 0 {
		batch = 10
	}
	streams, err := m.client.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    m.cfg.Group,
		Consumer: m.cfg.Consumer,
		Streams:  []string{m.cfg.Stream, ">"},
		Count:    batch,
		Block:    m.cfg.Block,
	}).Result()
	if err == redis.Nil {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []StreamMessage
	for _, stream := range streams {
		for _, msg := range stream.Messages {
			out = append(out, StreamMessage{ID: msg.ID, Values: msg.Values})
		}
	}
	return out, nil
}

// Ack acknowledges processed messages.
func (m *StreamManager) Ack(ctx context.Context, ids ...string) error {
	if !m.Enabled() || len(ids) == 0 {
		return nil
	}
	return m.client.XAck(ctx, m.cfg.Stream, m.cfg.Group, ids...).Err()
}
