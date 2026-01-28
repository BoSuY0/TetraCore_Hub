// Package hub provides the main orchestration use case for TetraCore Hub.
package hub

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/internal/usecase/auth"
	"github.com/tetra/core-hub/internal/usecase/client"
	"github.com/tetra/core-hub/internal/usecase/task"
	"github.com/tetra/core-hub/pkg/errors"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds hub configuration.
type Config struct {
	TaskChannel        string
	ResultChannel      string
	BroadcastChannel   string
	HealthChannel      string
	TaskStream         string
	TaskStreamGroup    string
	TaskStreamConsumer string
	TaskStreamBlock    time.Duration
	TaskStreamBatch    int64
	CleanupInterval    time.Duration
	HeartbeatInterval  time.Duration
}

// ConnectionManager manages WebSocket connections.
type ConnectionManager interface {
	SendToClient(clientID string, message any) error
	Broadcast(message any) error
	BroadcastToType(clientType entity.ClientType, message any) error
	CloseConnection(clientID string, reason string) error
	GetConnectedCount() int
}

// UseCase orchestrates all hub operations.
type UseCase struct {
	authUC    *auth.UseCase
	clientUC  *client.UseCase
	taskUC    *task.UseCase
	pubsub    *redis.PubSubManager
	streamMgr *redis.StreamManager
	connMgr   ConnectionManager
	config    Config
	log       logger.LogFields

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup

	// Stats
	startTime      time.Time
	messageCount   int64
	messageCountMu sync.Mutex
}

// NewUseCase creates a new hub use case.
func NewUseCase(
	authUC *auth.UseCase,
	clientUC *client.UseCase,
	taskUC *task.UseCase,
	pubsub *redis.PubSubManager,
	streamMgr *redis.StreamManager,
	config Config,
) *UseCase {
	ctx, cancel := context.WithCancel(context.Background())

	return &UseCase{
		authUC:    authUC,
		clientUC:  clientUC,
		taskUC:    taskUC,
		pubsub:    pubsub,
		streamMgr: streamMgr,
		config:    config,
		log:       logger.LogFields{"component": "hub-usecase"},
		ctx:       ctx,
		cancel:    cancel,
	}
}

// SetConnectionManager sets the connection manager (called after WebSocket handler is ready).
func (uc *UseCase) SetConnectionManager(connMgr ConnectionManager) {
	uc.connMgr = connMgr
	if uc.taskUC != nil {
		uc.taskUC.SetSender(uc)
	}
}

// Start starts background workers.
func (uc *UseCase) Start() error {
	log := logger.WithFields(uc.log)
	log.Info().Msg("Starting hub orchestration")

	// Set start time for uptime tracking
	uc.startTime = time.Now()

	// Subscribe to Redis channels
	if err := uc.subscribeToChannels(); err != nil {
		log.Error().Err(err).Msg("Failed to subscribe to channels")
		return err
	}

	if uc.streamMgr != nil && uc.streamMgr.Enabled() {
		if err := uc.streamMgr.EnsureGroup(uc.ctx); err != nil {
			log.Error().Err(err).Msg("Failed to ensure stream group")
		}
		uc.wg.Add(1)
		go uc.streamWorker()
	}

	// Start cleanup worker
	uc.wg.Add(1)
	go uc.cleanupWorker()

	// Start task processor
	uc.wg.Add(1)
	go uc.taskProcessor()

	// Start heartbeat checker
	uc.wg.Add(1)
	go uc.heartbeatChecker()

	log.Info().Msg("Hub orchestration started")
	return nil
}

// Stop gracefully stops the hub.
func (uc *UseCase) Stop() error {
	log := logger.WithFields(uc.log)
	log.Info().Msg("Stopping hub orchestration")

	uc.cancel()
	uc.wg.Wait()

	log.Info().Msg("Hub orchestration stopped")
	return nil
}

// subscribeToChannels subscribes to Redis pub/sub channels.
func (uc *UseCase) subscribeToChannels() error {
	// Subscribe to task channel
	if uc.config.TaskChannel != "" {
		if err := uc.pubsub.Subscribe(uc.ctx, uc.config.TaskChannel, uc.handleTaskMessage); err != nil {
			return err
		}
	}

	// Subscribe to result channel
	if uc.config.ResultChannel != "" {
		if err := uc.pubsub.Subscribe(uc.ctx, uc.config.ResultChannel, uc.handleResultMessage); err != nil {
			return err
		}
	}

	// Subscribe to broadcast channel
	if uc.config.BroadcastChannel != "" {
		if err := uc.pubsub.Subscribe(uc.ctx, uc.config.BroadcastChannel, uc.handleBroadcastMessage); err != nil {
			return err
		}
	}

	return nil
}

