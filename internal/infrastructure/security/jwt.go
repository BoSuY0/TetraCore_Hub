// Package security provides security infrastructure for TetraCore Hub.
package security

import (
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
)

// JWTConfig holds JWT configuration.
type JWTConfig struct {
	Secret                string
	AccessTokenDuration   time.Duration
	RefreshTokenDuration  time.Duration
	Issuer                string
	Audience              []string
	AllowedClockSkew      time.Duration
}

// DefaultJWTConfig returns default JWT configuration.
func DefaultJWTConfig() JWTConfig {
	return JWTConfig{
		AccessTokenDuration:  24 * time.Hour,
		RefreshTokenDuration: 7 * 24 * time.Hour,
		Issuer:               "tetracore-hub",
		Audience:             []string{"tetracore"},
		AllowedClockSkew:     time.Minute,
	}
}

// TokenClaims represents JWT claims.
type TokenClaims struct {
	jwt.RegisteredClaims
	UserID      string   `json:"user_id"`
	Username    string   `json:"username"`
	Role        string   `json:"role"`
	Permissions []string `json:"permissions,omitempty"`
	SessionID   string   `json:"session_id,omitempty"`
	TokenType   string   `json:"token_type"` // "access" or "refresh"
}

// TokenPair contains access and refresh tokens.
type TokenPair struct {
	AccessToken  string    `json:"access_token"`
	RefreshToken string    `json:"refresh_token"`
	TokenType    string    `json:"token_type"`
	ExpiresIn    int64     `json:"expires_in"`
	ExpiresAt    time.Time `json:"expires_at"`
}

// JWTManager manages JWT token operations.
type JWTManager struct {
	config    JWTConfig
	blacklist map[string]time.Time
	mu        sync.RWMutex
}

// NewJWTManager creates a new JWT manager from config.
func NewJWTManager(cfg JWTConfig) *JWTManager {
	if cfg.Secret == "" {
		cfg.Secret = uuid.New().String()
	}
	return &JWTManager{
		config:    cfg,
		blacklist: make(map[string]time.Time),
	}
}

// NewJWTManagerSimple creates a new JWT manager with secret and issuer.
func NewJWTManagerSimple(secret, issuer string) *JWTManager {
	cfg := DefaultJWTConfig()
	cfg.Secret = secret
	cfg.Issuer = issuer
	return NewJWTManager(cfg)
}

// CreateToken creates an access token (backward compatibility alias).
func (m *JWTManager) CreateToken(userID, username, role string, sessionID string) (string, error) {
	token, _, err := m.GenerateAccessToken(userID, username, role, nil, sessionID)
	return token, err
}

// CreateRefreshToken creates a refresh token (backward compatibility alias).
func (m *JWTManager) CreateRefreshToken(userID, username, role string, sessionID string) (string, error) {
	token, _, err := m.GenerateRefreshToken(userID, username, role, sessionID)
	return token, err
}

// GenerateTokenPair generates both access and refresh tokens.
func (m *JWTManager) GenerateTokenPair(userID, username, role string, permissions []string, sessionID string) (*TokenPair, error) {
	accessToken, accessExp, err := m.generateToken(userID, username, role, permissions, sessionID, "access", m.config.AccessTokenDuration)
	if err != nil {
		return nil, fmt.Errorf("failed to generate access token: %w", err)
	}

	refreshToken, _, err := m.generateToken(userID, username, role, nil, sessionID, "refresh", m.config.RefreshTokenDuration)
	if err != nil {
		return nil, fmt.Errorf("failed to generate refresh token: %w", err)
	}

	return &TokenPair{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		TokenType:    "Bearer",
		ExpiresIn:    int64(m.config.AccessTokenDuration.Seconds()),
		ExpiresAt:    accessExp,
	}, nil
}

// GenerateAccessToken generates only an access token.
func (m *JWTManager) GenerateAccessToken(userID, username, role string, permissions []string, sessionID string) (string, time.Time, error) {
	return m.generateToken(userID, username, role, permissions, sessionID, "access", m.config.AccessTokenDuration)
}

// GenerateRefreshToken generates only a refresh token.
func (m *JWTManager) GenerateRefreshToken(userID, username, role string, sessionID string) (string, time.Time, error) {
	return m.generateToken(userID, username, role, nil, sessionID, "refresh", m.config.RefreshTokenDuration)
}

