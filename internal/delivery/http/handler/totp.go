// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"
	"fmt"
	"net/url"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// TOTPService provides TOTP operations.
type TOTPService interface {
	Setup(ctx context.Context, userID string) (*entity.TOTPSetupResponse, error)
	Verify(ctx context.Context, userID, code string) error
	Validate(ctx context.Context, userID, code string) (bool, error)
	Disable(ctx context.Context, userID, code string) error
	GetStatus(ctx context.Context, userID string) (*TOTPStatus, error)
	RegenerateBackupCodes(ctx context.Context, userID, code string) ([]string, error)
}

// TOTPStatus represents TOTP status for a user.
type TOTPStatus struct {
	Enabled              bool  `json:"enabled"`
	Verified             bool  `json:"verified"`
	RemainingBackupCodes int   `json:"remaining_backup_codes"`
}

// TOTPHandler handles TOTP endpoints.
type TOTPHandler struct {
	service TOTPService
	issuer  string
}

// NewTOTPHandler creates a new TOTP handler.
func NewTOTPHandler(service TOTPService, issuer string) *TOTPHandler {
	return &TOTPHandler{
		service: service,
		issuer:  issuer,
	}
}

// Setup handles POST /auth/2fa/setup
func (h *TOTPHandler) Setup(c *fiber.Ctx) error {
	userID := c.Locals("user_id").(string)

	setup, err := h.service.Setup(c.Context(), userID)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to setup 2FA",
		})
	}

	// Generate QR code URL
	username := c.Locals("username")
	if username == nil {
		username = userID
	}
	qrURL := generateTOTPURL(setup.Secret, username.(string), h.issuer)

	return c.JSON(fiber.Map{
		"secret":       setup.Secret,
		"qr_code_url":  qrURL,
		"backup_codes": setup.BackupCodes,
		"message":      "Scan the QR code with your authenticator app, then verify with a code",
	})
}

// Verify handles POST /auth/2fa/verify
func (h *TOTPHandler) Verify(c *fiber.Ctx) error {
	userID := c.Locals("user_id").(string)

	var req struct {
		Code string `json:"code"`
	}
	if err := c.BodyParser(&req); err != nil || req.Code == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Code is required",
		})
	}

	if err := h.service.Verify(c.Context(), userID, req.Code); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid code",
		})
	}

	return c.JSON(fiber.Map{
		"message": "2FA enabled successfully",
	})
}

// Disable handles POST /auth/2fa/disable
func (h *TOTPHandler) Disable(c *fiber.Ctx) error {
	userID := c.Locals("user_id").(string)

	var req struct {
		Code string `json:"code"`
	}
	if err := c.BodyParser(&req); err != nil || req.Code == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Code is required to disable 2FA",
		})
	}

	if err := h.service.Disable(c.Context(), userID, req.Code); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid code",
		})
	}

	return c.JSON(fiber.Map{
		"message": "2FA disabled successfully",
	})
}

// Status handles GET /auth/2fa/status
func (h *TOTPHandler) Status(c *fiber.Ctx) error {
	userID := c.Locals("user_id").(string)

	status, err := h.service.GetStatus(c.Context(), userID)
	if err != nil {
		return c.JSON(&TOTPStatus{
			Enabled:              false,
			Verified:             false,
			RemainingBackupCodes: 0,
		})
	}

	return c.JSON(status)
}

// RegenerateBackupCodes handles POST /auth/2fa/backup-codes
func (h *TOTPHandler) RegenerateBackupCodes(c *fiber.Ctx) error {
	userID := c.Locals("user_id").(string)

	var req struct {
		Code string `json:"code"`
	}
	if err := c.BodyParser(&req); err != nil || req.Code == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Code is required to regenerate backup codes",
		})
	}

	codes, err := h.service.RegenerateBackupCodes(c.Context(), userID, req.Code)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid code",
		})
	}

	return c.JSON(fiber.Map{
		"backup_codes": codes,
		"message":      "Backup codes regenerated. Store them securely.",
	})
}

// generateTOTPURL generates an otpauth URL for QR code generation.
func generateTOTPURL(secret, account, issuer string) string {
	return fmt.Sprintf(
		"otpauth://totp/%s:%s?secret=%s&issuer=%s&algorithm=SHA1&digits=6&period=30",
		url.PathEscape(issuer),
		url.PathEscape(account),
		secret,
		url.QueryEscape(issuer),
	)
}
