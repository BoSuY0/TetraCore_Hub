// Package rbac provides role-based access control functionality.
package rbac

import (
	"context"
	"fmt"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/eventbus"
	"github.com/tetra/core-hub/pkg/logger"
	"golang.org/x/crypto/bcrypt"
)

// UseCase provides RBAC operations.
type UseCase struct {
	userRepo repository.UserRepository
	roleRepo repository.RoleRepository
	eventBus eventbus.EventBus
	log      logger.LogFields
}

// NewUseCase creates a new RBAC UseCase.
func NewUseCase(userRepo repository.UserRepository, roleRepo repository.RoleRepository, eventBus eventbus.EventBus) *UseCase {
	return &UseCase{
		userRepo: userRepo,
		roleRepo: roleRepo,
		eventBus: eventBus,
		log:      logger.LogFields{"component": "rbac-usecase"},
	}
}

// CreateUserInput represents input for creating a user.
type CreateUserInput struct {
	Username string         `json:"username"`
	Email    string         `json:"email"`
	Password string         `json:"password"`
	RoleID   entity.RoleID  `json:"role_id"`
}

// UpdateUserInput represents input for updating a user.
type UpdateUserInput struct {
	Email    *string           `json:"email,omitempty"`
	RoleID   *entity.RoleID    `json:"role_id,omitempty"`
	Status   *entity.UserStatus `json:"status,omitempty"`
	Metadata *entity.UserMetadata `json:"metadata,omitempty"`
}

// CreateUser creates a new user.
func (uc *UseCase) CreateUser(ctx context.Context, input CreateUserInput) (*entity.User, error) {
	log := logger.WithFields(uc.log)

	// Validate role exists
	exists, err := uc.roleRepo.Exists(ctx, input.RoleID)
	if err != nil {
		return nil, fmt.Errorf("failed to check role: %w", err)
	}
	if !exists {
		return nil, fmt.Errorf("role %s does not exist", input.RoleID)
	}

	// Hash password
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(input.Password), bcrypt.DefaultCost)
	if err != nil {
		return nil, fmt.Errorf("failed to hash password: %w", err)
	}

	// Create user
	user := entity.NewUser(input.Username, input.Email, string(hashedPassword), input.RoleID)

	if err := uc.userRepo.Create(ctx, user); err != nil {
		return nil, fmt.Errorf("failed to create user: %w", err)
	}

	log.Info().Str("user_id", user.ID).Str("username", user.Username).Msg("User created")

	// Publish event
	if uc.eventBus != nil {
		uc.eventBus.PublishAsync(ctx, eventbus.NewEvent(
			"user.created",
			"rbac",
			map[string]any{
				"user_id":  user.ID,
				"username": user.Username,
				"role_id":  string(user.RoleID),
			},
		))
	}

	return user, nil
}

// GetUser retrieves a user by ID.
func (uc *UseCase) GetUser(ctx context.Context, id string) (*entity.User, error) {
	return uc.userRepo.GetByID(ctx, id)
}

// GetUserByUsername retrieves a user by username.
func (uc *UseCase) GetUserByUsername(ctx context.Context, username string) (*entity.User, error) {
	return uc.userRepo.GetByUsername(ctx, username)
}

// UpdateUser updates a user.
func (uc *UseCase) UpdateUser(ctx context.Context, id string, input UpdateUserInput) (*entity.User, error) {
	user, err := uc.userRepo.GetByID(ctx, id)
	if err != nil {
		return nil, err
	}

	if input.Email != nil {
		user.Email = *input.Email
	}
	if input.RoleID != nil {
		// Validate role exists
		exists, err := uc.roleRepo.Exists(ctx, *input.RoleID)
		if err != nil {
			return nil, fmt.Errorf("failed to check role: %w", err)
		}
		if !exists {
			return nil, fmt.Errorf("role %s does not exist", *input.RoleID)
		}
		user.RoleID = *input.RoleID
	}
	if input.Status != nil {
		user.Status = *input.Status
	}
	if input.Metadata != nil {
		user.Metadata = *input.Metadata
	}

	user.UpdatedAt = time.Now().UTC()

	if err := uc.userRepo.Update(ctx, user); err != nil {
		return nil, fmt.Errorf("failed to update user: %w", err)
	}

	return user, nil
}

// DeleteUser deletes a user.
func (uc *UseCase) DeleteUser(ctx context.Context, id string) error {
	log := logger.WithFields(uc.log)

	user, err := uc.userRepo.GetByID(ctx, id)
	if err != nil {
		return err
	}

	if err := uc.userRepo.Delete(ctx, id); err != nil {
		return fmt.Errorf("failed to delete user: %w", err)
	}

	log.Info().Str("user_id", id).Str("username", user.Username).Msg("User deleted")

	// Publish event
	if uc.eventBus != nil {
		uc.eventBus.PublishAsync(ctx, eventbus.NewEvent(
			"user.deleted",
			"rbac",
			map[string]any{
				"user_id":  id,
				"username": user.Username,
			},
		))
	}

	return nil
}

