// Package adapter provides adapters between usecases and HTTP handlers.
package adapter

import (
	"context"
	"time"

	"github.com/tetra/core-hub/internal/delivery/http/handler"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/usecase/auth"
	"github.com/tetra/core-hub/internal/usecase/client"
	"github.com/tetra/core-hub/internal/usecase/hub"
	"github.com/tetra/core-hub/internal/usecase/task"
)

// AuthAdapter adapts auth.UseCase to handler.AuthService.
type AuthAdapter struct {
	uc *auth.UseCase
}

// NewAuthAdapter creates a new auth adapter.
func NewAuthAdapter(uc *auth.UseCase) *AuthAdapter {
	return &AuthAdapter{uc: uc}
}

// Login implements handler.AuthService.
func (a *AuthAdapter) Login(ctx context.Context, input handler.LoginInput) (*handler.LoginOutput, error) {
	result, err := a.uc.Login(ctx, auth.LoginInput{
		Username:  input.Username,
		Password:  input.Password,
		IPAddress: input.IPAddress,
		UserAgent: input.UserAgent,
	})
	if err != nil {
		return nil, err
	}
	return &handler.LoginOutput{
		Session:      result.Session,
		AccessToken:  result.AccessToken,
		RefreshToken: result.RefreshToken,
		ExpiresAt:    result.ExpiresAt,
	}, nil
}

// Logout implements handler.AuthService.
func (a *AuthAdapter) Logout(ctx context.Context, sessionID string) error {
	return a.uc.Logout(ctx, sessionID)
}

// RefreshToken implements handler.AuthService.
func (a *AuthAdapter) RefreshToken(ctx context.Context, refreshToken string) (*handler.LoginOutput, error) {
	result, err := a.uc.RefreshToken(ctx, refreshToken)
	if err != nil {
		return nil, err
	}
	return &handler.LoginOutput{
		Session:      result.Session,
		AccessToken:  result.AccessToken,
		RefreshToken: result.RefreshToken,
		ExpiresAt:    result.ExpiresAt,
	}, nil
}

// ValidateToken implements handler.AuthService.
func (a *AuthAdapter) ValidateToken(ctx context.Context, token string) (*entity.Session, error) {
	return a.uc.ValidateToken(ctx, token)
}

// HubAdapter adapts hub.UseCase to handler.StatsProvider.
type HubAdapter struct {
	uc *hub.UseCase
}

// NewHubAdapter creates a new hub adapter.
func NewHubAdapter(uc *hub.UseCase) *HubAdapter {
	return &HubAdapter{uc: uc}
}

// GetHubStats implements handler.StatsProvider.
func (a *HubAdapter) GetHubStats(ctx context.Context) (*handler.HubStats, error) {
	stats, err := a.uc.GetHubStats(ctx)
	if err != nil {
		return nil, err
	}
	return &handler.HubStats{
		Clients:      stats.Clients,
		Tasks:        stats.Tasks,
		Sessions:     stats.Sessions,
		Connections:  stats.Connections,
		MessageCount: stats.MessageCount,
		Uptime:       stats.Uptime,
	}, nil
}

// ClientAdapter adapts client.UseCase to handler.ClientService.
type ClientAdapter struct {
	uc *client.UseCase
}

// NewClientAdapter creates a new client adapter.
func NewClientAdapter(uc *client.UseCase) *ClientAdapter {
	return &ClientAdapter{uc: uc}
}

// GetClient implements handler.ClientService.
func (a *ClientAdapter) GetClient(ctx context.Context, clientID string) (*entity.Client, error) {
	return a.uc.GetClient(ctx, clientID)
}

// GetAllClients implements handler.ClientService.
func (a *ClientAdapter) GetAllClients(ctx context.Context) ([]*entity.Client, error) {
	return a.uc.GetAllClients(ctx)
}

// GetClientsByType implements handler.ClientService.
func (a *ClientAdapter) GetClientsByType(ctx context.Context, clientType entity.ClientType) ([]*entity.Client, error) {
	return a.uc.GetClientsByType(ctx, clientType)
}

// GetConnectedClients implements handler.ClientService.
func (a *ClientAdapter) GetConnectedClients(ctx context.Context) ([]*entity.Client, error) {
	return a.uc.GetConnectedClients(ctx)
}

// DisconnectClient implements handler.ClientService.
func (a *ClientAdapter) DisconnectClient(ctx context.Context, clientID string, reason string) error {
	return a.uc.DisconnectClient(ctx, clientID, reason)
}

// DeleteClient implements handler.ClientService.
func (a *ClientAdapter) DeleteClient(ctx context.Context, clientID string) error {
	return a.uc.DeleteClient(ctx, clientID)
}

// GetStats implements handler.ClientService.
func (a *ClientAdapter) GetStats(ctx context.Context) (*handler.ClientStats, error) {
	stats, err := a.uc.GetStats(ctx)
	if err != nil {
		return nil, err
	}
	return &handler.ClientStats{
		Total:        stats.Total,
		Bots:         stats.Bots,
		Workers:      stats.Workers,
		WorkerAPIs:   stats.WorkerAPIs,
		Monitors:     stats.Monitors,
		Admins:       stats.Admins,
		Connected:    stats.Connected,
		Disconnected: stats.Disconnected,
	}, nil
}

