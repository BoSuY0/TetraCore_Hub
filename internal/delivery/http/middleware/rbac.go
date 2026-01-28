// Package middleware provides HTTP middleware for TetraCore Hub.
package middleware

import (
	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/usecase/rbac"
	"github.com/tetra/core-hub/pkg/logger"
)

// RBACMiddleware provides role-based access control middleware.
type RBACMiddleware struct {
	rbacUseCase *rbac.UseCase
	log         logger.LogFields
}

// NewRBACMiddleware creates a new RBAC middleware.
func NewRBACMiddleware(rbacUseCase *rbac.UseCase) *RBACMiddleware {
	return &RBACMiddleware{
		rbacUseCase: rbacUseCase,
		log:         logger.LogFields{"component": "rbac-middleware"},
	}
}

// RequirePermission returns middleware that checks for a specific permission.
func (m *RBACMiddleware) RequirePermission(perm entity.Permission) fiber.Handler {
	return func(c *fiber.Ctx) error {
		userID := c.Locals("user_id")
		if userID == nil {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Unauthorized",
			})
		}

		hasPermission, err := m.rbacUseCase.HasPermission(c.Context(), userID.(string), perm)
		if err != nil {
			log := logger.WithFields(m.log)
			log.Error().Err(err).Str("user_id", userID.(string)).Msg("Failed to check permission")
			return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
				"error":   true,
				"message": "Failed to check permissions",
			})
		}

		if !hasPermission {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":      true,
				"message":    "Insufficient permissions",
				"required":   string(perm),
			})
		}

		return c.Next()
	}
}

// RequireAnyPermission returns middleware that checks for any of the given permissions.
func (m *RBACMiddleware) RequireAnyPermission(perms ...entity.Permission) fiber.Handler {
	return func(c *fiber.Ctx) error {
		userID := c.Locals("user_id")
		if userID == nil {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Unauthorized",
			})
		}

		permSet, err := m.rbacUseCase.GetUserPermissions(c.Context(), userID.(string))
		if err != nil {
			log := logger.WithFields(m.log)
			log.Error().Err(err).Str("user_id", userID.(string)).Msg("Failed to get permissions")
			return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
				"error":   true,
				"message": "Failed to check permissions",
			})
		}

		if !permSet.HasAny(perms...) {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Insufficient permissions",
			})
		}

		return c.Next()
	}
}

// RequireAllPermissions returns middleware that checks for all of the given permissions.
func (m *RBACMiddleware) RequireAllPermissions(perms ...entity.Permission) fiber.Handler {
	return func(c *fiber.Ctx) error {
		userID := c.Locals("user_id")
		if userID == nil {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Unauthorized",
			})
		}

		permSet, err := m.rbacUseCase.GetUserPermissions(c.Context(), userID.(string))
		if err != nil {
			log := logger.WithFields(m.log)
			log.Error().Err(err).Str("user_id", userID.(string)).Msg("Failed to get permissions")
			return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
				"error":   true,
				"message": "Failed to check permissions",
			})
		}

		if !permSet.HasAll(perms...) {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Insufficient permissions",
			})
		}

		return c.Next()
	}
}

// RequireRole returns middleware that checks for a specific role.
func (m *RBACMiddleware) RequireRole(roleID entity.RoleID) fiber.Handler {
	return func(c *fiber.Ctx) error {
		userRoleID := c.Locals("role_id")
		if userRoleID == nil {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Unauthorized",
			})
		}

		if entity.RoleID(userRoleID.(string)) != roleID {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":    true,
				"message":  "Insufficient role",
				"required": string(roleID),
			})
		}

		return c.Next()
	}
}

// RequireAdmin is a shortcut for requiring admin role.
func (m *RBACMiddleware) RequireAdmin() fiber.Handler {
	return m.RequireRole(entity.RoleAdmin)
}

// LoadUserPermissions loads user permissions into context for later use.
func (m *RBACMiddleware) LoadUserPermissions() fiber.Handler {
	return func(c *fiber.Ctx) error {
		userID := c.Locals("user_id")
		if userID == nil {
			return c.Next()
		}

		permSet, err := m.rbacUseCase.GetUserPermissions(c.Context(), userID.(string))
		if err != nil {
			log := logger.WithFields(m.log)
			log.Warn().Err(err).Str("user_id", userID.(string)).Msg("Failed to load user permissions")
			return c.Next()
		}

		c.Locals("permissions", permSet)
		return c.Next()
	}
}

// CheckPermission is a helper to check permission in handlers.
func CheckPermission(c *fiber.Ctx, perm entity.Permission) bool {
	permSet, ok := c.Locals("permissions").(entity.PermissionSet)
	if !ok {
		return false
	}
	return permSet.Has(perm)
}

// GetUserPermissions gets user permissions from context.
func GetUserPermissions(c *fiber.Ctx) entity.PermissionSet {
	permSet, ok := c.Locals("permissions").(entity.PermissionSet)
	if !ok {
		return nil
	}
	return permSet
}
