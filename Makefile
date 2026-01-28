.PHONY: build run test clean deps lint fmt swagger redis-start redis-stop docker-compose-up docker-compose-down install-tools

# Binary name
BINARY_NAME=tetracore-hub

# Go parameters
GOCMD=go
GOBUILD=$(GOCMD) build
GORUN=$(GOCMD) run
GOTEST=$(GOCMD) test
GOGET=$(GOCMD) get
GOMOD=$(GOCMD) mod
GOFMT=gofmt

# Build directory
BUILD_DIR=./build

# Main file
MAIN_FILE=./cmd/hub/main.go

# Version info
VERSION=$(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
BUILD_TIME=$(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
LDFLAGS=-ldflags "-X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME)"

# Default target
all: deps build

# Build the binary
build:
	@echo "Building $(BINARY_NAME)..."
	@mkdir -p $(BUILD_DIR)
	$(GOBUILD) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY_NAME) $(MAIN_FILE)
	@echo "Build complete: $(BUILD_DIR)/$(BINARY_NAME)"

# Build for production (optimized)
build-prod:
	@echo "Building $(BINARY_NAME) for production..."
	@mkdir -p $(BUILD_DIR)
	CGO_ENABLED=0 $(GOBUILD) $(LDFLAGS) -trimpath -ldflags "-s -w" -o $(BUILD_DIR)/$(BINARY_NAME) $(MAIN_FILE)
	@echo "Production build complete: $(BUILD_DIR)/$(BINARY_NAME)"

# Run the application
run:
	@echo "Running $(BINARY_NAME)..."
	$(GORUN) $(MAIN_FILE)

# Run with hot reload (requires air)
dev:
	@if command -v air > /dev/null; then \
		air; \
	else \
		echo "Installing air..."; \
		go install github.com/cosmtrek/air@latest; \
		air; \
	fi

# Run tests
test:
	@echo "Running tests..."
	$(GOTEST) -v -race -cover ./...

# Run tests with coverage report
test-coverage:
	@echo "Running tests with coverage..."
	$(GOTEST) -v -race -coverprofile=coverage.out ./...
	$(GOCMD) tool cover -html=coverage.out -o coverage.html
	@echo "Coverage report: coverage.html"

# Run benchmarks
bench:
	@echo "Running benchmarks..."
	$(GOTEST) -bench=. -benchmem ./...

# Clean build artifacts
clean:
	@echo "Cleaning..."
	@rm -rf $(BUILD_DIR)
	@rm -f coverage.out coverage.html
	@echo "Clean complete"

# Download dependencies
deps:
	@echo "Downloading dependencies..."
	$(GOMOD) download
	$(GOMOD) tidy
	@echo "Dependencies updated"

# Verify dependencies
verify:
	@echo "Verifying dependencies..."
	$(GOMOD) verify
	@echo "Dependencies verified"

# Format code
fmt:
	@echo "Formatting code..."
	$(GOFMT) -s -w .
	@echo "Formatting complete"

# Lint code (requires golangci-lint)
lint:
	@if command -v golangci-lint > /dev/null; then \
		golangci-lint run ./...; \
	else \
		echo "golangci-lint not installed. Run: go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest"; \
	fi

# Generate code (if needed)
generate:
	@echo "Generating code..."
	$(GOCMD) generate ./...
	@echo "Generation complete"

# Docker build
docker-build:
	@echo "Building Docker image..."
	docker build -t $(BINARY_NAME):$(VERSION) .
	@echo "Docker build complete"

# Docker run
docker-run:
	@echo "Running Docker container..."
	docker run --rm -p 8000:8000 --env-file .env $(BINARY_NAME):$(VERSION)

# Swagger docs generation
swagger:
	@if command -v swag > /dev/null; then \
		swag init -g cmd/hub/main.go -o docs; \
	else \
		echo "Installing swag..."; \
		go install github.com/swaggo/swag/cmd/swag@latest; \
		swag init -g cmd/hub/main.go -o docs; \
	fi

# Redis management
redis-start:
	@echo "Starting Redis..."
	@redis-server --daemonize yes
	@echo "Redis started on localhost:6379"

redis-stop:
	@echo "Stopping Redis..."
	@redis-cli shutdown || true
	@echo "Redis stopped"

# Docker Compose
docker-compose-up:
	docker-compose up -d

docker-compose-down:
	docker-compose down

# Install development tools
install-tools:
	@echo "Installing development tools..."
	go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
	go install github.com/cosmtrek/air@latest
	go install github.com/swaggo/swag/cmd/swag@latest
	@echo "Tools installed"

# Help
help:
	@echo "TetraCore Hub - Makefile Commands"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  all            - Download deps and build (default)"
	@echo "  build          - Build the binary"
	@echo "  build-prod     - Build optimized production binary"
	@echo "  run            - Run the application"
	@echo "  dev            - Run with hot reload"
	@echo "  test           - Run tests"
	@echo "  test-coverage  - Run tests with coverage report"
	@echo "  bench          - Run benchmarks"
	@echo "  clean          - Clean build artifacts"
	@echo "  deps           - Download dependencies"
	@echo "  verify         - Verify dependencies"
	@echo "  fmt            - Format code"
	@echo "  lint           - Lint code"
	@echo "  generate       - Generate code"
	@echo "  swagger        - Generate Swagger docs"
	@echo "  redis-start    - Start Redis server"
	@echo "  redis-stop     - Stop Redis server"
	@echo "  docker-build   - Build Docker image"
	@echo "  docker-run     - Run Docker container"
	@echo "  docker-compose-up   - Start with docker-compose"
	@echo "  docker-compose-down - Stop docker-compose"
	@echo "  install-tools  - Install dev tools"
	@echo "  help           - Show this help message"
