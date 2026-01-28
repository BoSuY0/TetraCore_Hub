// Package eventbus provides an in-memory event bus for TetraCore Hub.
package eventbus

import (
	"context"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/tetra/core-hub/pkg/logger"
)

// EventBus defines the interface for event publishing and subscription.
type EventBus interface {
	// Publish publishes an event to all subscribers.
	Publish(ctx context.Context, event Event) error

	// PublishAsync publishes an event asynchronously.
	PublishAsync(ctx context.Context, event Event)

	// Subscribe subscribes to events of a specific type.
	Subscribe(eventType EventType, handler EventHandler) string

	// SubscribeWithFilter subscribes with a filter function.
	SubscribeWithFilter(eventType EventType, handler EventHandler, filter EventFilter) string

	// SubscribeAll subscribes to all events.
	SubscribeAll(handler EventHandler) string

	// Unsubscribe removes a subscription.
	Unsubscribe(subscriptionID string)

	// Close closes the event bus.
	Close()
}

// InMemoryEventBus is an in-memory implementation of EventBus.
type InMemoryEventBus struct {
	subscriptions map[string]*Subscription
	byType        map[EventType][]string // eventType -> subscription IDs
	allSubs       []string               // subscriptions for all events
	mu            sync.RWMutex
	log           logger.LogFields
	asyncCh       chan Event
	closeCh       chan struct{}
	wg            sync.WaitGroup
	bufferSize    int
	workerCount   int
}

// Config holds event bus configuration.
type Config struct {
	BufferSize  int // Size of async event buffer
	WorkerCount int // Number of async workers
}

// DefaultConfig returns default configuration.
func DefaultConfig() Config {
	return Config{
		BufferSize:  1000,
		WorkerCount: 4,
	}
}

// New creates a new InMemoryEventBus.
func New(cfg Config) *InMemoryEventBus {
	if cfg.BufferSize == 0 {
		cfg.BufferSize = 1000
	}
	if cfg.WorkerCount == 0 {
		cfg.WorkerCount = 4
	}

	eb := &InMemoryEventBus{
		subscriptions: make(map[string]*Subscription),
		byType:        make(map[EventType][]string),
		allSubs:       make([]string, 0),
		log:           logger.LogFields{"component": "eventbus"},
		asyncCh:       make(chan Event, cfg.BufferSize),
		closeCh:       make(chan struct{}),
		bufferSize:    cfg.BufferSize,
		workerCount:   cfg.WorkerCount,
	}

	// Start async workers
	for i := 0; i < cfg.WorkerCount; i++ {
		eb.wg.Add(1)
		go eb.asyncWorker(i)
	}

	return eb
}

// asyncWorker processes async events.
func (eb *InMemoryEventBus) asyncWorker(id int) {
	defer eb.wg.Done()
	log := logger.WithFields(eb.log).With("worker_id", id)

	for {
		select {
		case <-eb.closeCh:
			return
		case event := <-eb.asyncCh:
			if err := eb.dispatch(event); err != nil {
				log.Error().Err(err).Str("event_type", string(event.Type)).Msg("Failed to dispatch event")
			}
		}
	}
}

// Publish publishes an event synchronously.
func (eb *InMemoryEventBus) Publish(ctx context.Context, event Event) error {
	// Ensure event has ID and timestamp
	if event.ID == "" {
		event.ID = uuid.New().String()
	}
	if event.Timestamp.IsZero() {
		event.Timestamp = time.Now().UTC()
	}

	return eb.dispatch(event)
}

// PublishAsync publishes an event asynchronously.
func (eb *InMemoryEventBus) PublishAsync(ctx context.Context, event Event) {
	// Ensure event has ID and timestamp
	if event.ID == "" {
		event.ID = uuid.New().String()
	}
	if event.Timestamp.IsZero() {
		event.Timestamp = time.Now().UTC()
	}

	select {
	case eb.asyncCh <- event:
		// Event queued
	default:
		// Buffer full, log warning
		log := logger.WithFields(eb.log)
		log.Warn().Str("event_type", string(event.Type)).Msg("Event buffer full, dropping event")
	}
}

