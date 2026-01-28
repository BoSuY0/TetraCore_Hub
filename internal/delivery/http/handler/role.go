// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	infrarepo "github.com/tetra/core-hub/internal/infrastructure/repository"
	"github.com/tetra/core-hub/internal/usecase/rbac"
	"github.com/tetra/core-hub/pkg/logger"
)

// RoleHandler handles role-related HTTP requests.
type RoleHandler struct {
	rbacUseCase *rbac.UseCase
	log         logger.LogFields
}

// NewRoleHandler creates a new RoleHandler.
func NewRoleHandler(rbacUseCase *rbac.UseCase) *RoleHandler {
	return &RoleHandler{
		rbacUseCase: rbacUseCase,
		log:         logger.LogFields{"component": "role-handler"},
	}
}

// CreateRoleRequest represents a create role request.
type CreateRoleRequest struct {
	ID          entity.RoleID      `json:"id" validate:"required,min=2,max=50"`
	Name        string             `json:"name" validate:"required,min=2,max=100"`
	Description string             `json:"description"`
	Permissions []entity.Permission `json:"permissions" validate:"required,min=1"`
}

// UpdateRoleRequest represents an update role request.
type UpdateRoleRequest struct {
	Name        *string             `json:"name,omitempty"`
	Description *string             `json:"description,omitempty"`
	Permissions []entity.Permission `json:"permissions,omitempty"`
}

// GetRoles returns all roles.
func (h *RoleHandler) GetRoles(c *fiber.Ctx) error {
	roles, err := h.rbacUseCase.ListRoles(c.Context())
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get roles",
		})
	}

	return c.JSON(fiber.Map{
		"roles": roles,
		"count": len(roles),
	})
}

// GetRole returns a single role by ID.
func (h *RoleHandler) GetRole(c *fiber.Ctx) error {
	id := entity.RoleID(c.Params("id"))

	role, err := h.rbacUseCase.GetRole(c.Context(), id)
	if err != nil {
		if err == infrarepo.ErrRoleNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Role not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get role",
		})
	}

	return c.JSON(role)
}

// CreateRole creates a new role.
func (h *RoleHandler) CreateRole(c *fiber.Ctx) error {
	var req CreateRoleRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	now := time.Now().UTC()
	role := &entity.Role{
		ID:          req.ID,
		Name:        req.Name,
		Description: req.Description,
		Permissions: req.Permissions,
		IsSystem:    false,
		CreatedAt:   now,
		UpdatedAt:   now,
	}

	if err := h.rbacUseCase.CreateRole(c.Context(), role); err != nil {
		log := logger.WithFields(h.log)
		log.Error().Err(err).Msg("Failed to create role")
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to create role",
		})
	}

	return c.Status(fiber.StatusCreated).JSON(role)
}

// UpdateRole updates a role.
func (h *RoleHandler) UpdateRole(c *fiber.Ctx) error {
	id := entity.RoleID(c.Params("id"))

	// Get existing role
	role, err := h.rbacUseCase.GetRole(c.Context(), id)
	if err != nil {
		if err == infrarepo.ErrRoleNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Role not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get role",
		})
	}

	if role.IsSystem {
		return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
			"error":   true,
			"message": "Cannot modify system role",
		})
	}

	var req UpdateRoleRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	if req.Name != nil {
		role.Name = *req.Name
	}
	if req.Description != nil {
		role.Description = *req.Description
	}
	if req.Permissions != nil {
		role.Permissions = req.Permissions
	}
	role.UpdatedAt = time.Now().UTC()

	if err := h.rbacUseCase.UpdateRole(c.Context(), role); err != nil {
		if err == infrarepo.ErrRoleIsSystem {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Cannot modify system role",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to update role",
		})
	}

	return c.JSON(role)
}

// DeleteRole deletes a role.
func (h *RoleHandler) DeleteRole(c *fiber.Ctx) error {
	id := entity.RoleID(c.Params("id"))

	if err := h.rbacUseCase.DeleteRole(c.Context(), id); err != nil {
		if err == infrarepo.ErrRoleNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Role not found",
			})
		}
		if err == infrarepo.ErrRoleIsSystem {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Cannot delete system role",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete role",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Role deleted",
	})
}

// GetPermissions returns all available permissions.
func (h *RoleHandler) GetPermissions(c *fiber.Ctx) error {
	perms := entity.AllPermissions()
	return c.JSON(fiber.Map{
		"permissions": perms,
		"count":       len(perms),
	})
}
