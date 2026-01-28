// Package auth provides authentication use cases for TetraCore Hub.
package auth

import (
	"context"
	"fmt"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/security"
	"github.com/tetra/core-hub/pkg/errors"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds authentication configuration.
type Config struct {
	AdminUsername         string
	AdminPasswordHash     string
	SessionDuration       time.Duration
	TokenRefreshThreshold time.Duration
	MaxLoginAttempts      int
	LockoutDuration       time.Duration
}

// UseCase handles authentication operations.
type UseCase struct {
	sessionRepo   repository.SessionRepository
	attemptRepo   repository.LoginAttemptRepository
	blacklistRepo repository.TokenBlacklistRepository
	jwtManager    *security.JWTManager
	hasher        *security.BCryptHasher
	config        Config
	log           logger.LogFields
}

// NewUseCase creates a new auth use case.
func NewUseCase(
	sessionRepo repository.SessionRepository,
	attemptRepo repository.LoginAttemptRepository,
	blacklistRepo repository.TokenBlacklistRepository,
	jwtManager *security.JWTManager,
	hasher *security.BCryptHasher,
	config Config,
) *UseCase {
	return &UseCase{
		sessionRepo:   sessionRepo,
		attemptRepo:   attemptRepo,
		blacklistRepo: blacklistRepo,
		jwtManager:    jwtManager,
		hasher:        hasher,
		config:        config,
		log:           logger.LogFields{"component": "auth-usecase"},
	}
}

// LoginInput represents login credentials.
type LoginInput struct {
	Username  string
	Password  string
	IPAddress string
	UserAgent string
}

// LoginOutput represents successful login result.
type LoginOutput struct {
	Session      *entity.Session
	AccessToken  string
	RefreshToken string
	ExpiresAt    time.Time
}

// Login authenticates a user and creates a session.
func (uc *UseCase) Login(ctx context.Context, input LoginInput) (*LoginOutput, error) {
	log := logger.WithFields(uc.log).With("username", input.Username, "ip", input.IPAddress)

	// Check if locked out
	locked, err := uc.attemptRepo.IsLocked(ctx, input.Username, input.IPAddress)
	if err != nil {
		log.Error().Err(err).Msg("Failed to check lockout status")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to check lockout")
	}
	if locked {
		remaining, _ := uc.attemptRepo.GetLockoutRemaining(ctx, input.Username, input.IPAddress)
		log.Warn().Msg("Login attempt while locked out")
		return nil, errors.NewHTTPError(429,
			fmt.Sprintf("Account locked. Try again in %v", remaining.Round(time.Second)))
	}

	// Validate credentials
	if input.Username != uc.config.AdminUsername {
		uc.recordFailedAttempt(ctx, input, "invalid_username")
		return nil, errors.ErrUnauthorized.With("invalid credentials")
	}

	if !uc.hasher.Verify(input.Password, uc.config.AdminPasswordHash) {
		uc.recordFailedAttempt(ctx, input, "invalid_password")
		return nil, errors.ErrUnauthorized.With("invalid credentials")
	}

	// Clear previous failed attempts on successful login
	_ = uc.attemptRepo.ClearAttempts(ctx, input.Username, input.IPAddress)

	// Record successful attempt
	_ = uc.attemptRepo.Record(ctx, input.Username, input.IPAddress, true, "")

	// Create session first to get sessionID for tokens
	session := entity.NewSession(input.Username, input.Username, "admin", uc.config.SessionDuration)
	session.IPAddress = input.IPAddress
	session.UserAgent = input.UserAgent

	// Generate tokens with sessionID
	accessToken, err := uc.jwtManager.CreateToken(input.Username, input.Username, "admin", session.SessionID)
	if err != nil {
		log.Error().Err(err).Msg("Failed to create access token")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to create token")
	}

	refreshToken, err := uc.jwtManager.CreateRefreshToken(input.Username, input.Username, "admin", session.SessionID)
	if err != nil {
		log.Error().Err(err).Msg("Failed to create refresh token")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to create refresh token")
	}

	// Set tokens in session
	session.AccessToken = accessToken
	session.RefreshToken = refreshToken
	expiresAt := session.ExpiresAt

	if err := uc.sessionRepo.Save(ctx, session); err != nil {
		log.Error().Err(err).Msg("Failed to save session")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to save session")
	}

	log.Info().Msg("User logged in successfully")

	return &LoginOutput{
		Session:      session,
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		ExpiresAt:    expiresAt,
	}, nil
}

// recordFailedAttempt records a failed login attempt.
func (uc *UseCase) recordFailedAttempt(ctx context.Context, input LoginInput, reason string) {
	_ = uc.attemptRepo.Record(ctx, input.Username, input.IPAddress, false, reason)
}

// Logout invalidates a session and blacklists tokens.
func (uc *UseCase) Logout(ctx context.Context, sessionID string) error {
	log := logger.WithFields(uc.log).With("session_id", sessionID)

	session, err := uc.sessionRepo.Get(ctx, sessionID)
	if err != nil {
		return errors.ErrNotFound.With("session not found")
	}

	// Blacklist tokens
	_ = uc.blacklistRepo.Add(ctx, session.AccessToken, session.ExpiresAt)
	_ = uc.blacklistRepo.Add(ctx, session.RefreshToken, session.ExpiresAt.Add(uc.config.SessionDuration*6))

	// Delete session
	if err := uc.sessionRepo.Delete(ctx, sessionID); err != nil {
		log.Error().Err(err).Msg("Failed to delete session")
		return errors.ErrInternalServer.Wrap(err, "failed to delete session")
	}

	log.Info().Msg("User logged out")
	return nil
}

// LogoutAll invalidates all sessions for a user.
func (uc *UseCase) LogoutAll(ctx context.Context, userID string) error {
	log := logger.WithFields(uc.log).With("user_id", userID)

	sessions, err := uc.sessionRepo.GetByUser(ctx, userID)
	if err != nil {
		log.Error().Err(err).Msg("Failed to get user sessions")
		return errors.ErrInternalServer.Wrap(err, "failed to get sessions")
	}

	for _, session := range sessions {
		_ = uc.blacklistRepo.Add(ctx, session.AccessToken, session.ExpiresAt)
		_ = uc.blacklistRepo.Add(ctx, session.RefreshToken, session.ExpiresAt.Add(uc.config.SessionDuration*6))
	}

	if err := uc.sessionRepo.DeleteByUser(ctx, userID); err != nil {
		log.Error().Err(err).Msg("Failed to delete user sessions")
		return errors.ErrInternalServer.Wrap(err, "failed to delete sessions")
	}

	log.Info().Int("count", len(sessions)).Msg("All user sessions invalidated")
	return nil
}

// ValidateToken validates an access token and returns the session.
func (uc *UseCase) ValidateToken(ctx context.Context, token string) (*entity.Session, error) {
	// Check if token is blacklisted
	blacklisted, err := uc.blacklistRepo.IsBlacklisted(ctx, token)
	if err != nil {
		return nil, errors.ErrInternalServer.Wrap(err, "failed to check blacklist")
	}
	if blacklisted {
		return nil, errors.ErrUnauthorized.With("token is blacklisted")
	}

	// Validate JWT
	claims, err := uc.jwtManager.ValidateToken(token)
	if err != nil {
		return nil, errors.ErrUnauthorized.Wrap(err, "invalid token")
	}

	// Get session by token
	session, err := uc.sessionRepo.GetByToken(ctx, token)
	if err != nil {
		return nil, errors.ErrUnauthorized.With("session not found")
	}

	// Check if session is valid
	if !session.IsActive || session.IsExpired() {
		return nil, errors.ErrUnauthorized.With("session expired")
	}

	// Update last activity
	_ = uc.sessionRepo.Touch(ctx, session.SessionID)

	// Check if token needs refresh
	if claims.ExpiresAt != nil {
		timeUntilExpiry := time.Until(claims.ExpiresAt.Time)
		if timeUntilExpiry < uc.config.TokenRefreshThreshold {
			session.ShouldRefresh = true
		}
	}

	return session, nil
}

// RefreshToken generates new tokens from a refresh token.
func (uc *UseCase) RefreshToken(ctx context.Context, refreshToken string) (*LoginOutput, error) {
	log := logger.WithFields(uc.log)

	// Check if refresh token is blacklisted
	blacklisted, err := uc.blacklistRepo.IsBlacklisted(ctx, refreshToken)
	if err != nil {
		return nil, errors.ErrInternalServer.Wrap(err, "failed to check blacklist")
	}
	if blacklisted {
		return nil, errors.ErrUnauthorized.With("refresh token is blacklisted")
	}

	// Validate refresh token
	claims, err := uc.jwtManager.ValidateRefreshToken(refreshToken)
	if err != nil {
		return nil, errors.ErrUnauthorized.Wrap(err, "invalid refresh token")
	}

	// Get session by refresh token
	session, err := uc.sessionRepo.GetByRefreshToken(ctx, refreshToken)
	if err != nil {
		return nil, errors.ErrUnauthorized.With("session not found")
	}

	// Blacklist old tokens
	_ = uc.blacklistRepo.Add(ctx, session.AccessToken, time.Now().Add(time.Hour))
	_ = uc.blacklistRepo.Add(ctx, refreshToken, time.Now().Add(time.Hour))

	// Generate new tokens
	newAccessToken, err := uc.jwtManager.CreateToken(claims.UserID, claims.Username, claims.Role, session.SessionID)
	if err != nil {
		log.Error().Err(err).Msg("Failed to create new access token")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to create token")
	}

	newRefreshToken, err := uc.jwtManager.CreateRefreshToken(claims.UserID, claims.Username, claims.Role, session.SessionID)
	if err != nil {
		log.Error().Err(err).Msg("Failed to create new refresh token")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to create refresh token")
	}

	// Update session
	expiresAt := time.Now().UTC().Add(uc.config.SessionDuration)
	session.AccessToken = newAccessToken
	session.RefreshToken = newRefreshToken
	session.ExpiresAt = expiresAt
	session.Touch()

	if err := uc.sessionRepo.Save(ctx, session); err != nil {
		log.Error().Err(err).Msg("Failed to update session")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to update session")
	}

	log.Info().Str("session_id", session.SessionID).Msg("Token refreshed")

	return &LoginOutput{
		Session:      session,
		AccessToken:  newAccessToken,
		RefreshToken: newRefreshToken,
		ExpiresAt:    expiresAt,
	}, nil
}

// GetSession retrieves a session by ID.
func (uc *UseCase) GetSession(ctx context.Context, sessionID string) (*entity.Session, error) {
	session, err := uc.sessionRepo.Get(ctx, sessionID)
	if err != nil {
		return nil, errors.ErrNotFound.With("session not found")
	}
	return session, nil
}

// GetUserSessions retrieves all sessions for a user.
func (uc *UseCase) GetUserSessions(ctx context.Context, userID string) ([]*entity.Session, error) {
	return uc.sessionRepo.GetByUser(ctx, userID)
}

// GetAllSessions retrieves all active sessions.
func (uc *UseCase) GetAllSessions(ctx context.Context) ([]*entity.Session, error) {
	return uc.sessionRepo.GetAll(ctx)
}

// CleanupExpiredSessions removes expired sessions.
func (uc *UseCase) CleanupExpiredSessions(ctx context.Context) (int64, error) {
	log := logger.WithFields(uc.log)

	deleted, err := uc.sessionRepo.DeleteExpired(ctx)
	if err != nil {
		log.Error().Err(err).Msg("Failed to cleanup expired sessions")
		return 0, err
	}

	if deleted > 0 {
		log.Info().Int64("count", deleted).Msg("Cleaned up expired sessions")
	}

	return deleted, nil
}

// GetSessionCount returns the total number of active sessions.
func (uc *UseCase) GetSessionCount(ctx context.Context) (int64, error) {
	return uc.sessionRepo.Count(ctx)
}

// IsTokenBlacklisted checks if a token is blacklisted.
func (uc *UseCase) IsTokenBlacklisted(ctx context.Context, token string) (bool, error) {
	return uc.blacklistRepo.IsBlacklisted(ctx, token)
}

// HashPassword creates a hash of a password.
func (uc *UseCase) HashPassword(password string) (string, error) {
	return uc.hasher.Hash(password)
}

// VerifyPassword verifies a password against a hash.
func (uc *UseCase) VerifyPassword(hash, password string) bool {
	return uc.hasher.Verify(password, hash)
}