func (m *JWTManager) generateToken(userID, username, role string, permissions []string, sessionID, tokenType string, duration time.Duration) (string, time.Time, error) {
	now := time.Now().UTC()
	expiresAt := now.Add(duration)

	claims := TokenClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			ID:        uuid.New().String(),
			Subject:   userID,
			Issuer:    m.config.Issuer,
			Audience:  m.config.Audience,
			IssuedAt:  jwt.NewNumericDate(now),
			NotBefore: jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(expiresAt),
		},
		UserID:      userID,
		Username:    username,
		Role:        role,
		Permissions: permissions,
		SessionID:   sessionID,
		TokenType:   tokenType,
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenString, err := token.SignedString([]byte(m.config.Secret))
	if err != nil {
		return "", time.Time{}, err
	}

	return tokenString, expiresAt, nil
}

// ValidateToken validates a token and returns the claims.
func (m *JWTManager) ValidateToken(tokenString string) (*TokenClaims, error) {
	// Check blacklist
	if m.IsBlacklisted(tokenString) {
		return nil, errors.New("token is blacklisted")
	}

	token, err := jwt.ParseWithClaims(tokenString, &TokenClaims{}, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return []byte(m.config.Secret), nil
	}, jwt.WithLeeway(m.config.AllowedClockSkew))

	if err != nil {
		return nil, fmt.Errorf("failed to parse token: %w", err)
	}

	claims, ok := token.Claims.(*TokenClaims)
	if !ok || !token.Valid {
		return nil, errors.New("invalid token claims")
	}

	return claims, nil
}

// ValidateAccessToken validates an access token.
func (m *JWTManager) ValidateAccessToken(tokenString string) (*TokenClaims, error) {
	claims, err := m.ValidateToken(tokenString)
	if err != nil {
		return nil, err
	}

	if claims.TokenType != "access" {
		return nil, errors.New("not an access token")
	}

	return claims, nil
}

// ValidateRefreshToken validates a refresh token.
func (m *JWTManager) ValidateRefreshToken(tokenString string) (*TokenClaims, error) {
	claims, err := m.ValidateToken(tokenString)
	if err != nil {
		return nil, err
	}

	if claims.TokenType != "refresh" {
		return nil, errors.New("not a refresh token")
	}

	return claims, nil
}

// RefreshTokens refreshes the token pair using a refresh token.
func (m *JWTManager) RefreshTokens(refreshToken string) (*TokenPair, error) {
	claims, err := m.ValidateRefreshToken(refreshToken)
	if err != nil {
		return nil, err
	}

	// Blacklist old refresh token
	m.Blacklist(refreshToken, claims.ExpiresAt.Time)

	// Generate new token pair
	return m.GenerateTokenPair(claims.UserID, claims.Username, claims.Role, claims.Permissions, claims.SessionID)
}

// Blacklist adds a token to the blacklist.
func (m *JWTManager) Blacklist(tokenString string, expiresAt time.Time) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.blacklist[tokenString] = expiresAt
}

// IsBlacklisted checks if a token is blacklisted.
func (m *JWTManager) IsBlacklisted(tokenString string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	_, exists := m.blacklist[tokenString]
	return exists
}

// CleanupBlacklist removes expired tokens from the blacklist.
func (m *JWTManager) CleanupBlacklist() int {
	m.mu.Lock()
	defer m.mu.Unlock()

	now := time.Now().UTC()
	removed := 0

	for token, expiresAt := range m.blacklist {
		if now.After(expiresAt) {
			delete(m.blacklist, token)
			removed++
		}
	}

	return removed
}

// StartBlacklistCleanup starts a background cleanup goroutine.
func (m *JWTManager) StartBlacklistCleanup(interval time.Duration, stopCh <-chan struct{}) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			select {
			case <-stopCh:
				return
			case <-ticker.C:
				m.CleanupBlacklist()
			}
		}
	}()
}

// BlacklistCount returns the number of blacklisted tokens.
func (m *JWTManager) BlacklistCount() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.blacklist)
}

// GetTokenExpiration extracts the expiration time from a token without full validation.
func (m *JWTManager) GetTokenExpiration(tokenString string) (time.Time, error) {
	token, _, err := jwt.NewParser().ParseUnverified(tokenString, &TokenClaims{})
	if err != nil {
		return time.Time{}, err
	}

	claims, ok := token.Claims.(*TokenClaims)
	if !ok {
		return time.Time{}, errors.New("invalid claims")
	}

	if claims.ExpiresAt == nil {
		return time.Time{}, errors.New("no expiration claim")
	}

	return claims.ExpiresAt.Time, nil
}

// IsTokenExpiringSoon checks if a token is expiring within a threshold.
func (m *JWTManager) IsTokenExpiringSoon(tokenString string, threshold time.Duration) (bool, error) {
	exp, err := m.GetTokenExpiration(tokenString)
	if err != nil {
		return false, err
	}

	return time.Until(exp) < threshold, nil
}
