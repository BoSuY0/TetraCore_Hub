//go:build integration
// +build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

type procHandle struct {
	name string
	cmd  *exec.Cmd
	logs *bytes.Buffer
}

func TestHubWorkerIntegration(t *testing.T) {
	if os.Getenv("TETRACORE_INTEGRATION") != "1" {
		t.Skip("інтеграційний тест вимкнено (встановіть TETRACORE_INTEGRATION=1)")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	waitForTCP(t, ctx, "127.0.0.1:16379", "Redis (docker-compose.test.yml)")
	waitForTCP(t, ctx, "127.0.0.1:13306", "MySQL (docker-compose.test.yml)")

	// Очистити Redis від залишків попередніх запусків (стале клієнти, задачі)
	flushTestRedis(t)

	hubRoot := projectRoot(t)
	workerRoot := filepath.Clean(filepath.Join(hubRoot, "..", "TetraCore_Worker"))

	hubBin := filepath.Join(t.TempDir(), "tetracore-hub")
	workerBin := filepath.Join(t.TempDir(), "tetracore-worker")

	buildBinary(t, hubRoot, "./cmd/hub", hubBin)
	buildBinary(t, workerRoot, "./cmd/worker", workerBin)

	hubPort := freePort(t)
	baseURL := fmt.Sprintf("http://127.0.0.1:%d", hubPort)
	wsURL := fmt.Sprintf("ws://127.0.0.1:%d/ws", hubPort)

	hubEnv := withEnv(os.Environ(), map[string]string{
		"ENVIRONMENT":     "testing",
		"HOST":            "127.0.0.1",
		"PORT":            fmt.Sprintf("%d", hubPort),
		"ADMIN_USERNAME":  "admin",
		"ADMIN_PASSWORD":  "admin123",
		"JWT_SECRET":      "test-secret",
		"JWT_ISSUER":      "tetracore-test",
		"REDIS_URL":       "redis://127.0.0.1:16379/0",
		"PLUGINS_ENABLED": "false",
		"LOG_LEVEL":       "info",
		"LOG_FORMAT":      "json",
	})

	hubProc := startProcess(t, "hub", hubBin, nil, hubEnv, hubRoot)
	defer stopProcess(t, hubProc)

	waitForHealth(t, ctx, baseURL+"/health")

	token := login(t, ctx, baseURL+"/auth/login", "admin", "admin123")

	// --- Real bot flow ---
	pythonBin := findPython(t)
	botRoot := filepath.Clean(filepath.Join(hubRoot, "..", "TetraCore_Bot"))

	botProc := startRealBot(t, pythonBin, botRoot, wsURL, token)
	defer stopProcess(t, botProc)

	waitForBots(t, ctx, baseURL+"/api/v1/clients/stats", token)
	verifyBotInClientsList(t, ctx, baseURL+"/api/v1/clients?type=bot", token)
	t.Logf("реальний бот успішно зареєстрований у Hub")

	workerEnv := withEnv(os.Environ(), map[string]string{
		"HUB_URL":    wsURL,
		"AUTH_TOKEN": token,
		"WORKER_ID":  "worker-test",
		"REDIS_URL":  "redis://127.0.0.1:16379/0",
		"MYSQL_DSN":  "tetra_test:tetra_test@tcp(127.0.0.1:13306)/tetracore_test?parseTime=true&multiStatements=true",
		"LOG_LEVEL":  "info",
		"LOG_FORMAT": "json",
	})

	workerCfg := filepath.Join(workerRoot, "config", "worker.yaml")
	workerArgs := []string{"-config", workerCfg, "-worker-id", "worker-test"}

	workerProc := startProcess(t, "worker", workerBin, workerArgs, workerEnv, workerRoot)
	defer stopProcess(t, workerProc)

	waitForWorkers(t, ctx, baseURL+"/api/v1/clients/stats", token)

	taskID := createTestTask(t, ctx, baseURL+"/api/v1/tasks", token)
	result := waitForTaskCompletion(t, ctx, baseURL+"/api/v1/tasks/"+taskID, token)

	if result.Status != "completed" {
		t.Fatalf("очікував статус completed, отримано %q (task_id=%s)", result.Status, taskID)
	}

	msg, _ := result.Result["message"].(string)
	if !strings.Contains(msg, "Test successful") {
		t.Fatalf("неочікуваний результат task_id=%s, message=%q", taskID, msg)
	}
}

func projectRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("не вдалося отримати робочу директорію: %v", err)
	}
	// test/integration -> test -> hub root
	return filepath.Clean(filepath.Join(dir, "..", ".."))
}

