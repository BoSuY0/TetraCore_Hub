// Package redis provides Redis client infrastructure for TetraCore Hub.
package redis

import (
	"context"
	"encoding/json"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/pkg/logger"
)

// PubSub wraps Redis pub/sub functionality with auto-reconnect.
type PubSub struct {
	client       *Client
	pubsub       *redis.PubSub
	channels     map[string]bool
	patterns     map[string]bool
	handlers     map[string][]MessageHandler
	log          logger.LogFields
	mu           sync.RWMutex
	isRunning    bool
	reconnectCh  chan struct{}
	stopCh       chan struct{}
	msgCh        chan *redis.Message
	bufferSize   int
}

// MessageHandler is a function that handles pub/sub messages.
type MessageHandler func(channel string, payload string)

// PubSubConfig holds pub/sub configuration.
type PubSubConfig struct {
	BufferSize     int
	ReconnectDelay time.Duration
}

// DefaultPubSubConfig returns default pub/sub configuration.
func DefaultPubSubConfig() PubSubConfig {
	return PubSubConfig{
		BufferSize:     1000,
		ReconnectDelay: 5 * time.Second,
	}
}

// NewPubSub creates a new pub/sub manager.
func NewPubSub(client *Client, cfg PubSubConfig) *PubSub {
	return &PubSub{
		client:      client,
		channels:    make(map[string]bool),
		patterns:    make(map[string]bool),
		handlers:    make(map[string][]MessageHandler),
		log:         logger.LogFields{"component": "redis-pubsub"},
		reconnectCh: make(chan struct{}, 1),
		stopCh:      make(chan struct{}),
		msgCh:       make(chan *redis.Message, cfg.BufferSize),
		bufferSize:  cfg.BufferSize,
	}
}

// Start starts the pub/sub message processing.
func (p *PubSub) Start(ctx context.Context) error {
	p.mu.Lock()
	if p.isRunning {
		p.mu.Unlock()
		return nil
	}
	p.isRunning = true
	p.mu.Unlock()

	// Start message processing goroutine
	go p.processMessages(ctx)

	// Start subscription management goroutine
	go p.manageSubscriptions(ctx)

	log := logger.WithFields(p.log)
	log.Info().Msg("PubSub manager started")
	return nil
}

// Stop stops the pub/sub manager.
func (p *PubSub) Stop() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.isRunning {
		return nil
	}

	p.isRunning = false
	close(p.stopCh)

	if p.pubsub != nil {
		return p.pubsub.Close()
	}

	return nil
}

// Subscribe subscribes to channels.
func (p *PubSub) Subscribe(ctx context.Context, channels ...string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	for _, ch := range channels {
		p.channels[ch] = true
	}

	if p.pubsub != nil {
		return p.pubsub.Subscribe(ctx, channels...)
	}

	// Create new pubsub if not exists
	p.pubsub = p.client.Underlying().Subscribe(ctx, channels...)
	return nil
}

// PSubscribe subscribes to channel patterns.
func (p *PubSub) PSubscribe(ctx context.Context, patterns ...string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	for _, pat := range patterns {
		p.patterns[pat] = true
	}

	if p.pubsub != nil {
		return p.pubsub.PSubscribe(ctx, patterns...)
	}

	// Create new pubsub if not exists
	p.pubsub = p.client.Underlying().PSubscribe(ctx, patterns...)
	return nil
}

// Unsubscribe unsubscribes from channels.
func (p *PubSub) Unsubscribe(ctx context.Context, channels ...string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	for _, ch := range channels {
		delete(p.channels, ch)
	}

	if p.pubsub != nil {
		return p.pubsub.Unsubscribe(ctx, channels...)
	}
	return nil
}

// PUnsubscribe unsubscribes from patterns.
func (p *PubSub) PUnsubscribe(ctx context.Context, patterns ...string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	for _, pat := range patterns {
		delete(p.patterns, pat)
	}

	if p.pubsub != nil {
		return p.pubsub.PUnsubscribe(ctx, patterns...)
	}
	return nil
}

