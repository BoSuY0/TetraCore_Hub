// Package redis provides Redis client infrastructure for TetraCore Hub.
package redis

import (
	"context"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/pkg/logger"
)

// PipelineOperation represents a queued pipeline operation.
type PipelineOperation struct {
	Command  string
	Args     []any
	Callback func(any, error)
}

// PipelineManager manages batched Redis operations.
type PipelineManager struct {
	client        *Client
	operations    []PipelineOperation
	mu            sync.Mutex
	batchSize     int
	flushInterval time.Duration
	isRunning     bool
	stopCh        chan struct{}
	flushCh       chan struct{}
	log           logger.LogFields
}

// PipelineConfig holds pipeline configuration.
type PipelineConfig struct {
	BatchSize     int
	FlushInterval time.Duration
}

// DefaultPipelineConfig returns default pipeline configuration.
func DefaultPipelineConfig() PipelineConfig {
	return PipelineConfig{
		BatchSize:     100,
		FlushInterval: 100 * time.Millisecond,
	}
}

// NewPipelineManager creates a new pipeline manager.
func NewPipelineManager(client *Client, cfg PipelineConfig) *PipelineManager {
	return &PipelineManager{
		client:        client,
		operations:    make([]PipelineOperation, 0, cfg.BatchSize),
		batchSize:     cfg.BatchSize,
		flushInterval: cfg.FlushInterval,
		stopCh:        make(chan struct{}),
		flushCh:       make(chan struct{}, 1),
		log:           logger.LogFields{"component": "redis-pipeline"},
	}
}

// Start starts the pipeline manager.
func (p *PipelineManager) Start(ctx context.Context) {
	p.mu.Lock()
	if p.isRunning {
		p.mu.Unlock()
		return
	}
	p.isRunning = true
	p.mu.Unlock()

	go p.run(ctx)

	log := logger.WithFields(p.log)
	log.Info().Int("batch_size", p.batchSize).Dur("flush_interval", p.flushInterval).Msg("Pipeline manager started")
}

// Stop stops the pipeline manager.
func (p *PipelineManager) Stop() {
	p.mu.Lock()
	if !p.isRunning {
		p.mu.Unlock()
		return
	}
	p.isRunning = false
	close(p.stopCh)
	p.mu.Unlock()

	// Flush remaining operations
	p.Flush(context.Background())

	log := logger.WithFields(p.log)
	log.Info().Msg("Pipeline manager stopped")
}

func (p *PipelineManager) run(ctx context.Context) {
	ticker := time.NewTicker(p.flushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-p.stopCh:
			return
		case <-ticker.C:
			p.Flush(ctx)
		case <-p.flushCh:
			p.Flush(ctx)
		}
	}
}

// Enqueue adds an operation to the pipeline.
func (p *PipelineManager) Enqueue(op PipelineOperation) {
	p.mu.Lock()
	p.operations = append(p.operations, op)
	needsFlush := len(p.operations) >= p.batchSize
	p.mu.Unlock()

	if needsFlush {
		select {
		case p.flushCh <- struct{}{}:
		default:
		}
	}
}

// Flush executes all queued operations.
func (p *PipelineManager) Flush(ctx context.Context) {
	p.mu.Lock()
	if len(p.operations) == 0 {
		p.mu.Unlock()
		return
	}

	// Get operations and clear queue
	ops := p.operations
	p.operations = make([]PipelineOperation, 0, p.batchSize)
	p.mu.Unlock()

	// Execute pipeline
	pipe := p.client.Pipeline()
	cmds := make([]*redis.Cmd, len(ops))

	for i, op := range ops {
		cmds[i] = pipe.Do(ctx, op.Args...)
	}

	_, err := pipe.Exec(ctx)

	log := logger.WithFields(p.log)
	if err != nil && err != redis.Nil {
		log.Error().Err(err).Int("operations", len(ops)).Msg("Pipeline execution failed")
	} else {
		log.Debug().Int("operations", len(ops)).Msg("Pipeline flushed")
	}

	// Execute callbacks
	for i, op := range ops {
		if op.Callback != nil {
			var result any
			var cmdErr error
			if cmds[i] != nil {
				result, cmdErr = cmds[i].Result()
			}
			op.Callback(result, cmdErr)
		}
	}
}

// Set adds a SET operation to the pipeline.
func (p *PipelineManager) Set(key string, value any, ttl time.Duration, callback func(error)) {
	args := []any{"SET", key, value}
	if ttl > 0 {
		args = append(args, "EX", int(ttl.Seconds()))
	}

	p.Enqueue(PipelineOperation{
		Command: "SET",
		Args:    args,
		Callback: func(_ any, err error) {
			if callback != nil {
				callback(err)
			}
		},
	})
}

