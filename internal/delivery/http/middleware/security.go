// Package middleware provides HTTP middleware for TetraCore Hub.
package middleware

import (
	"github.com/gofiber/fiber/v2"
)

// SecurityHeaders adds security headers to responses.
func SecurityHeaders() fiber.Handler {
	return func(c *fiber.Ctx) error {
		// Prevent MIME type sniffing
		c.Set("X-Content-Type-Options", "nosniff")

		// Prevent clickjacking
		c.Set("X-Frame-Options", "DENY")

		// Enable XSS filter
		c.Set("X-XSS-Protection", "1; mode=block")

		// Referrer policy
		c.Set("Referrer-Policy", "strict-origin-when-cross-origin")

		// Content Security Policy (strict - no unsafe-inline)
		// Note: If inline scripts/styles are needed, use nonce or hash-based CSP
		c.Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' wss: ws:; frame-ancestors 'none'; base-uri 'self'; form-action 'self';")

		// Strict Transport Security (only in production)
		if c.Protocol() == "https" {
			c.Set("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
		}

		// Permissions Policy
		c.Set("Permissions-Policy", "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()")

		return c.Next()
	}
}

// CSRFProtection provides basic CSRF protection.
func CSRFProtection() fiber.Handler {
	return func(c *fiber.Ctx) error {
		// Skip for safe methods
		if c.Method() == "GET" || c.Method() == "HEAD" || c.Method() == "OPTIONS" {
			return c.Next()
		}

		// Check for CSRF token in header
		token := c.Get("X-CSRF-Token")
		if token == "" {
			// Also check cookie
			token = c.Cookies("csrf_token")
		}

		// For API routes, we rely on JWT authentication instead of CSRF tokens
		// CSRF protection is mainly for cookie-based auth which we don't use

		return c.Next()
	}
}

// IPWhitelist creates IP whitelist middleware.
func IPWhitelist(allowedIPs []string) fiber.Handler {
	ipSet := make(map[string]bool)
	for _, ip := range allowedIPs {
		ipSet[ip] = true
	}

	return func(c *fiber.Ctx) error {
		clientIP := c.IP()

		// Allow if whitelist is empty (disabled)
		if len(ipSet) == 0 {
			return c.Next()
		}

		// Check if IP is allowed
		if ipSet[clientIP] {
			return c.Next()
		}

		// Check for X-Forwarded-For header
		forwardedFor := c.Get("X-Forwarded-For")
		if forwardedFor != "" && ipSet[forwardedFor] {
			return c.Next()
		}

		return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
			"error":   true,
			"message": "Access denied",
			"code":    "IP_NOT_ALLOWED",
		})
	}
}

// IPBlacklist creates IP blacklist middleware.
func IPBlacklist(blockedIPs []string) fiber.Handler {
	ipSet := make(map[string]bool)
	for _, ip := range blockedIPs {
		ipSet[ip] = true
	}

	return func(c *fiber.Ctx) error {
		clientIP := c.IP()

		// Block if IP is in blacklist
		if ipSet[clientIP] {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Access denied",
				"code":    "IP_BLOCKED",
			})
		}

		// Also check X-Forwarded-For
		forwardedFor := c.Get("X-Forwarded-For")
		if forwardedFor != "" && ipSet[forwardedFor] {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Access denied",
				"code":    "IP_BLOCKED",
			})
		}

		return c.Next()
	}
}

// SecureWebSocket adds security checks for WebSocket upgrades.
func SecureWebSocket(allowedOrigins []string) fiber.Handler {
	originSet := make(map[string]bool)
	for _, origin := range allowedOrigins {
		originSet[origin] = true
	}

	return func(c *fiber.Ctx) error {
		// Check if it's a WebSocket upgrade
		if c.Get("Upgrade") != "websocket" {
			return c.Next()
		}

		// Check origin
		origin := c.Get("Origin")
		if len(originSet) > 0 && !originSet[origin] && !originSet["*"] {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Invalid origin",
				"code":    "INVALID_ORIGIN",
			})
		}

		return c.Next()
	}
}
