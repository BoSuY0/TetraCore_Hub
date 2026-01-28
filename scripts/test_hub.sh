#!/bin/bash
# TetraCore Hub Manual Test Script
# Запуск: ./scripts/test_hub.sh

set -e

BASE_URL="${HUB_URL:-http://localhost:8000}"
TOKEN=""

echo "========================================"
echo "  TetraCore Hub Manual Test Script"
echo "========================================"
echo "Base URL: $BASE_URL"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}✓ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}"; }

# 1. Health Check
echo "1. Testing Health Endpoint..."
HEALTH=$(curl -s "$BASE_URL/health")
if echo "$HEALTH" | grep -q "healthy"; then
    pass "Health check passed"
    echo "   Response: $HEALTH"
else
    fail "Health check failed"
    echo "   Response: $HEALTH"
fi
echo ""

# 2. Login
echo "2. Testing Login..."
LOGIN_RESP=$(curl -s -X POST "$BASE_URL/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}')

TOKEN=$(echo "$LOGIN_RESP" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
if [ -n "$TOKEN" ]; then
    pass "Login successful"
    echo "   Token: ${TOKEN:0:50}..."
else
    fail "Login failed"
    echo "   Response: $LOGIN_RESP"
    echo ""
    echo "Note: Make sure you set ADMIN_USERNAME and ADMIN_PASSWORD environment variables"
    echo "      or use the default credentials configured in your .env file"
    exit 1
fi
echo ""

# 3. Verify Token
echo "3. Verifying Token..."
VERIFY_RESP=$(curl -s "$BASE_URL/api/v1/auth/verify" \
    -H "Authorization: Bearer $TOKEN")
if echo "$VERIFY_RESP" | grep -q "true\|valid"; then
    pass "Token verification passed"
else
    fail "Token verification failed"
    echo "   Response: $VERIFY_RESP"
fi
echo ""

# 4. List Clients
echo "4. Testing Clients Endpoint..."
CLIENTS_RESP=$(curl -s "$BASE_URL/api/v1/clients" \
    -H "Authorization: Bearer $TOKEN")
pass "Clients endpoint responded"
echo "   Response: ${CLIENTS_RESP:0:200}..."
echo ""

# 5. Get Client Stats
echo "5. Testing Client Stats..."
STATS_RESP=$(curl -s "$BASE_URL/api/v1/clients/stats" \
    -H "Authorization: Bearer $TOKEN")
pass "Stats endpoint responded"
echo "   Response: $STATS_RESP"
echo ""

# 6. Submit Task
echo "6. Testing Task Submission..."
TASK_RESP=$(curl -s -X POST "$BASE_URL/api/v1/tasks" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "task_type": "api_request",
        "executor_type": "worker",
        "priority": "normal",
        "payload": {"url": "https://api.example.com", "method": "GET"}
    }')
TASK_ID=$(echo "$TASK_RESP" | grep -o '"task_id":"[^"]*"' | cut -d'"' -f4)
if [ -n "$TASK_ID" ]; then
    pass "Task submitted: $TASK_ID"
else
    fail "Task submission failed"
    echo "   Response: $TASK_RESP"
fi
echo ""

# 7. Get Task
if [ -n "$TASK_ID" ]; then
    echo "7. Testing Get Task..."
    GET_TASK=$(curl -s "$BASE_URL/api/v1/tasks/$TASK_ID" \
        -H "Authorization: Bearer $TOKEN")
    pass "Task retrieved"
    echo "   Response: ${GET_TASK:0:200}..."
    echo ""

    # 8. Cancel Task
    echo "8. Testing Task Cancellation..."
    CANCEL_RESP=$(curl -s -X POST "$BASE_URL/api/v1/tasks/$TASK_ID/cancel" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"reason": "test cancellation"}')
    pass "Task cancellation requested"
    echo "   Response: $CANCEL_RESP"
    echo ""
fi

# 9. List Tasks
echo "9. Testing List Tasks..."
TASKS_RESP=$(curl -s "$BASE_URL/api/v1/tasks" \
    -H "Authorization: Bearer $TOKEN")
pass "Tasks listed"
echo "   Response: ${TASKS_RESP:0:200}..."
echo ""

# 10. Get Sessions
echo "10. Testing Sessions Endpoint..."
SESSIONS_RESP=$(curl -s "$BASE_URL/api/v1/sessions" \
    -H "Authorization: Bearer $TOKEN")
pass "Sessions endpoint responded"
echo "   Response: ${SESSIONS_RESP:0:200}..."
echo ""

echo "========================================"
echo "  Test Complete!"
echo "========================================"
echo ""
echo "WebSocket test (manual):"
echo "  wscat -c '$BASE_URL/ws?token=$TOKEN'"
echo ""