// handleTaskMessage handles incoming task messages from Redis.
func (uc *UseCase) handleTaskMessage(msg redis.Message) {
	log := logger.WithFields(uc.log)

	var taskMsg entity.TaskMessage
	if err := json.Unmarshal([]byte(msg.Payload), &taskMsg); err != nil {
		log.Warn().Err(err).Msg("Failed to unmarshal task message")
		return
	}

	log.Debug().Str("task_id", taskMsg.TaskID).Msg("Received task from Redis")

	// Process task through usecase
	_, err := uc.taskUC.SubmitTask(uc.ctx, task.SubmitInput{
		TaskID:       taskMsg.TaskID,
		TaskType:     taskMsg.TaskType,
		ExecutorType: taskMsg.ExecutorType,
		Priority:     taskMsg.Priority,
		Payload:      taskMsg.Payload,
		Timeout:      taskMsg.Timeout,
	})

	if err != nil {
		log.Error().Err(err).Msg("Failed to process task from Redis")
	}
}

// handleResultMessage handles task result messages from Redis.
func (uc *UseCase) handleResultMessage(msg redis.Message) {
	log := logger.WithFields(uc.log)

	var resultMsg entity.TaskResultMessage
	if err := json.Unmarshal([]byte(msg.Payload), &resultMsg); err != nil {
		log.Warn().Err(err).Msg("Failed to unmarshal result message")
		return
	}

	log.Debug().Str("task_id", resultMsg.TaskID).Msg("Received result from Redis")

	// Complete or fail task based on status
	if resultMsg.Status == entity.TaskStatusCompleted {
		_ = uc.taskUC.CompleteTask(uc.ctx, resultMsg.TaskID, resultMsg.Result)
	} else if resultMsg.Status == entity.TaskStatusFailed && resultMsg.Error != nil {
		_ = uc.taskUC.FailTask(uc.ctx, resultMsg.TaskID, resultMsg.Error.Type, resultMsg.Error.Message, resultMsg.Error.Stacktrace)
	}
}

// handleBroadcastMessage handles broadcast messages from Redis.
func (uc *UseCase) handleBroadcastMessage(msg redis.Message) {
	log := logger.WithFields(uc.log)

	if uc.connMgr == nil {
		return
	}

	var broadcastMsg entity.BroadcastMessage
	if err := json.Unmarshal([]byte(msg.Payload), &broadcastMsg); err != nil {
		log.Warn().Err(err).Msg("Failed to unmarshal broadcast message")
		return
	}

	log.Debug().Str("type", broadcastMsg.DataType).Msg("Broadcasting message")

	if err := uc.connMgr.Broadcast(broadcastMsg); err != nil {
		log.Warn().Err(err).Msg("Failed to broadcast message")
	}
}

// cleanupWorker periodically cleans up stale data.
func (uc *UseCase) cleanupWorker() {
	defer uc.wg.Done()

	log := logger.WithFields(uc.log)
	ticker := time.NewTicker(uc.config.CleanupInterval)
	defer ticker.Stop()

	for {
		select {
		case <-uc.ctx.Done():
			return
		case <-ticker.C:
			// Cleanup expired sessions
			if deleted, err := uc.authUC.CleanupExpiredSessions(uc.ctx); err == nil && deleted > 0 {
				log.Debug().Int64("count", deleted).Msg("Cleaned up sessions")
			}

			// Cleanup old tasks
			if deleted, err := uc.taskUC.CleanupOldTasks(uc.ctx); err == nil && deleted > 0 {
				log.Debug().Int64("count", deleted).Msg("Cleaned up tasks")
			}

			// Cleanup stale connections
			if cleaned, err := uc.clientUC.CleanupStaleConnections(uc.ctx); err == nil && cleaned > 0 {
				log.Debug().Int("count", cleaned).Msg("Cleaned up connections")
			}
		}
	}
}