// Publish publishes a message to a channel.
func (p *PubSub) Publish(ctx context.Context, channel string, message any) error {
	var payload string
	switch v := message.(type) {
	case string:
		payload = v
	case []byte:
		payload = string(v)
	default:
		data, err := json.Marshal(message)
		if err != nil {
			return err
		}
		payload = string(data)
	}

	return p.client.Underlying().Publish(ctx, channel, payload).Err()
}

// AddHandler adds a message handler for a channel.
func (p *PubSub) AddHandler(channel string, handler MessageHandler) {
	p.mu.Lock()
	defer p.mu.Unlock()

	p.handlers[channel] = append(p.handlers[channel], handler)
}

// RemoveHandlers removes all handlers for a channel.
func (p *PubSub) RemoveHandlers(channel string) {
	p.mu.Lock()
	defer p.mu.Unlock()

	delete(p.handlers, channel)
}

// Channel returns a channel for receiving messages.
func (p *PubSub) Channel() <-chan *redis.Message {
	return p.msgCh
}

func (p *PubSub) processMessages(ctx context.Context) {
	log := logger.WithFields(p.log)

	for {
		select {
		case <-ctx.Done():
			return
		case <-p.stopCh:
			return
		case msg := <-p.msgCh:
			p.handleMessage(msg)
		}
	}

	log.Debug().Msg("Message processor stopped")
}

func (p *PubSub) handleMessage(msg *redis.Message) {
	p.mu.RLock()
	handlers := p.handlers[msg.Channel]
	wildcardHandlers := p.handlers["*"]
	p.mu.RUnlock()

	// Execute channel-specific handlers
	for _, handler := range handlers {
		handler(msg.Channel, msg.Payload)
	}

	// Execute wildcard handlers
	for _, handler := range wildcardHandlers {
		handler(msg.Channel, msg.Payload)
	}
}

func (p *PubSub) manageSubscriptions(ctx context.Context) {
	log := logger.WithFields(p.log)

	for {
		select {
		case <-ctx.Done():
			return
		case <-p.stopCh:
			return
		case <-p.reconnectCh:
			p.reconnect(ctx)
		default:
			p.receiveMessages(ctx)
		}
	}

	log.Debug().Msg("Subscription manager stopped")
}

func (p *PubSub) receiveMessages(ctx context.Context) {
	p.mu.RLock()
	pubsub := p.pubsub
	p.mu.RUnlock()

	if pubsub == nil {
		time.Sleep(100 * time.Millisecond)
		return
	}

	// Receive with timeout
	receiveCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	msg, err := pubsub.ReceiveMessage(receiveCtx)
	if err != nil {
		if ctx.Err() != nil {
			return
		}

		log := logger.WithFields(p.log)
		log.Warn().Err(err).Msg("Error receiving message, triggering reconnect")

		select {
		case p.reconnectCh <- struct{}{}:
		default:
		}
		return
	}

	// Send to channel buffer
	select {
	case p.msgCh <- msg:
	default:
		log := logger.WithFields(p.log)
		log.Warn().Msg("Message buffer full, dropping message")
	}
}

func (p *PubSub) reconnect(ctx context.Context) {
	log := logger.WithFields(p.log)
	log.Info().Msg("Reconnecting to PubSub...")

	p.mu.Lock()
	defer p.mu.Unlock()

	// Close existing connection
	if p.pubsub != nil {
		p.pubsub.Close()
		p.pubsub = nil
	}

	// Wait before reconnect
	time.Sleep(5 * time.Second)

	// Collect channels and patterns
	var channels []string
	var patterns []string

	for ch := range p.channels {
		channels = append(channels, ch)
	}
	for pat := range p.patterns {
		patterns = append(patterns, pat)
	}

	// Re-subscribe
	if len(channels) > 0 {
		p.pubsub = p.client.Underlying().Subscribe(ctx, channels...)
	}
	if len(patterns) > 0 {
		if p.pubsub != nil {
			p.pubsub.PSubscribe(ctx, patterns...)
		} else {
			p.pubsub = p.client.Underlying().PSubscribe(ctx, patterns...)
		}
	}

	log.Info().Int("channels", len(channels)).Int("patterns", len(patterns)).Msg("PubSub reconnected")
}