// TaskAdapter adapts task.UseCase to handler.TaskService.
type TaskAdapter struct {
	uc *task.UseCase
}

// NewTaskAdapter creates a new task adapter.
func NewTaskAdapter(uc *task.UseCase) *TaskAdapter {
	return &TaskAdapter{uc: uc}
}

// SubmitTask implements handler.TaskService.
func (a *TaskAdapter) SubmitTask(ctx context.Context, input handler.TaskSubmitInput) (*entity.Task, error) {
	return a.uc.SubmitTask(ctx, task.SubmitInput{
		TaskType:       input.TaskType,
		ExecutorType:   input.ExecutorType,
		Priority:       input.Priority,
		Payload:        input.Payload,
		ClientID:       input.ClientID,
		Timeout:        input.Timeout,
		IdempotencyKey: input.IdempotencyKey,
	})
}

// GetTask implements handler.TaskService.
func (a *TaskAdapter) GetTask(ctx context.Context, taskID string) (*entity.Task, error) {
	return a.uc.GetTask(ctx, taskID)
}

// GetAllTasks implements handler.TaskService.
func (a *TaskAdapter) GetAllTasks(ctx context.Context, limit, offset int) ([]*entity.Task, error) {
	return a.uc.GetAllTasks(ctx, limit, offset)
}

// GetTasksByStatus implements handler.TaskService.
func (a *TaskAdapter) GetTasksByStatus(ctx context.Context, status entity.TaskStatus, limit int) ([]*entity.Task, error) {
	return a.uc.GetTasksByStatus(ctx, status, limit)
}

// GetTasksByType implements handler.TaskService.
func (a *TaskAdapter) GetTasksByType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Task, error) {
	return a.uc.GetTasksByType(ctx, taskType, limit)
}

// CancelTask implements handler.TaskService.
func (a *TaskAdapter) CancelTask(ctx context.Context, taskID string, reason string) error {
	return a.uc.CancelTask(ctx, taskID, reason)
}

// RetryTask implements handler.TaskService.
func (a *TaskAdapter) RetryTask(ctx context.Context, taskID string) error {
	return a.uc.RetryTask(ctx, taskID)
}

// DeleteTask implements handler.TaskService.
func (a *TaskAdapter) DeleteTask(ctx context.Context, taskID string) error {
	return a.uc.DeleteTask(ctx, taskID)
}

// GetStats implements handler.TaskService.
func (a *TaskAdapter) GetStats(ctx context.Context) (*handler.TaskStatsResponse, error) {
	stats, err := a.uc.GetStats(ctx)
	if err != nil {
		return nil, err
	}
	return &handler.TaskStatsResponse{
		TotalTasks:        stats.TotalTasks,
		PendingTasks:      stats.PendingTasks,
		ProcessingTasks:   stats.ProcessingTasks,
		CompletedTasks:    stats.CompletedTasks,
		FailedTasks:       stats.FailedTasks,
		TasksByType:       stats.TasksByType,
		AvgProcessingTime: stats.AvgProcessingTime,
	}, nil
}

// SessionAdapter adapts auth.UseCase to handler.SessionService.
type SessionAdapter struct {
	uc *auth.UseCase
}

// NewSessionAdapter creates a new session adapter.
func NewSessionAdapter(uc *auth.UseCase) *SessionAdapter {
	return &SessionAdapter{uc: uc}
}

// GetSession implements handler.SessionService.
func (a *SessionAdapter) GetSession(ctx context.Context, sessionID string) (*entity.Session, error) {
	return a.uc.GetSession(ctx, sessionID)
}

// GetAllSessions implements handler.SessionService.
func (a *SessionAdapter) GetAllSessions(ctx context.Context) ([]*entity.Session, error) {
	return a.uc.GetAllSessions(ctx)
}

// GetSessionsByUser implements handler.SessionService.
func (a *SessionAdapter) GetSessionsByUser(ctx context.Context, userID string) ([]*entity.Session, error) {
	return a.uc.GetUserSessions(ctx, userID)
}

// InvalidateSession implements handler.SessionService.
func (a *SessionAdapter) InvalidateSession(ctx context.Context, sessionID string) error {
	return a.uc.Logout(ctx, sessionID)
}

// InvalidateUserSessions implements handler.SessionService.
func (a *SessionAdapter) InvalidateUserSessions(ctx context.Context, userID string) error {
	return a.uc.LogoutAll(ctx, userID)
}

// GetSessionCount implements handler.SessionService.
func (a *SessionAdapter) GetSessionCount(ctx context.Context) (int64, error) {
	return a.uc.GetSessionCount(ctx)
}

// Ensure adapters implement interfaces at compile time.
var (
	_ handler.AuthService    = (*AuthAdapter)(nil)
	_ handler.StatsProvider  = (*HubAdapter)(nil)
	_ handler.ClientService  = (*ClientAdapter)(nil)
	_ handler.TaskService    = (*TaskAdapter)(nil)
	_ handler.SessionService = (*SessionAdapter)(nil)
)

// unused - prevents import error for time
var _ = time.Second