func buildBinary(t *testing.T, workDir, pkg, out string) {
	t.Helper()
	cmd := exec.Command("go", "build", "-o", out, pkg)
	cmd.Dir = workDir
	outBuf := &bytes.Buffer{}
	cmd.Stdout = outBuf
	cmd.Stderr = outBuf
	if err := cmd.Run(); err != nil {
		t.Fatalf("збірка %s не вдалася: %v\n%s", pkg, err, outBuf.String())
	}
}

func startProcess(t *testing.T, name, bin string, args, env []string, dir string) *procHandle {
	t.Helper()
	logs := &bytes.Buffer{}
	cmd := exec.Command(bin, args...)
	cmd.Env = env
	cmd.Dir = dir
	cmd.Stdout = logs
	cmd.Stderr = logs
	if err := cmd.Start(); err != nil {
		t.Fatalf("не вдалося запустити %s: %v", name, err)
	}
	return &procHandle{name: name, cmd: cmd, logs: logs}
}

func stopProcess(t *testing.T, p *procHandle) {
	t.Helper()
	if p == nil || p.cmd == nil || p.cmd.Process == nil {
		return
	}

	_ = p.cmd.Process.Signal(os.Interrupt)

	done := make(chan error, 1)
	go func() { done <- p.cmd.Wait() }()

	select {
	case <-time.After(20 * time.Second):
		_ = p.cmd.Process.Kill()
	case err := <-done:
		if err != nil && !errors.Is(err, os.ErrProcessDone) {
			t.Logf("процес %s завершився з помилкою: %v", p.name, err)
		}
	}

	if p.logs != nil && p.logs.Len() > 0 {
		t.Logf("логи %s:\n%s", p.name, p.logs.String())
	}
}

func flushTestRedis(t *testing.T) {
	t.Helper()
	cmd := exec.Command("redis-cli", "-p", "16379", "-n", "0", "FLUSHDB")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("не вдалося очистити test Redis: %v\n%s", err, out)
	}
	t.Logf("test Redis очищено: %s", strings.TrimSpace(string(out)))
}