// taskProcessor periodically processes pending tasks.
func (uc *UseCase) taskProcessor() {
	defer uc.wg.Done()

	log := logger.WithFields(uc.log)
	ticker := time.NewTicker(time.Second * 5)
	defer ticker.Stop()

	for {
		select {
		case <-uc.ctx.Done():
			return
		case <-ticker.C:
			if assigned, err := uc.taskUC.ProcessPendingTasks(uc.ctx); err == nil && assigned > 0 {
				log.Debug().Int("assigned", assigned).Msg("Processed pending tasks")
			}
		}
	}
}

// streamWorker consumes tasks from Redis Streams.
func (uc *UseCase) streamWorker() {
	defer uc.wg.Done()

	log := logger.WithFields(uc.log).With("worker", "stream")
	for {
		select {
		case <-uc.ctx.Done():
			return
		default:
			messages, err := uc.streamMgr.ReadGroup(uc.ctx)
			if err != nil {
				log.Warn().Err(err).Msg("Stream read failed")
				time.Sleep(time.Second)
				continue
			}
			if len(messages) == 0 {
				continue
			}
			for _, msg := range messages {
				if err := uc.handleStreamMessage(msg); err != nil {
					log.Warn().Err(err).Str("stream_id", msg.ID).Msg("Stream message failed")
					continue
				}
				_ = uc.streamMgr.Ack(uc.ctx, msg.ID)
			}
		}
	}
}

func (uc *UseCase) handleStreamMessage(msg redis.StreamMessage) error {
	payloadRaw, ok := msg.Values["payload"]
	if !ok {
		return errors.ErrValidation.With("missing payload")
	}

	var payload string
	switch v := payloadRaw.(type) {
	case string:
		payload = v
	case []byte:
		payload = string(v)
	default:
		return errors.ErrValidation.With("invalid payload type")
	}

	var taskMsg entity.TaskMessage
	if err := json.Unmarshal([]byte(payload), &taskMsg); err != nil {
		return errors.ErrValidation.Wrap(err, "invalid payload json")
	}

	_, err := uc.taskUC.SubmitTask(uc.ctx, task.SubmitInput{
		TaskID:         taskMsg.TaskID,
		TaskType:       taskMsg.TaskType,
		ExecutorType:   taskMsg.ExecutorType,
		Priority:       taskMsg.Priority,
		Payload:        taskMsg.Payload,
		Timeout:        taskMsg.Timeout,
		IdempotencyKey: taskMsg.IdempotencyKey,
	})
	return err
}

// heartbeatChecker checks for stale connections.
func (uc *UseCase) heartbeatChecker() {
	defer uc.wg.Done()

	ticker := time.NewTicker(uc.config.HeartbeatInterval)
	defer ticker.Stop()

	for {
		select {
		case <-uc.ctx.Done():
			return
		case <-ticker.C:
			_, _ = uc.clientUC.CleanupStaleConnections(uc.ctx)
		}
	}
}

// HandleClientRegistration handles a new client registration.
func (uc *UseCase) HandleClientRegistration(ctx context.Context, msg entity.ClientRegistrationMessage) (*entity.Client, error) {
	log := logger.WithFields(uc.log).With("client_id", msg.ClientID, "type", msg.ClientType)

	registeredClient, err := uc.clientUC.RegisterClient(ctx, client.RegisterInput{
		ClientID:     msg.ClientID,
		ClientType:   msg.ClientType,
		Name:         msg.ClientName,
		Version:      msg.Version,
		Capabilities: msg.Capabilities,
		Metadata:     msg.Metadata,
	})

	if err != nil {
		log.Error().Err(err).Msg("Client registration failed")
		return nil, err
	}

	// Broadcast client registration
	if uc.connMgr != nil {
		broadcast := entity.ClientStatusMessage{
			BaseMessage: entity.BaseMessage{
				Type:      entity.MessageTypeClientStatus,
				Timestamp: time.Now().UTC(),
			},
			ClientID:   msg.ClientID,
			ClientType: msg.ClientType,
			Status:     entity.ConnectionStatusConnected,
		}
		_ = uc.connMgr.BroadcastToType(entity.ClientTypeMonitor, broadcast)
	}

	log.Info().Msg("Client registered successfully")
	return registeredClient, nil
}