// Get adds a GET operation to the pipeline.
func (p *PipelineManager) Get(key string, callback func(string, error)) {
	p.Enqueue(PipelineOperation{
		Command: "GET",
		Args:    []any{"GET", key},
		Callback: func(result any, err error) {
			if callback != nil {
				if s, ok := result.(string); ok {
					callback(s, err)
				} else {
					callback("", err)
				}
			}
		},
	})
}

// Del adds a DEL operation to the pipeline.
func (p *PipelineManager) Del(keys []string, callback func(int64, error)) {
	args := make([]any, len(keys)+1)
	args[0] = "DEL"
	for i, key := range keys {
		args[i+1] = key
	}

	p.Enqueue(PipelineOperation{
		Command: "DEL",
		Args:    args,
		Callback: func(result any, err error) {
			if callback != nil {
				if n, ok := result.(int64); ok {
					callback(n, err)
				} else {
					callback(0, err)
				}
			}
		},
	})
}

// HSet adds an HSET operation to the pipeline.
func (p *PipelineManager) HSet(key, field string, value any, callback func(error)) {
	p.Enqueue(PipelineOperation{
		Command: "HSET",
		Args:    []any{"HSET", key, field, value},
		Callback: func(_ any, err error) {
			if callback != nil {
				callback(err)
			}
		},
	})
}

// HGet adds an HGET operation to the pipeline.
func (p *PipelineManager) HGet(key, field string, callback func(string, error)) {
	p.Enqueue(PipelineOperation{
		Command: "HGET",
		Args:    []any{"HGET", key, field},
		Callback: func(result any, err error) {
			if callback != nil {
				if s, ok := result.(string); ok {
					callback(s, err)
				} else {
					callback("", err)
				}
			}
		},
	})
}

// Incr adds an INCR operation to the pipeline.
func (p *PipelineManager) Incr(key string, callback func(int64, error)) {
	p.Enqueue(PipelineOperation{
		Command: "INCR",
		Args:    []any{"INCR", key},
		Callback: func(result any, err error) {
			if callback != nil {
				if n, ok := result.(int64); ok {
					callback(n, err)
				} else {
					callback(0, err)
				}
			}
		},
	})
}

// Expire adds an EXPIRE operation to the pipeline.
func (p *PipelineManager) Expire(key string, ttl time.Duration, callback func(bool, error)) {
	p.Enqueue(PipelineOperation{
		Command: "EXPIRE",
		Args:    []any{"EXPIRE", key, int(ttl.Seconds())},
		Callback: func(result any, err error) {
			if callback != nil {
				if n, ok := result.(int64); ok {
					callback(n == 1, err)
				} else {
					callback(false, err)
				}
			}
		},
	})
}

// LPush adds an LPUSH operation to the pipeline.
func (p *PipelineManager) LPush(key string, values []any, callback func(int64, error)) {
	args := make([]any, len(values)+2)
	args[0] = "LPUSH"
	args[1] = key
	for i, v := range values {
		args[i+2] = v
	}

	p.Enqueue(PipelineOperation{
		Command: "LPUSH",
		Args:    args,
		Callback: func(result any, err error) {
			if callback != nil {
				if n, ok := result.(int64); ok {
					callback(n, err)
				} else {
					callback(0, err)
				}
			}
		},
	})
}

// RPop adds an RPOP operation to the pipeline.
func (p *PipelineManager) RPop(key string, callback func(string, error)) {
	p.Enqueue(PipelineOperation{
		Command: "RPOP",
		Args:    []any{"RPOP", key},
		Callback: func(result any, err error) {
			if callback != nil {
				if s, ok := result.(string); ok {
					callback(s, err)
				} else {
					callback("", err)
				}
			}
		},
	})
}

// SAdd adds an SADD operation to the pipeline.
func (p *PipelineManager) SAdd(key string, members []any, callback func(int64, error)) {
	args := make([]any, len(members)+2)
	args[0] = "SADD"
	args[1] = key
	for i, m := range members {
		args[i+2] = m
	}

	p.Enqueue(PipelineOperation{
		Command: "SADD",
		Args:    args,
		Callback: func(result any, err error) {
			if callback != nil {
				if n, ok := result.(int64); ok {
					callback(n, err)
				} else {
					callback(0, err)
				}
			}
		},
	})
}

// ZAdd adds a ZADD operation to the pipeline.
func (p *PipelineManager) ZAdd(key string, score float64, member string, callback func(int64, error)) {
	p.Enqueue(PipelineOperation{
		Command: "ZADD",
		Args:    []any{"ZADD", key, score, member},
		Callback: func(result any, err error) {
			if callback != nil {
				if n, ok := result.(int64); ok {
					callback(n, err)
				} else {
					callback(0, err)
				}
			}
		},
	})
}

// PendingOperations returns the number of pending operations.
func (p *PipelineManager) PendingOperations() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return len(p.operations)
}

// IsRunning returns whether the pipeline manager is running.
func (p *PipelineManager) IsRunning() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.isRunning
}