func freePort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("не вдалося отримати вільний порт: %v", err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

func waitForTCP(t *testing.T, ctx context.Context, addr, label string) {
	t.Helper()
	deadline := time.NewTimer(30 * time.Second)
	defer deadline.Stop()

	for {
		select {
		case <-ctx.Done():
			t.Fatalf("таймаут очікування %s: %v", label, ctx.Err())
		case <-deadline.C:
			t.Fatalf("не вдалося під'єднатись до %s (%s)", label, addr)
		default:
			conn, err := net.DialTimeout("tcp", addr, 1*time.Second)
			if err == nil {
				_ = conn.Close()
				return
			}
			time.Sleep(500 * time.Millisecond)
		}
	}
}

func waitForHealth(t *testing.T, ctx context.Context, url string) {
	t.Helper()
	client := &http.Client{Timeout: 3 * time.Second}
	for {
		select {
		case <-ctx.Done():
			t.Fatalf("таймаут очікування health: %v", ctx.Err())
		default:
			resp, err := client.Get(url)
			if err == nil && resp != nil {
				var body struct {
					Status string `json:"status"`
				}
				_ = json.NewDecoder(resp.Body).Decode(&body)
				_ = resp.Body.Close()
				if resp.StatusCode == http.StatusOK && body.Status == "healthy" {
					return
				}
			}
			time.Sleep(500 * time.Millisecond)
		}
	}
}

func login(t *testing.T, ctx context.Context, url, username, password string) string {
	t.Helper()
	payload := map[string]string{
		"username": username,
		"password": password,
	}
	data, _ := json.Marshal(payload)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(data))
	if err != nil {
		t.Fatalf("не вдалося створити запит login: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("login запит не вдався: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("login повернув статус %d", resp.StatusCode)
	}

	var out struct {
		AccessToken string `json:"access_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("не вдалося розпарсити login response: %v", err)
	}
	if out.AccessToken == "" {
		t.Fatalf("порожній access_token у login response")
	}
	return out.AccessToken
}

func waitForWorkers(t *testing.T, ctx context.Context, url, token string) {
	t.Helper()
	client := &http.Client{Timeout: 5 * time.Second}

	for {
		select {
		case <-ctx.Done():
			t.Fatalf("таймаут очікування реєстрації воркера: %v", ctx.Err())
		default:
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
			if err != nil {
				t.Fatalf("не вдалося створити запит clients/stats: %v", err)
			}
			req.Header.Set("Authorization", "Bearer "+token)
			resp, err := client.Do(req)
			if err == nil && resp != nil {
				var stats struct {
					Workers int64 `json:"workers"`
				}
				_ = json.NewDecoder(resp.Body).Decode(&stats)
				_ = resp.Body.Close()
				if resp.StatusCode == http.StatusOK && stats.Workers > 0 {
					return
				}
			}
			time.Sleep(500 * time.Millisecond)
		}
	}
}

func createTestTask(t *testing.T, ctx context.Context, url, token string) string {
	t.Helper()
	body := map[string]any{
		"task_type":     "test_simple",
		"executor_type": "worker",
		"priority":      "normal",
		"data": map[string]any{
			"action": "test_simple",
			"params": map[string]any{
				"message": "ping",
			},
		},
		"timeout": 10,
	}
	data, _ := json.Marshal(body)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(data))
	if err != nil {
		t.Fatalf("не вдалося створити запит tasks: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("створення задачі не вдалося: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("створення задачі повернуло статус %d", resp.StatusCode)
	}

	var out struct {
		TaskID string `json:"task_id"`
		Status string `json:"status"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("не вдалося розпарсити відповідь задачі: %v", err)
	}
	if out.TaskID == "" {
		t.Fatalf("порожній task_id у відповіді")
	}
	return out.TaskID
}

type taskResult struct {
	Status string         `json:"status"`
	Result map[string]any `json:"result"`
}

func waitForTaskCompletion(t *testing.T, ctx context.Context, url, token string) taskResult {
	t.Helper()
	client := &http.Client{Timeout: 5 * time.Second}

	for {
		select {
		case <-ctx.Done():
			t.Fatalf("таймаут очікування завершення задачі: %v", ctx.Err())
		default:
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
			if err != nil {
				t.Fatalf("не вдалося створити запит задачі: %v", err)
			}
			req.Header.Set("Authorization", "Bearer "+token)
			resp, err := client.Do(req)
			if err == nil && resp != nil {
				if resp.StatusCode == http.StatusOK {
					var out taskResult
					if err := json.NewDecoder(resp.Body).Decode(&out); err == nil {
						_ = resp.Body.Close()
						if out.Status == "completed" || out.Status == "failed" || out.Status == "timeout" || out.Status == "cancelled" {
							return out
						}
					} else {
						_ = resp.Body.Close()
					}
				} else {
					_ = resp.Body.Close()
				}
			}
			time.Sleep(500 * time.Millisecond)
		}
	}
}

// findPython шукає Python 3 інтерпретатор: спочатку у проектному venv,
// потім у системі. Якщо не знайдено — тест пропускається.
func findPython(t *testing.T) string {
	t.Helper()

	// Проектний venv (пріоритет)
	hubRoot := projectRoot(t)
	venvPython := filepath.Join(hubRoot, "..", ".venv", "bin", "python3")
	if _, err := os.Stat(venvPython); err == nil {
		return venvPython
	}

	// Системний python3
	if p, err := exec.LookPath("python3"); err == nil {
		return p
	}

	t.Skip("Python 3 не знайдено — bot stub тест пропускається")
	return ""
}

// startRealBot запускає реальний TetraCore_Bot (python launcher.py --bot).
// Бот підключається до Hub як client_type="bot" та починає Telegram polling.
func startRealBot(t *testing.T, pythonBin, botRoot, wsURL, token string) *procHandle {
	t.Helper()

	logs := &bytes.Buffer{}
	cmd := exec.Command(pythonBin, "launcher.py", "--bot")
	cmd.Dir = botRoot
	cmd.Env = withEnv(os.Environ(), map[string]string{
		// Hub — підключаємо до тестового хаба
		"HUB_URL":           wsURL,
		"AUTH_TOKEN":        token,
		"AUTH_TOKEN_ACTIVE": token,
		"HUB_ENABLED":       "1",
		"HUB_REQUIRED":      "0",
		// Вимкнення subprotocol enforcement (тестовий Hub не підтримує bearer.hmac.v1)
		"HUB_ENFORCE_SUBPROTOCOL":                   "0",
		"HUB_ALLOW_INSECURE_SUBPROTOCOL_WITH_TOKEN": "1",
		// Redis — тестовий інстанс із docker-compose.test.yml
		"LOCAL_REDIS_URL": "redis://127.0.0.1:16379/0",
		"REDIS_URL":       "redis://127.0.0.1:16379/0",
		// БД — тестовий MySQL із docker-compose.test.yml
		"LOCAL_DATABASE_URL": "mysql+asyncmy://tetra_test:tetra_test@127.0.0.1:13306/tetracore_test?charset=utf8mb4",
		// Режим розробки
		"APP_MODE":         "development",
		"DEV_BYPASS":       "true",
		"HMAC_REQUIRED":    "false",
		"PYTHONUNBUFFERED": "1",
	})
	cmd.Stdout = io.MultiWriter(logs, os.Stdout)
	cmd.Stderr = io.MultiWriter(logs, os.Stderr)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	if err := cmd.Start(); err != nil {
		t.Fatalf("не вдалося запустити реальний бот: %v", err)
	}

	return &procHandle{name: "bot", cmd: cmd, logs: logs}
}

// waitForBots очікує поки хоча б один бот зареєструється у Hub (через /api/v1/clients/stats).
// Реальний бот стартує довше (DB міграції, компоненти, Telegram), тому таймаут 60с.
func waitForBots(t *testing.T, ctx context.Context, url, token string) {
	t.Helper()
	client := &http.Client{Timeout: 5 * time.Second}
	deadline := time.After(60 * time.Second)

	for {
		select {
		case <-ctx.Done():
			t.Fatalf("таймаут очікування реєстрації бота (context): %v", ctx.Err())
		case <-deadline:
			t.Fatalf("таймаут 30с очікування реєстрації бота через /api/v1/clients/stats")
		default:
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
			if err != nil {
				t.Fatalf("не вдалося створити запит clients/stats (бот): %v", err)
			}
			req.Header.Set("Authorization", "Bearer "+token)
			resp, err := client.Do(req)
			if err == nil && resp != nil {
				var stats struct {
					Bots int64 `json:"bots"`
				}
				_ = json.NewDecoder(resp.Body).Decode(&stats)
				_ = resp.Body.Close()
				if resp.StatusCode == http.StatusOK && stats.Bots > 0 {
					t.Logf("бот з'явився у stats: bots=%d", stats.Bots)
					return
				}
			}
			time.Sleep(500 * time.Millisecond)
		}
	}
}

// verifyBotInClientsList перевіряє наявність клієнта з client_type="bot" у списку.
// Реальний бот генерує рандомний client_id виду "tetracore_bot_<hex8>".
func verifyBotInClientsList(t *testing.T, ctx context.Context, url, token string) {
	t.Helper()
	client := &http.Client{Timeout: 5 * time.Second}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		t.Fatalf("не вдалося створити запит clients?type=bot: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("запит clients?type=bot не вдався: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("clients?type=bot повернув статус %d", resp.StatusCode)
	}

	var out struct {
		Clients []struct {
			ClientID   string `json:"client_id"`
			ClientType string `json:"client_type"`
			ClientName string `json:"client_name"`
		} `json:"clients"`
		Total int `json:"total"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("не вдалося розпарсити відповідь clients?type=bot: %v", err)
	}

	if out.Total == 0 || len(out.Clients) == 0 {
		t.Fatalf("clients?type=bot повернув 0 клієнтів, очікувався хоча б 1")
	}

	// Перевіряємо що є хоча б один бот з client_type="bot"
	found := false
	for _, c := range out.Clients {
		if c.ClientType == "bot" {
			t.Logf("знайдено бота: client_id=%s, client_name=%s", c.ClientID, c.ClientName)
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("жоден клієнт у списку не має client_type=\"bot\"; отримано %d клієнтів", len(out.Clients))
	}
}

func withEnv(base []string, overrides map[string]string) []string {
	out := make([]string, 0, len(base)+len(overrides))
	seen := make(map[string]struct{}, len(overrides))
	for k := range overrides {
		seen[k] = struct{}{}
	}
	for _, kv := range base {
		key := kv
		if idx := strings.Index(kv, "="); idx != -1 {
			key = kv[:idx]
		}
		if _, ok := seen[key]; ok {
			continue
		}
		out = append(out, kv)
	}
	for k, v := range overrides {
		out = append(out, k+"="+v)
	}
	return out
}
