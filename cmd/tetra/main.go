// Package main provides the CLI tool for TetraCore Hub.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"text/tabwriter"
	"time"
)

var (
	Version = "dev"
	baseURL = "http://localhost:8000"
	token   = ""
)

func main() {
	// Load config
	if url := os.Getenv("TETRA_URL"); url != "" {
		baseURL = url
	}
	if t := os.Getenv("TETRA_TOKEN"); t != "" {
		token = t
	}

	// Load token from file
	if token == "" {
		if data, err := os.ReadFile(tokenFile()); err == nil {
			token = strings.TrimSpace(string(data))
		}
	}

	if len(os.Args) < 2 {
		printHelp()
		os.Exit(0)
	}

	cmd := os.Args[1]
	args := os.Args[2:]

	switch cmd {
	case "login":
		cmdLogin(args)
	case "logout":
		cmdLogout()
	case "clients":
		cmdClients(args)
	case "tasks":
		cmdTasks(args)
	case "sessions":
		cmdSessions(args)
	case "stats":
		cmdStats()
	case "health":
		cmdHealth()
	case "version":
		fmt.Printf("tetra version %s\n", Version)
	case "help", "-h", "--help":
		printHelp()
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmd)
		os.Exit(1)
	}
}

func printHelp() {
	fmt.Println(`TetraCore Hub CLI

Usage: tetra <command> [arguments]

Commands:
  login <username> <password>   Authenticate with the hub
  logout                        Clear saved credentials

  clients list                  List all clients
  clients stats                 Show client statistics
  clients disconnect <id>       Disconnect a client

  tasks list [--status <s>]     List tasks
  tasks stats                   Show task statistics
  tasks create <type> <json>    Create a new task
  tasks get <id>                Get task details
  tasks cancel <id>             Cancel a task

  sessions list                 List all sessions
  sessions stats                Show session statistics
  sessions delete <id>          Delete a session

  stats                         Show hub statistics
  health                        Check hub health
  version                       Show CLI version

Environment:
  TETRA_URL     Hub URL (default: http://localhost:8000)
  TETRA_TOKEN   Authentication token`)
}

func tokenFile() string {
	home, _ := os.UserHomeDir()
	return home + "/.tetra_token"
}

func cmdLogin(args []string) {
	if len(args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: tetra login <username> <password>")
		os.Exit(1)
	}

	body := map[string]string{"username": args[0], "password": args[1]}
	resp, err := doRequest("POST", "/auth/login", body, false)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	if resp["error"] != nil {
		fmt.Fprintf(os.Stderr, "Login failed: %v\n", resp["message"])
		os.Exit(1)
	}

	token = resp["access_token"].(string)
	os.WriteFile(tokenFile(), []byte(token), 0600)
	fmt.Println("Login successful. Token saved.")
}

func cmdLogout() {
	if token != "" {
		doRequest("POST", "/auth/logout", nil, true)
	}
	os.Remove(tokenFile())
	fmt.Println("Logged out.")
}

func cmdClients(args []string) {
	if len(args) == 0 {
		args = []string{"list"}
	}

	switch args[0] {
	case "list":
		resp, err := doRequest("GET", "/api/v1/clients", nil, true)
		if err != nil {
			fatal(err)
		}
		printClients(resp)

	case "stats":
		resp, err := doRequest("GET", "/api/v1/clients/stats", nil, true)
		if err != nil {
			fatal(err)
		}
		printJSON(resp)

	case "disconnect":
		if len(args) < 2 {
			fmt.Fprintln(os.Stderr, "Usage: tetra clients disconnect <id>")
			os.Exit(1)
		}
		_, err := doRequest("POST", "/api/v1/clients/"+args[1]+"/disconnect", nil, true)
		if err != nil {
			fatal(err)
		}
		fmt.Println("Client disconnected.")

	default:
		fmt.Fprintf(os.Stderr, "Unknown subcommand: clients %s\n", args[0])
	}
}

