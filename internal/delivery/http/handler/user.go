// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/usecase/rbac"
	"github.com/tetra/core-hub/pkg/logger"
)

// UserHandler handles user-related HTTP requests.
type UserHandler struct {
	rbacUseCase *rbac.UseCase
	log         logger.LogFields
}

// NewUserHandler creates a new UserHandler.
func NewUserHandler(rbacUseCase *rbac.UseCase) *UserHandler {
	return &UserHandler{
		rbacUseCase: rbacUseCase,
		log:         logger.LogFields{"component": "user-handler"},
	}
}

// CreateUserRequest represents a create user request.
type CreateUserRequest struct {
	Username string        `json:"username" validate:"required,min=3,max=50"`
	Email    string        `json:"email" validate:"omitempty,email"`
	Password string        `json:"password" validate:"required,min=8"`
	RoleID   entity.RoleID `json:"role_id" validate:"required"`
}

// UpdateUserRequest represents an update user request.
type UpdateUserRequest struct {
	Email    *string              `json:"email,omitempty"`
	RoleID   *entity.RoleID       `json:"role_id,omitempty"`
	Status   *entity.UserStatus   `json:"status,omitempty"`
	Metadata *entity.UserMetadata `json:"metadata,omitempty"`
}

// ChangePasswordRequest represents a change password request.
type ChangePasswordRequest struct {
	CurrentPassword string `json:"current_password" validate:"required"`
	NewPassword     string `json:"new_password" validate:"required,min=8"`
}

// ResetPasswordRequest represents a reset password request (admin).
type ResetPasswordRequest struct {
	NewPassword string `json:"new_password" validate:"required,min=8"`
}

// GetUsers returns all users.
func (h *UserHandler) GetUsers(c *fiber.Ctx) error {
	filter := repository.UserFilter{
		RoleID: entity.RoleID(c.Query("role_id")),
		Status: entity.UserStatus(c.Query("status")),
		Search: c.Query("search"),
		Limit:  c.QueryInt("limit", 50),
		Offset: c.QueryInt("offset", 0),
	}

	users, err := h.rbacUseCase.ListUsers(c.Context(), filter)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get users",
		})
	}

	// Convert to public representation
	publicUsers := make([]entity.UserPublic, len(users))
	for i, user := range users {
		publicUsers[i] = user.ToPublic()
	}

	return c.JSON(fiber.Map{
		"users": publicUsers,
		"count": len(publicUsers),
	})
}

// GetUser returns a single user by ID.
func (h *UserHandler) GetUser(c *fiber.Ctx) error {
	id := c.Params("id")

	user, err := h.rbacUseCase.GetUser(c.Context(), id)
	if err != nil {
		if err == entity.ErrUserNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "User not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get user",
		})
	}

	return c.JSON(user.ToPublic())
}

// CreateUser creates a new user.
func (h *UserHandler) CreateUser(c *fiber.Ctx) error {
	var req CreateUserRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	user, err := h.rbacUseCase.CreateUser(c.Context(), rbac.CreateUserInput{
		Username: req.Username,
		Email:    req.Email,
		Password: req.Password,
		RoleID:   req.RoleID,
	})
	if err != nil {
		if err == entity.ErrUserAlreadyExists {
			return c.Status(fiber.StatusConflict).JSON(fiber.Map{
				"error":   true,
				"message": "User already exists",
			})
		}
		log := logger.WithFields(h.log)
		log.Error().Err(err).Msg("Failed to create user")
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to create user",
		})
	}

	return c.Status(fiber.StatusCreated).JSON(user.ToPublic())
}

// UpdateUser updates a user.
func (h *UserHandler) UpdateUser(c *fiber.Ctx) error {
	id := c.Params("id")

	var req UpdateUserRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	user, err := h.rbacUseCase.UpdateUser(c.Context(), id, rbac.UpdateUserInput{
		Email:    req.Email,
		RoleID:   req.RoleID,
		Status:   req.Status,
		Metadata: req.Metadata,
	})
	if err != nil {
		if err == entity.ErrUserNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "User not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to update user",
		})
	}

	return c.JSON(user.ToPublic())
}

// DeleteUser deletes a user.
func (h *UserHandler) DeleteUser(c *fiber.Ctx) error {
	id := c.Params("id")

	// Prevent self-deletion
	currentUserID := c.Locals("user_id")
	if currentUserID != nil && currentUserID.(string) == id {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Cannot delete your own account",
		})
	}

	if err := h.rbacUseCase.DeleteUser(c.Context(), id); err != nil {
		if err == entity.ErrUserNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "User not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete user",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "User deleted",
	})
}

// ChangePassword changes the current user's password.
func (h *UserHandler) ChangePassword(c *fiber.Ctx) error {
	userID := c.Locals("user_id")
	if userID == nil {
		return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
			"error":   true,
			"message": "Unauthorized",
		})
	}

	var req ChangePasswordRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	if err := h.rbacUseCase.ChangePassword(c.Context(), userID.(string), req.CurrentPassword, req.NewPassword); err != nil {
		if err == entity.ErrInvalidPassword {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Current password is incorrect",
			})
		}
		if err == entity.ErrPasswordReused {
			return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
				"error":   true,
				"message": "Password has been used before",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to change password",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Password changed",
	})
}

// ResetPassword resets a user's password (admin action).
func (h *UserHandler) ResetPassword(c *fiber.Ctx) error {
	id := c.Params("id")

	var req ResetPasswordRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	if err := h.rbacUseCase.ResetPassword(c.Context(), id, req.NewPassword); err != nil {
		if err == entity.ErrUserNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "User not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to reset password",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Password reset",
	})
}

// GetCurrentUser returns the current authenticated user.
func (h *UserHandler) GetCurrentUser(c *fiber.Ctx) error {
	userID := c.Locals("user_id")
	if userID == nil {
		return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
			"error":   true,
			"message": "Unauthorized",
		})
	}

	user, err := h.rbacUseCase.GetUser(c.Context(), userID.(string))
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get user",
		})
	}

	// Get user permissions
	perms, err := h.rbacUseCase.GetUserPermissions(c.Context(), userID.(string))
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get permissions",
		})
	}

	return c.JSON(fiber.Map{
		"user":        user.ToPublic(),
		"permissions": perms.ToSlice(),
	})
}
