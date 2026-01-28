// Package middleware provides HTTP middleware for TetraCore Hub.
package middleware

import (
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/google/uuid"
	"github.com/tetra/core-hub/pkg/logger"
)

// RequestID adds a unique request ID to each request.
func RequestID() fiber.Handler {
	return func(c *fiber.Ctx) error {
		// Check for existing request ID in header
		requestID := c.Get("X-Request-ID")
		if requestID == "" {
			requestID = uuid.New().String()
		}

		// Set request ID in header and locals
		c.Set("X-Request-ID", requestID)
		c.Locals("request_id", requestID)

		return c.Next()
	}
}

// Logger provides request logging middleware.
func Logger() fiber.Handler {
	return func(c *fiber.Ctx) error {
		start := time.Now()

		// Get request ID
		requestID := c.Locals("request_id")
		if requestID == nil {
			requestID = uuid.New().String()
		}

		// Process request
		err := c.Next()

		// Calculate latency
		latency := time.Since(start)

		// Get status code
		status := c.Response().StatusCode()

		// Get user ID if authenticated
		userID := c.Locals("user_id")

		// Create log event
		log := logger.WithRequestID(requestID.(string))

		event := log.Info()
		if status >= 500 {
			event = log.Error()
		} else if status >= 400 {
			event = log.Warn()
		}

		event.
			Str("method", c.Method()).
			Str("path", c.Path()).
			Int("status", status).
			Dur("latency", latency).
			Str("ip", c.IP()).
			Str("user_agent", c.Get("User-Agent"))

		if userID != nil {
			event.Str("user_id", userID.(string))
		}

		if err != nil {
			event.Err(err)
		}

		event.Msg("HTTP request")

		return err
	}
}

// ErrorLogger provides error logging middleware.
func ErrorLogger() fiber.Handler {
	return func(c *fiber.Ctx) error {
		err := c.Next()
		if err != nil {
			requestID := c.Locals("request_id")
			log := logger.WithRequestID(requestID.(string))

			log.Error().
				Err(err).
				Str("method", c.Method()).
				Str("path", c.Path()).
				Msg("Request error")
		}
		return err
	}
}