// ListUsers lists users with optional filtering.
func (uc *UseCase) ListUsers(ctx context.Context, filter repository.UserFilter) ([]*entity.User, error) {
	return uc.userRepo.List(ctx, filter)
}

// ChangePassword changes a user's password.
func (uc *UseCase) ChangePassword(ctx context.Context, id, currentPassword, newPassword string) error {
	user, err := uc.userRepo.GetByID(ctx, id)
	if err != nil {
		return err
	}

	// Verify current password
	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(currentPassword)); err != nil {
		return entity.ErrInvalidPassword
	}

	// Hash new password
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(newPassword), bcrypt.DefaultCost)
	if err != nil {
		return fmt.Errorf("failed to hash password: %w", err)
	}

	// Check password history
	if user.IsPasswordInHistory(string(hashedPassword)) {
		return entity.ErrPasswordReused
	}

	// Update password
	user.UpdatePassword(string(hashedPassword), 5) // Keep last 5 passwords

	if err := uc.userRepo.Update(ctx, user); err != nil {
		return fmt.Errorf("failed to update password: %w", err)
	}

	return nil
}

// ResetPassword resets a user's password (admin action).
func (uc *UseCase) ResetPassword(ctx context.Context, id, newPassword string) error {
	user, err := uc.userRepo.GetByID(ctx, id)
	if err != nil {
		return err
	}

	// Hash new password
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(newPassword), bcrypt.DefaultCost)
	if err != nil {
		return fmt.Errorf("failed to hash password: %w", err)
	}

	// Update password (don't check history for admin reset)
	user.UpdatePassword(string(hashedPassword), 5)

	if err := uc.userRepo.Update(ctx, user); err != nil {
		return fmt.Errorf("failed to update password: %w", err)
	}

	return nil
}

// GetUserPermissions returns all permissions for a user.
func (uc *UseCase) GetUserPermissions(ctx context.Context, userID string) (entity.PermissionSet, error) {
	user, err := uc.userRepo.GetByID(ctx, userID)
	if err != nil {
		return nil, err
	}

	role, err := uc.roleRepo.GetByID(ctx, user.RoleID)
	if err != nil {
		return nil, err
	}

	return entity.NewPermissionSet(role.Permissions), nil
}

// HasPermission checks if a user has a specific permission.
func (uc *UseCase) HasPermission(ctx context.Context, userID string, perm entity.Permission) (bool, error) {
	perms, err := uc.GetUserPermissions(ctx, userID)
	if err != nil {
		return false, err
	}
	return perms.Has(perm), nil
}

// Role operations

// CreateRole creates a new role.
func (uc *UseCase) CreateRole(ctx context.Context, role *entity.Role) error {
	return uc.roleRepo.Create(ctx, role)
}

// GetRole retrieves a role by ID.
func (uc *UseCase) GetRole(ctx context.Context, id entity.RoleID) (*entity.Role, error) {
	return uc.roleRepo.GetByID(ctx, id)
}

// UpdateRole updates a role.
func (uc *UseCase) UpdateRole(ctx context.Context, role *entity.Role) error {
	return uc.roleRepo.Update(ctx, role)
}

// DeleteRole deletes a role.
func (uc *UseCase) DeleteRole(ctx context.Context, id entity.RoleID) error {
	return uc.roleRepo.Delete(ctx, id)
}

// ListRoles lists all roles.
func (uc *UseCase) ListRoles(ctx context.Context) ([]*entity.Role, error) {
	return uc.roleRepo.List(ctx)
}

// InitializeDefaults initializes default roles and admin user.
func (uc *UseCase) InitializeDefaults(ctx context.Context, adminUsername, adminPassword string) error {
	log := logger.WithFields(uc.log)

	// Initialize default roles
	if err := uc.roleRepo.InitDefaults(ctx); err != nil {
		return fmt.Errorf("failed to initialize default roles: %w", err)
	}

	// Check if admin user exists
	exists, err := uc.userRepo.ExistsByUsername(ctx, adminUsername)
	if err != nil {
		return fmt.Errorf("failed to check admin user: %w", err)
	}

	if !exists && adminUsername != "" && adminPassword != "" {
		// Create admin user
		_, err := uc.CreateUser(ctx, CreateUserInput{
			Username: adminUsername,
			Password: adminPassword,
			RoleID:   entity.RoleAdmin,
		})
		if err != nil {
			return fmt.Errorf("failed to create admin user: %w", err)
		}
		log.Info().Str("username", adminUsername).Msg("Created admin user")
	}

	return nil
}