// HandleClientDisconnect handles client disconnection.
func (uc *UseCase) HandleClientDisconnect(ctx context.Context, clientID string, reason string) error {
	log := logger.WithFields(uc.log).With("client_id", clientID, "reason", reason)

	clientInfo, _ := uc.clientUC.GetClient(ctx, clientID)

	if err := uc.clientUC.DisconnectClient(ctx, clientID, reason); err != nil {
		log.Warn().Err(err).Msg("Failed to disconnect client")
	}

	// Broadcast disconnection
	if uc.connMgr != nil && clientInfo != nil {
		broadcast := entity.ClientStatusMessage{
			BaseMessage: entity.BaseMessage{
				Type:      entity.MessageTypeClientStatus,
				Timestamp: time.Now().UTC(),
			},
			ClientID:   clientID,
			ClientType: clientInfo.Info.ClientType,
			Status:     entity.ConnectionStatusDisconnected,
		}
		_ = uc.connMgr.BroadcastToType(entity.ClientTypeMonitor, broadcast)
	}

	log.Info().Msg("Client disconnected")
	return nil
}

// HandleTaskSubmission handles a new task submission.
// If producer HMAC authentication is enabled on the task usecase, the hub verifies
// the signature extracted from the payload metadata before forwarding the task.
func (uc *UseCase) HandleTaskSubmission(ctx context.Context, msg entity.TaskMessage, clientID string) (*entity.Task, error) {
	log := logger.WithFields(uc.log).With("task_type", msg.TaskType, "client_id", clientID)

	// Optional: verify producer HMAC signature if auth is configured.
	if producerAuth := uc.taskUC.GetProducerAuth(); producerAuth != nil {
		sig, _ := msg.Payload["_signature"].(string)
		body, _ := msg.Payload["_signed_body"].(string)
		if sig != "" && body != "" {
			verified, _, _, err := producerAuth.Verify(ctx, sig, body)
			if err != nil {
				log.Warn().Err(err).Msg("Producer HMAC verification failed")
				return nil, err
			}
			if !verified {
				log.Warn().Msg("Producer HMAC signature invalid")
				return nil, fmt.Errorf("HMAC signature verification failed")
			}
		}
	}

	submittedTask, err := uc.taskUC.SubmitTask(ctx, task.SubmitInput{
		TaskID:         msg.TaskID,
		TaskType:       msg.TaskType,
		ExecutorType:   msg.ExecutorType,
		Priority:       msg.Priority,
		Payload:        msg.Payload,
		ClientID:       clientID,
		Timeout:        msg.Timeout,
		IdempotencyKey: msg.IdempotencyKey,
	})

	if err != nil {
		log.Error().Err(err).Msg("Task submission failed")
		return nil, err
	}

	log.Info().Str("task_id", submittedTask.TaskID).Msg("Task submitted")
	return submittedTask, nil
}

// HandleTaskResult handles a task result from a worker.
func (uc *UseCase) HandleTaskResult(ctx context.Context, msg entity.TaskResultMessage) error {
	log := logger.WithFields(uc.log).With("task_id", msg.TaskID, "status", msg.Status)

	var err error
	switch msg.Status {
	case entity.TaskStatusCompleted:
		err = uc.taskUC.CompleteTask(ctx, msg.TaskID, msg.Result)
	case entity.TaskStatusFailed:
		if msg.Error != nil {
			err = uc.taskUC.FailTask(ctx, msg.TaskID, msg.Error.Type, msg.Error.Message, msg.Error.Stacktrace)
		} else {
			err = uc.taskUC.FailTask(ctx, msg.TaskID, "unknown", "Unknown error", "")
		}
	default:
		log.Warn().Msg("Unknown task result status")
		return errors.ErrValidation.With("unknown status")
	}

	if err != nil {
		log.Error().Err(err).Msg("Failed to process task result")
		return err
	}

	log.Info().Msg("Task result processed")
	return nil
}

// HandleTaskProgress handles task progress update.
func (uc *UseCase) HandleTaskProgress(ctx context.Context, msg entity.TaskProgressMessage) error {
	// Forward progress to task client
	submittedTask, err := uc.taskUC.GetTask(ctx, msg.TaskID)
	if err != nil {
		return err
	}

	if uc.connMgr != nil && submittedTask.Context.ClientID != "" {
		_ = uc.connMgr.SendToClient(submittedTask.Context.ClientID, msg)
	}

	return nil
}

// HandleHeartbeat handles a heartbeat message.
func (uc *UseCase) HandleHeartbeat(ctx context.Context, clientID string, metrics map[string]any) error {
	return uc.clientUC.ProcessHeartbeat(ctx, clientID, metrics)
}