func cmdTasks(args []string) {
	if len(args) == 0 {
		args = []string{"list"}
	}

	switch args[0] {
	case "list":
		path := "/api/v1/tasks"
		for i, arg := range args[1:] {
			if arg == "--status" && i+2 < len(args) {
				path += "?status=" + args[i+2]
				break
			}
		}
		resp, err := doRequest("GET", path, nil, true)
		if err != nil {
			fatal(err)
		}
		printTasks(resp)

	case "stats":
		resp, err := doRequest("GET", "/api/v1/tasks/stats", nil, true)
		if err != nil {
			fatal(err)
		}
		printJSON(resp)

	case "create":
		if len(args) < 3 {
			fmt.Fprintln(os.Stderr, "Usage: tetra tasks create <type> <payload_json>")
			os.Exit(1)
		}
		var payload map[string]any
		json.Unmarshal([]byte(args[2]), &payload)
		body := map[string]any{"task_type": args[1], "payload": payload}
		resp, err := doRequest("POST", "/api/v1/tasks", body, true)
		if err != nil {
			fatal(err)
		}
		printJSON(resp)

	case "get":
		if len(args) < 2 {
			fmt.Fprintln(os.Stderr, "Usage: tetra tasks get <id>")
			os.Exit(1)
		}
		resp, err := doRequest("GET", "/api/v1/tasks/"+args[1], nil, true)
		if err != nil {
			fatal(err)
		}
		printJSON(resp)

	case "cancel":
		if len(args) < 2 {
			fmt.Fprintln(os.Stderr, "Usage: tetra tasks cancel <id>")
			os.Exit(1)
		}
		_, err := doRequest("DELETE", "/api/v1/tasks/"+args[1], nil, true)
		if err != nil {
			fatal(err)
		}
		fmt.Println("Task cancelled.")

	default:
		fmt.Fprintf(os.Stderr, "Unknown subcommand: tasks %s\n", args[0])
	}
}

func cmdSessions(args []string) {
	if len(args) == 0 {
		args = []string{"list"}
	}

	switch args[0] {
	case "list":
		resp, err := doRequest("GET", "/api/v1/sessions", nil, true)
		if err != nil {
			fatal(err)
		}
		printSessions(resp)

	case "stats":
		resp, err := doRequest("GET", "/api/v1/sessions/stats", nil, true)
		if err != nil {
			fatal(err)
		}
		printJSON(resp)

	case "delete":
		if len(args) < 2 {
			fmt.Fprintln(os.Stderr, "Usage: tetra sessions delete <id>")
			os.Exit(1)
		}
		_, err := doRequest("DELETE", "/api/v1/sessions/"+args[1], nil, true)
		if err != nil {
			fatal(err)
		}
		fmt.Println("Session deleted.")

	default:
		fmt.Fprintf(os.Stderr, "Unknown subcommand: sessions %s\n", args[0])
	}
}

func cmdStats() {
	resp, err := doRequest("GET", "/stats", nil, false)
	if err != nil {
		fatal(err)
	}
	printJSON(resp)
}

func cmdHealth() {
	resp, err := doRequest("GET", "/health", nil, false)
	if err != nil {
		fatal(err)
	}
	if status, ok := resp["status"].(string); ok && status == "healthy" {
		fmt.Println("Hub is healthy")
	} else {
		fmt.Println("Hub is unhealthy")
		os.Exit(1)
	}
}

func doRequest(method, path string, body any, auth bool) (map[string]any, error) {
	var bodyReader io.Reader
	if body != nil {
		data, _ := json.Marshal(body)
		bodyReader = bytes.NewReader(data)
	}

	req, err := http.NewRequest(method, baseURL+path, bodyReader)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	if auth && token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var result map[string]any
	json.NewDecoder(resp.Body).Decode(&result)

	if resp.StatusCode == 401 {
		return nil, fmt.Errorf("unauthorized - please login first")
	}

	return result, nil
}

func printClients(resp map[string]any) {
	clients, ok := resp["clients"].([]any)
	if !ok || len(clients) == 0 {
		fmt.Println("No clients found.")
		return
	}

	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(w, "ID\tTYPE\tSTATUS\tCONNECTED")
	for _, c := range clients {
		cl := c.(map[string]any)
		id := truncate(str(cl["client_id"]), 12)
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", id, str(cl["type"]), str(cl["status"]), str(cl["connected_at"]))
	}
	w.Flush()
}

func printTasks(resp map[string]any) {
	tasks, ok := resp["tasks"].([]any)
	if !ok || len(tasks) == 0 {
		fmt.Println("No tasks found.")
		return
	}

	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(w, "ID\tTYPE\tSTATUS\tPRIORITY\tCREATED")
	for _, t := range tasks {
		task := t.(map[string]any)
		id := truncate(str(task["task_id"]), 12)
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\n", id, str(task["task_type"]), str(task["status"]), str(task["priority"]), str(task["created_at"]))
	}
	w.Flush()
}

func printSessions(resp map[string]any) {
	sessions, ok := resp["sessions"].([]any)
	if !ok || len(sessions) == 0 {
		fmt.Println("No sessions found.")
		return
	}

	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(w, "ID\tUSER\tROLE\tCREATED\tEXPIRES")
	for _, s := range sessions {
		sess := s.(map[string]any)
		id := truncate(str(sess["session_id"]), 12)
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\n", id, str(sess["username"]), str(sess["role"]), str(sess["created_at"]), str(sess["expires_at"]))
	}
	w.Flush()
}

func printJSON(data map[string]any) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	enc.Encode(data)
}

func str(v any) string {
	if v == nil {
		return "-"
	}
	return fmt.Sprintf("%v", v)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}

func fatal(err error) {
	fmt.Fprintf(os.Stderr, "Error: %v\n", err)
	os.Exit(1)
}
