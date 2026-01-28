// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// ClientService provides client management operations.
type ClientService interface {
	GetClient(ctx context.Context, clientID string) (*entity.Client, error)
	GetAllClients(ctx context.Context) ([]*entity.Client, error)
	GetClientsByType(ctx context.Context, clientType entity.ClientType) ([]*entity.Client, error)
	GetConnectedClients(ctx context.Context) ([]*entity.Client, error)
	DisconnectClient(ctx context.Context, clientID string, reason string) error
	DeleteClient(ctx context.Context, clientID string) error
	GetStats(ctx context.Context) (*ClientStats, error)
}

// ClientStats represents client statistics.
type ClientStats struct {
	Total        int64 `json:"total"`
	Bots         int64 `json:"bots"`
	Workers      int64 `json:"workers"`
	WorkerAPIs   int64 `json:"worker_apis"`
	Monitors     int64 `json:"monitors"`
	Admins       int64 `json:"admins"`
	Connected    int64 `json:"connected"`
	Disconnected int64 `json:"disconnected"`
}

// ClientHandler handles client management endpoints.
type ClientHandler struct {
	clientService ClientService
}

// NewClientHandler creates a new client handler.
func NewClientHandler(clientService ClientService) *ClientHandler {
	return &ClientHandler{
		clientService: clientService,
	}
}

// ClientResponse represents a client in API responses.
type ClientResponse struct {
	ClientID         string                     `json:"client_id"`
	ClientType       string                     `json:"client_type"`
	ClientName       string                     `json:"client_name"`
	ClientVersion    string                     `json:"client_version"`
	ConnectionStatus string                     `json:"connection_status"`
	WorkerStatus     *string                    `json:"worker_status,omitempty"`
	RegisteredAt     string                     `json:"registered_at"`
	LastSeen         string                     `json:"last_seen"`
	Stats            *ClientStatsResponse       `json:"stats,omitempty"`
	Capabilities     *entity.WorkerCapabilities `json:"capabilities,omitempty"`
}

// ClientStatsResponse represents client stats in API responses.
type ClientStatsResponse struct {
	TotalTasks      int64   `json:"total_tasks"`
	SuccessfulTasks int64   `json:"successful_tasks"`
	FailedTasks     int64   `json:"failed_tasks"`
	ActiveTasks     int     `json:"active_tasks"`
	AvgProcessTime  float64 `json:"avg_processing_time_ms"`
}

// clientToResponse converts a client entity to API response.
func clientToResponse(c *entity.Client) *ClientResponse {
	resp := &ClientResponse{
		ClientID:         c.Info.ClientID,
		ClientType:       string(c.Info.ClientType),
		ClientName:       c.Info.ClientName,
		ClientVersion:    c.Info.ClientVersion,
		ConnectionStatus: string(c.Info.ConnectionStatus),
		RegisteredAt:     c.Info.RegisteredAt.Format("2006-01-02T15:04:05Z"),
		LastSeen:         c.Info.LastSeen.Format("2006-01-02T15:04:05Z"),
		Capabilities:     c.Info.Capabilities,
	}

	if c.Info.WorkerStatus != nil {
		ws := string(*c.Info.WorkerStatus)
		resp.WorkerStatus = &ws
	}

	if c.Info.Stats != nil {
		resp.Stats = &ClientStatsResponse{
			TotalTasks:      c.Info.Stats.TotalTasks,
			SuccessfulTasks: c.Info.Stats.SuccessfulTasks,
			FailedTasks:     c.Info.Stats.FailedTasks,
			ActiveTasks:     c.Info.Stats.ActiveTasks,
			AvgProcessTime:  c.Info.Stats.AverageProcessingTime,
		}
	}

	return resp
}

// GetClients handles GET /api/v1/clients
func (h *ClientHandler) GetClients(c *fiber.Ctx) error {
	// Parse query parameters
	clientType := c.Query("type")
	connectedOnly := c.Query("connected") == "true"

	var clients []*entity.Client
	var err error

	if connectedOnly {
		clients, err = h.clientService.GetConnectedClients(c.Context())
	} else if clientType != "" {
		clients, err = h.clientService.GetClientsByType(c.Context(), entity.ClientType(clientType))
	} else {
		clients, err = h.clientService.GetAllClients(c.Context())
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve clients",
			"code":    "INTERNAL_ERROR",
		})
	}

	// Convert to response format
	response := make([]*ClientResponse, len(clients))
	for i, client := range clients {
		response[i] = clientToResponse(client)
	}

	return c.JSON(fiber.Map{
		"clients": response,
		"total":   len(response),
	})
}

// GetClient handles GET /api/v1/clients/:id
func (h *ClientHandler) GetClient(c *fiber.Ctx) error {
	clientID := c.Params("id")
	if clientID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Client ID is required",
			"code":    "MISSING_CLIENT_ID",
		})
	}

	client, err := h.clientService.GetClient(c.Context(), clientID)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Client not found",
			"code":    "CLIENT_NOT_FOUND",
		})
	}

	return c.JSON(clientToResponse(client))
}

// DeleteClient handles DELETE /api/v1/clients/:id
func (h *ClientHandler) DeleteClient(c *fiber.Ctx) error {
	clientID := c.Params("id")
	if clientID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Client ID is required",
			"code":    "MISSING_CLIENT_ID",
		})
	}

	// First disconnect the client
	_ = h.clientService.DisconnectClient(c.Context(), clientID, "deleted_via_api")

	// Then delete
	if err := h.clientService.DeleteClient(c.Context(), clientID); err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Client not found",
			"code":    "CLIENT_NOT_FOUND",
		})
	}

	return c.JSON(fiber.Map{
		"message":   "Client deleted successfully",
		"client_id": clientID,
	})
}

// DisconnectClient handles POST /api/v1/clients/:id/disconnect
func (h *ClientHandler) DisconnectClient(c *fiber.Ctx) error {
	clientID := c.Params("id")
	if clientID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Client ID is required",
			"code":    "MISSING_CLIENT_ID",
		})
	}

	var req struct {
		Reason string `json:"reason"`
	}
	_ = c.BodyParser(&req)

	if req.Reason == "" {
		req.Reason = "disconnected_via_api"
	}

	if err := h.clientService.DisconnectClient(c.Context(), clientID, req.Reason); err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Client not found",
			"code":    "CLIENT_NOT_FOUND",
		})
	}

	return c.JSON(fiber.Map{
		"message":   "Client disconnected successfully",
		"client_id": clientID,
	})
}

// GetClientStats handles GET /api/v1/clients/stats
func (h *ClientHandler) GetClientStats(c *fiber.Ctx) error {
	stats, err := h.clientService.GetStats(c.Context())
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve stats",
			"code":    "INTERNAL_ERROR",
		})
	}

	return c.JSON(stats)
}