// dispatch delivers an event to all matching subscribers.
func (eb *InMemoryEventBus) dispatch(event Event) error {
	eb.mu.RLock()
	defer eb.mu.RUnlock()

	// Get subscriptions for this event type
	subIDs := make([]string, 0)
	if ids, ok := eb.byType[event.Type]; ok {
		subIDs = append(subIDs, ids...)
	}
	// Add "all events" subscriptions
	subIDs = append(subIDs, eb.allSubs...)

	// Dispatch to each subscriber
	for _, subID := range subIDs {
		sub, ok := eb.subscriptions[subID]
		if !ok {
			continue
		}

		// Apply filter if present
		if sub.Filter != nil && !sub.Filter(event) {
			continue
		}

		// Call handler (recover from panics)
		func() {
			defer func() {
				if r := recover(); r != nil {
					log := logger.WithFields(eb.log)
					log.Error().Interface("panic", r).Str("subscription_id", subID).Msg("Handler panic recovered")
				}
			}()
			sub.Handler(event)
		}()
	}

	return nil
}

// Subscribe subscribes to events of a specific type.
func (eb *InMemoryEventBus) Subscribe(eventType EventType, handler EventHandler) string {
	return eb.SubscribeWithFilter(eventType, handler, nil)
}

// SubscribeWithFilter subscribes with a filter function.
func (eb *InMemoryEventBus) SubscribeWithFilter(eventType EventType, handler EventHandler, filter EventFilter) string {
	eb.mu.Lock()
	defer eb.mu.Unlock()

	subID := uuid.New().String()
	sub := &Subscription{
		ID:        subID,
		EventType: eventType,
		Handler:   handler,
		Filter:    filter,
	}

	eb.subscriptions[subID] = sub
	eb.byType[eventType] = append(eb.byType[eventType], subID)

	return subID
}

// SubscribeAll subscribes to all events.
func (eb *InMemoryEventBus) SubscribeAll(handler EventHandler) string {
	eb.mu.Lock()
	defer eb.mu.Unlock()

	subID := uuid.New().String()
	sub := &Subscription{
		ID:      subID,
		Handler: handler,
	}

	eb.subscriptions[subID] = sub
	eb.allSubs = append(eb.allSubs, subID)

	return subID
}

// Unsubscribe removes a subscription.
func (eb *InMemoryEventBus) Unsubscribe(subscriptionID string) {
	eb.mu.Lock()
	defer eb.mu.Unlock()

	sub, ok := eb.subscriptions[subscriptionID]
	if !ok {
		return
	}

	delete(eb.subscriptions, subscriptionID)

	// Remove from byType
	if sub.EventType != "" {
		ids := eb.byType[sub.EventType]
		for i, id := range ids {
			if id == subscriptionID {
				eb.byType[sub.EventType] = append(ids[:i], ids[i+1:]...)
				break
			}
		}
	}

	// Remove from allSubs
	for i, id := range eb.allSubs {
		if id == subscriptionID {
			eb.allSubs = append(eb.allSubs[:i], eb.allSubs[i+1:]...)
			break
		}
	}
}

// Close closes the event bus and waits for workers to finish.
func (eb *InMemoryEventBus) Close() {
	close(eb.closeCh)
	eb.wg.Wait()
}

// Stats returns event bus statistics.
func (eb *InMemoryEventBus) Stats() EventBusStats {
	eb.mu.RLock()
	defer eb.mu.RUnlock()

	typeStats := make(map[EventType]int)
	for eventType, ids := range eb.byType {
		typeStats[eventType] = len(ids)
	}

	return EventBusStats{
		TotalSubscriptions: len(eb.subscriptions),
		AllEventSubs:       len(eb.allSubs),
		ByType:             typeStats,
		BufferSize:         eb.bufferSize,
		BufferUsed:         len(eb.asyncCh),
		WorkerCount:        eb.workerCount,
	}
}

// EventBusStats holds event bus statistics.
type EventBusStats struct {
	TotalSubscriptions int                  `json:"total_subscriptions"`
	AllEventSubs       int                  `json:"all_event_subs"`
	ByType             map[EventType]int    `json:"by_type"`
	BufferSize         int                  `json:"buffer_size"`
	BufferUsed         int                  `json:"buffer_used"`
	WorkerCount        int                  `json:"worker_count"`
}

// NewEvent creates a new event with the given type and payload.
func NewEvent(eventType EventType, source string, payload map[string]any) Event {
	return Event{
		ID:        uuid.New().String(),
		Type:      eventType,
		Source:    source,
		Payload:   payload,
		Timestamp: time.Now().UTC(),
	}
}

// NewEventWithMetadata creates a new event with metadata.
func NewEventWithMetadata(eventType EventType, source string, payload map[string]any, metadata EventMetadata) Event {
	return Event{
		ID:        uuid.New().String(),
		Type:      eventType,
		Source:    source,
		Payload:   payload,
		Timestamp: time.Now().UTC(),
		Metadata:  metadata,
	}
}

// Ensure interface compliance
var _ EventBus = (*InMemoryEventBus)(nil)