// HandleWorkerStatusChange handles worker status change.
func (uc *UseCase) HandleWorkerStatusChange(ctx context.Context, clientID string, status entity.WorkerStatus) error {
	log := logger.WithFields(uc.log).With("client_id", clientID, "status", status)

	if err := uc.clientUC.UpdateWorkerStatus(ctx, clientID, status); err != nil {
		log.Error().Err(err).Msg("Failed to update worker status")
		return err
	}

	// If worker becomes idle, try to assign pending tasks
	if status == entity.WorkerStatusIdle {
		go func() {
			_, _ = uc.taskUC.ProcessPendingTasks(context.Background())
		}()
	}

	return nil
}

// SendToClient sends a message to a specific client (implements task.TaskSender).
func (uc *UseCase) SendToClient(clientID string, message any) error {
	if uc.connMgr == nil {
		return errors.ErrInternalServer.With("connection manager not set")
	}
	return uc.connMgr.SendToClient(clientID, message)
}

// GetAvailableWorkers returns available workers for a task type (implements task.TaskSender).
func (uc *UseCase) GetAvailableWorkers(ctx context.Context, taskType string) ([]*entity.Client, error) {
	return uc.clientUC.GetAvailableWorkers(ctx, taskType)
}

// Broadcast sends a message to all connected clients.
func (uc *UseCase) Broadcast(message any) error {
	if uc.connMgr == nil {
		return errors.ErrInternalServer.With("connection manager not set")
	}
	return uc.connMgr.Broadcast(message)
}

// BroadcastToType sends a message to all clients of a specific type.
func (uc *UseCase) BroadcastToType(clientType entity.ClientType, message any) error {
	if uc.connMgr == nil {
		return errors.ErrInternalServer.With("connection manager not set")
	}
	return uc.connMgr.BroadcastToType(clientType, message)
}

// PublishTask publishes a task to Redis for distributed processing.
func (uc *UseCase) PublishTask(ctx context.Context, submittedTask *entity.Task) error {
	if uc.config.TaskChannel == "" && (uc.streamMgr == nil || !uc.streamMgr.Enabled()) {
		return nil
	}

	msg := entity.TaskMessage{
		BaseMessage: entity.BaseMessage{
			Type:      entity.MessageTypeTask,
			Timestamp: time.Now().UTC(),
		},
		TaskID:       submittedTask.TaskID,
		TaskType:     submittedTask.TaskType,
		ExecutorType: submittedTask.ExecutorType,
		Priority:     submittedTask.Priority,
		Payload:      submittedTask.Data,
		Timeout:      time.Duration(submittedTask.Timeout) * time.Second,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}

	if uc.streamMgr != nil && uc.streamMgr.Enabled() {
		_, err = uc.streamMgr.Add(ctx, map[string]any{
			"payload":   string(data),
			"task_id":   submittedTask.TaskID,
			"task_type": submittedTask.TaskType,
		})
		return err
	}

	return uc.pubsub.Publish(ctx, uc.config.TaskChannel, string(data))
}

// GetHubStats returns hub statistics.
func (uc *UseCase) GetHubStats(ctx context.Context) (*HubStats, error) {
	clientStats, err := uc.clientUC.GetStats(ctx)
	if err != nil {
		return nil, err
	}

	taskStats, err := uc.taskUC.GetStats(ctx)
	if err != nil {
		return nil, err
	}

	sessionCount, _ := uc.authUC.GetSessionCount(ctx)

	connectedCount := 0
	if uc.connMgr != nil {
		connectedCount = uc.connMgr.GetConnectedCount()
	}

	uc.messageCountMu.Lock()
	msgCount := uc.messageCount
	uc.messageCountMu.Unlock()

	return &HubStats{
		Clients:      clientStats,
		Tasks:        taskStats,
		Sessions:     sessionCount,
		Connections:  int64(connectedCount),
		MessageCount: msgCount,
		Uptime:       time.Since(uc.startTime),
	}, nil
}

// IncrementMessageCount increments the message counter.
func (uc *UseCase) IncrementMessageCount() {
	uc.messageCountMu.Lock()
	uc.messageCount++
	uc.messageCountMu.Unlock()
}

// HubStats holds aggregated hub statistics.
type HubStats struct {
	Clients      *client.ClientStats `json:"clients"`
	Tasks        *task.Stats         `json:"tasks"`
	Sessions     int64               `json:"sessions"`
	Connections  int64               `json:"connections"`
	MessageCount int64               `json:"message_count"`
	Uptime       time.Duration       `json:"uptime"`
}
