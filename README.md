# TetraCore Hub

Centralized stream hub and task orchestration platform for microservices architecture.

## Features

- **Task Orchestration**: Route and coordinate tasks between bots and workers
- **WebSocket Support**: Real-time bidirectional communication
- **RBAC**: Role-based access control with fine-grained permissions
- **JWT Authentication**: Secure token-based authentication with refresh tokens
- **2FA/TOTP**: Two-factor authentication support
- **API Keys**: Scoped API key management
- **Redis Backend**: High-performance data storage with cluster/sentinel support
- **Plugin System**: Lua-based extensibility
- **Audit Logging**: Complete audit trail for compliance
- **Prometheus Metrics**: Built-in observability

## Quick Start

### Prerequisites

- Go 1.22+
- Redis 7+
- Make

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/tetra-core-hub.git
cd tetra-core-hub

# Install dependencies
make deps

# Copy environment configuration
cp .env.example .env

# Start Redis (if not running)
make redis-start

# Run in development mode
make dev
```

### Production Build

```bash
make build-prod
./build/tetracore-hub
```

### Docker

```bash
# Build and run with Docker Compose
make docker-compose-up

# Or build image manually
make docker-build
docker run -p 8000:8000 --env-file .env tetracore-hub:latest
```

## Configuration

Configuration is managed via environment variables and `config/config.yaml`.

Key environment variables:
- `APP_ENV` - Environment (development/production)
- `SERVER_PORT` - HTTP server port (default: 8000)
- `REDIS_ADDR` - Redis connection address
- `JWT_SECRET` - JWT signing secret
- `ADMIN_USERNAME` - Initial admin username
- `ADMIN_PASSWORD` - Initial admin password

## API Documentation

- OpenAPI spec: `api/openapi/openapi.yaml`
- Postman collection: `api/postman/`

### Main Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /auth/login` | User authentication |
| `POST /auth/logout` | Session termination |
| `GET /health` | Health check |
| `GET /stats` | System statistics |
| `WS /ws` | WebSocket connection |
| `/api/v1/clients` | Client management |
| `/api/v1/tasks` | Task operations |
| `/api/v1/sessions` | Session management |
| `/api/v1/users` | User management |
| `/api/v1/roles` | Role management |

## Architecture

```
cmd/
  hub/          # Main hub server
  tetra/        # CLI tool
  secret-scan/  # Security scanner
internal/
  domain/       # Business entities and interfaces
  usecase/      # Business logic
  delivery/     # HTTP and WebSocket handlers
  infrastructure/  # Redis, security, plugins
pkg/            # Shared utilities
sdk/go/         # Go client SDK
web/admin/      # Admin dashboard
```

## Development

```bash
# Run tests
make test

# Run tests with coverage
make test-coverage

# Lint code
make lint

# Format code
make fmt

# Generate Swagger docs
make swagger
```

## License

MIT
