// Package logger provides structured logging using zerolog.
package logger

import (
	"io"
	"os"
	"strings"
	"time"

	"github.com/rs/zerolog"
)

var (
	// Log is the global logger instance.
	Log zerolog.Logger
)

// Config holds logger configuration.
type Config struct {
	Level      string `mapstructure:"level"`
	Format     string `mapstructure:"format"` // "json" or "console"
	TimeFormat string `mapstructure:"time_format"`
	CallerInfo bool   `mapstructure:"caller_info"`
}

// DefaultConfig returns default logger configuration.
func DefaultConfig() Config {
	return Config{
		Level:      "info",
		Format:     "json",
		TimeFormat: time.RFC3339,
		CallerInfo: false,
	}
}

// Init initializes the global logger with the given configuration.
func Init(cfg Config) {
	// Set time format
	zerolog.TimeFieldFormat = cfg.TimeFormat

	// Determine output writer
	var output io.Writer = os.Stdout

	// Use console writer for non-JSON format
	if strings.ToLower(cfg.Format) == "console" {
		output = zerolog.ConsoleWriter{
			Out:        os.Stdout,
			TimeFormat: cfg.TimeFormat,
			NoColor:    false,
		}
	}

	// Create logger
	Log = zerolog.New(output).With().Timestamp().Logger()

	// Add caller info if enabled
	if cfg.CallerInfo {
		Log = Log.With().Caller().Logger()
	}

	// Set log level
	level := parseLevel(cfg.Level)
	zerolog.SetGlobalLevel(level)
	Log = Log.Level(level)
}

// parseLevel converts a string log level to zerolog.Level.
func parseLevel(level string) zerolog.Level {
	switch strings.ToUpper(level) {
	case "TRACE":
		return zerolog.TraceLevel
	case "DEBUG":
		return zerolog.DebugLevel
	case "INFO":
		return zerolog.InfoLevel
	case "WARN", "WARNING":
		return zerolog.WarnLevel
	case "ERROR":
		return zerolog.ErrorLevel
	case "FATAL":
		return zerolog.FatalLevel
	case "PANIC":
		return zerolog.PanicLevel
	default:
		return zerolog.InfoLevel
	}
}

// SetLevel changes the global log level.
func SetLevel(level string) {
	l := parseLevel(level)
	zerolog.SetGlobalLevel(l)
	Log = Log.Level(l)
}

// With creates a child logger with additional context fields.
func With() zerolog.Context {
	return Log.With()
}

// Debug logs a debug message.
func Debug() *zerolog.Event {
	return Log.Debug()
}

// Info logs an info message.
func Info() *zerolog.Event {
	return Log.Info()
}

// Warn logs a warning message.
func Warn() *zerolog.Event {
	return Log.Warn()
}

// Error logs an error message.
func Error() *zerolog.Event {
	return Log.Error()
}

// Fatal logs a fatal message and exits.
func Fatal() *zerolog.Event {
	return Log.Fatal()
}

// Trace logs a trace message.
func Trace() *zerolog.Event {
	return Log.Trace()
}

// WithComponent creates a child logger with a component field.
func WithComponent(component string) zerolog.Logger {
	return Log.With().Str("component", component).Logger()
}

// WithClientID creates a child logger with a client_id field.
func WithClientID(clientID string) zerolog.Logger {
	return Log.With().Str("client_id", clientID).Logger()
}

// WithTaskID creates a child logger with a task_id field.
func WithTaskID(taskID string) zerolog.Logger {
	return Log.With().Str("task_id", taskID).Logger()
}

// WithRequestID creates a child logger with a request_id field.
func WithRequestID(requestID string) zerolog.Logger {
	return Log.With().Str("request_id", requestID).Logger()
}

// LogFields is a helper type for structured logging.
type LogFields map[string]any

// WithFields creates a child logger with multiple fields.
func WithFields(fields LogFields) *ChainLogger {
	ctx := Log.With()
	for k, v := range fields {
		ctx = ctx.Interface(k, v)
	}
	return &ChainLogger{logger: ctx.Logger()}
}

// ChainLogger wraps zerolog.Logger with chainable With method.
type ChainLogger struct {
	logger zerolog.Logger
}

// Logger returns the underlying zerolog.Logger.
func (l *ChainLogger) Logger() zerolog.Logger {
	return l.logger
}

// With adds key-value pairs to the logger context and returns a new ChainLogger.
func (l *ChainLogger) With(keyvals ...any) *ChainLogger {
	ctx := l.logger.With()
	for i := 0; i < len(keyvals)-1; i += 2 {
		key, ok := keyvals[i].(string)
		if !ok {
			continue
		}
		ctx = ctx.Interface(key, keyvals[i+1])
	}
	return &ChainLogger{logger: ctx.Logger()}
}

// Zerolog-style event methods (returns *zerolog.Event for native API compatibility)

// Debug returns a zerolog debug event.
func (l *ChainLogger) Debug() *zerolog.Event {
	return l.logger.Debug()
}

// Info returns a zerolog info event.
func (l *ChainLogger) Info() *zerolog.Event {
	return l.logger.Info()
}

// Warn returns a zerolog warn event.
func (l *ChainLogger) Warn() *zerolog.Event {
	return l.logger.Warn()
}

// Error returns a zerolog error event.
func (l *ChainLogger) Error() *zerolog.Event {
	return l.logger.Error()
}

// Fatal returns a zerolog fatal event.
func (l *ChainLogger) Fatal() *zerolog.Event {
	return l.logger.Fatal()
}

// Trace returns a zerolog trace event.
func (l *ChainLogger) Trace() *zerolog.Event {
	return l.logger.Trace()
}