// GetSubscribedChannels returns the list of subscribed channels.
func (p *PubSub) GetSubscribedChannels() []string {
	p.mu.RLock()
	defer p.mu.RUnlock()

	channels := make([]string, 0, len(p.channels))
	for ch := range p.channels {
		channels = append(channels, ch)
	}
	return channels
}

// GetSubscribedPatterns returns the list of subscribed patterns.
func (p *PubSub) GetSubscribedPatterns() []string {
	p.mu.RLock()
	defer p.mu.RUnlock()

	patterns := make([]string, 0, len(p.patterns))
	for pat := range p.patterns {
		patterns = append(patterns, pat)
	}
	return patterns
}

// IsRunning returns whether the pub/sub manager is running.
func (p *PubSub) IsRunning() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.isRunning
}

// ========================================
// PubSubManager - High-level pub/sub manager for hub use case
// ========================================

// Message represents a pub/sub message.
type Message struct {
	Channel string
	Payload string
}

// MessageHandlerFunc handles pub/sub messages.
type MessageHandlerFunc func(msg Message)

// PubSubManager provides a high-level pub/sub interface for the hub.
type PubSubManager struct {
	client   *Client
	handlers map[string][]MessageHandlerFunc
	pubsubs  map[string]*redis.PubSub
	log      logger.LogFields
	mu       sync.RWMutex
	ctx      context.Context
	cancel   context.CancelFunc
}

// NewPubSubManager creates a new PubSubManager.
func NewPubSubManager(client *Client, cfg PubSubConfig) *PubSubManager {
	ctx, cancel := context.WithCancel(context.Background())
	return &PubSubManager{
		client:   client,
		handlers: make(map[string][]MessageHandlerFunc),
		pubsubs:  make(map[string]*redis.PubSub),
		log:      logger.LogFields{"component": "pubsub-manager"},
		ctx:      ctx,
		cancel:   cancel,
	}
}

// Subscribe subscribes to a channel with a handler.
func (m *PubSubManager) Subscribe(ctx context.Context, channel string, handler MessageHandlerFunc) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.handlers[channel] = append(m.handlers[channel], handler)

	// Create subscription if not exists
	if _, exists := m.pubsubs[channel]; !exists {
		pubsub := m.client.Underlying().Subscribe(ctx, channel)
		m.pubsubs[channel] = pubsub

		// Start message receiver
		go m.receiveMessages(channel, pubsub)
	}

	log := logger.WithFields(m.log)
	log.Debug().Str("channel", channel).Msg("Subscribed to channel")
	return nil
}

// Unsubscribe unsubscribes from a channel.
func (m *PubSubManager) Unsubscribe(ctx context.Context, channel string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if pubsub, exists := m.pubsubs[channel]; exists {
		pubsub.Close()
		delete(m.pubsubs, channel)
	}
	delete(m.handlers, channel)

	return nil
}

// Publish publishes a message to a channel.
func (m *PubSubManager) Publish(ctx context.Context, channel, payload string) error {
	return m.client.Underlying().Publish(ctx, channel, payload).Err()
}

// Close closes all subscriptions.
func (m *PubSubManager) Close() error {
	m.cancel()

	m.mu.Lock()
	defer m.mu.Unlock()

	for _, pubsub := range m.pubsubs {
		pubsub.Close()
	}
	m.pubsubs = make(map[string]*redis.PubSub)
	m.handlers = make(map[string][]MessageHandlerFunc)

	return nil
}

func (m *PubSubManager) receiveMessages(channel string, pubsub *redis.PubSub) {
	log := logger.WithFields(m.log)

	for {
		select {
		case <-m.ctx.Done():
			return
		default:
			msg, err := pubsub.ReceiveMessage(m.ctx)
			if err != nil {
				if m.ctx.Err() != nil {
					return
				}
				log.Warn().Err(err).Str("channel", channel).Msg("Error receiving message")
				time.Sleep(time.Second)
				continue
			}

			// Dispatch to handlers
			m.mu.RLock()
			handlers := m.handlers[channel]
			m.mu.RUnlock()

			message := Message{
				Channel: msg.Channel,
				Payload: msg.Payload,
			}

			for _, handler := range handlers {
				go handler(message)
			}
		}
	}
}
