// Package main provides a secret scanning tool for TetraCore Hub.
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// SecretPattern defines a pattern for detecting secrets.
type SecretPattern struct {
	Name        string
	Pattern     *regexp.Regexp
	Severity    string // critical, high, medium, low
	Description string
}

// Finding represents a detected secret.
type Finding struct {
	File        string `json:"file"`
	Line        int    `json:"line"`
	PatternName string `json:"pattern_name"`
	Severity    string `json:"severity"`
	Match       string `json:"match"`
	Context     string `json:"context,omitempty"`
}

// ScanResult holds the complete scan results.
type ScanResult struct {
	TotalFiles   int       `json:"total_files"`
	TotalLines   int       `json:"total_lines"`
	Findings     []Finding `json:"findings"`
	ScanDuration string    `json:"scan_duration"`
}

var patterns = []SecretPattern{
	// AWS
	{
		Name:        "AWS Access Key ID",
		Pattern:     regexp.MustCompile(`(?i)(AKIA|A3T|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}`),
		Severity:    "critical",
		Description: "AWS Access Key ID",
	},
	{
		Name:        "AWS Secret Access Key",
		Pattern:     regexp.MustCompile(`(?i)aws_secret_access_key\s*[=:]\s*['"]?([A-Za-z0-9/+=]{40})['"]?`),
		Severity:    "critical",
		Description: "AWS Secret Access Key",
	},
	// GitHub
	{
		Name:        "GitHub Token",
		Pattern:     regexp.MustCompile(`(?i)(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}|gho_[a-zA-Z0-9]{36}|ghu_[a-zA-Z0-9]{36}|ghs_[a-zA-Z0-9]{36}|ghr_[a-zA-Z0-9]{36})`),
		Severity:    "critical",
		Description: "GitHub Personal Access Token",
	},
	// GitLab
	{
		Name:        "GitLab Token",
		Pattern:     regexp.MustCompile(`glpat-[a-zA-Z0-9_-]{20}`),
		Severity:    "critical",
		Description: "GitLab Personal Access Token",
	},
	// Slack
	{
		Name:        "Slack Token",
		Pattern:     regexp.MustCompile(`xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*`),
		Severity:    "high",
		Description: "Slack API Token",
	},
	{
		Name:        "Slack Webhook",
		Pattern:     regexp.MustCompile(`https://hooks\.slack\.com/services/T[A-Z0-9]{8,}/B[A-Z0-9]{8,}/[a-zA-Z0-9]{24}`),
		Severity:    "high",
		Description: "Slack Webhook URL",
	},
	// Stripe
	{
		Name:        "Stripe API Key",
		Pattern:     regexp.MustCompile(`(?i)(sk_live_|rk_live_)[a-zA-Z0-9]{24,}`),
		Severity:    "critical",
		Description: "Stripe Live API Key",
	},
	{
		Name:        "Stripe Test Key",
		Pattern:     regexp.MustCompile(`(?i)(sk_test_|rk_test_)[a-zA-Z0-9]{24,}`),
		Severity:    "medium",
		Description: "Stripe Test API Key",
	},
	// Google
	{
		Name:        "Google API Key",
		Pattern:     regexp.MustCompile(`AIza[0-9A-Za-z_-]{35}`),
		Severity:    "high",
		Description: "Google API Key",
	},
	{
		Name:        "Google OAuth ID",
		Pattern:     regexp.MustCompile(`[0-9]+-[a-z0-9_]{32}\.apps\.googleusercontent\.com`),
		Severity:    "medium",
		Description: "Google OAuth Client ID",
	},
	// Telegram
	{
		Name:        "Telegram Bot Token",
		Pattern:     regexp.MustCompile(`[0-9]{9,10}:[a-zA-Z0-9_-]{35}`),
		Severity:    "high",
		Description: "Telegram Bot Token",
	},
	// Generic patterns
	{
		Name:        "Private Key",
		Pattern:     regexp.MustCompile(`-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----`),
		Severity:    "critical",
		Description: "Private Key Header",
	},
	{
		Name:        "JWT Token",
		Pattern:     regexp.MustCompile(`eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*`),
		Severity:    "high",
		Description: "JSON Web Token",
	},
	{
		Name:        "Generic API Key",
		Pattern:     regexp.MustCompile(`(?i)(api[_-]?key|apikey)\s*[=:]\s*['"]?([a-zA-Z0-9]{32,})['"]?`),
		Severity:    "medium",
		Description: "Generic API Key Pattern",
	},
	{
		Name:        "Generic Secret",
		Pattern:     regexp.MustCompile(`(?i)(secret|password|passwd|pwd)\s*[=:]\s*['"]([^'"]{8,})['"]`),
		Severity:    "medium",
		Description: "Generic Secret/Password Assignment",
	},
	{
		Name:        "Bearer Token",
		Pattern:     regexp.MustCompile(`(?i)bearer\s+[a-zA-Z0-9_-]{20,}`),
		Severity:    "high",
		Description: "Bearer Token in Header",
	},
	// Database
	{
		Name:        "Database URL",
		Pattern:     regexp.MustCompile(`(?i)(postgres|mysql|mongodb|redis)://[^:\s]+:[^@\s]+@[^\s]+`),
		Severity:    "critical",
		Description: "Database Connection URL with Credentials",
	},
	// Heroku
	{
		Name:        "Heroku API Key",
		Pattern:     regexp.MustCompile(`(?i)heroku.*[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}`),
		Severity:    "high",
		Description: "Heroku API Key",
	},
}

var excludeDirs = map[string]bool{
	".git":         true,
	".venv":        true,
	"venv":         true,
	"node_modules": true,
	"__pycache__":  true,
	".pytest_cache": true,
	"vendor":       true,
	".idea":        true,
	".vscode":      true,
	"build":        true,
	"dist":         true,
}

var excludeExtensions = map[string]bool{
	".exe":  true,
	".dll":  true,
	".so":   true,
	".dylib": true,
	".bin":  true,
	".png":  true,
	".jpg":  true,
	".jpeg": true,
	".gif":  true,
	".ico":  true,
	".pdf":  true,
	".zip":  true,
	".tar":  true,
	".gz":   true,
}

func main() {
	// Parse flags
	dir := flag.String("dir", ".", "Directory to scan")
	outputJSON := flag.Bool("json", false, "Output as JSON")
	outputFile := flag.String("output", "", "Output file (default: stdout)")
	minSeverity := flag.String("severity", "low", "Minimum severity to report (low, medium, high, critical)")
	entropyCheck := flag.Bool("entropy", false, "Enable entropy-based detection")
	entropyThreshold := flag.Float64("entropy-threshold", 4.5, "Entropy threshold for detection")
	ignoreFile := flag.String("ignore", ".secret-scan-ignore", "Ignore rules file")
	failOnFind := flag.Bool("fail-on-find", false, "Exit with code 1 if secrets found")
	flag.Parse()

	// Load ignore rules
	ignoreRules := loadIgnoreRules(*ignoreFile)

	// Scan
	result := scan(*dir, *minSeverity, *entropyCheck, *entropyThreshold, ignoreRules)

	// Output
	var output string
	if *outputJSON {
		data, _ := json.MarshalIndent(result, "", "  ")
		output = string(data)
	} else {
		output = formatTextOutput(result)
	}

	if *outputFile != "" {
		if err := os.WriteFile(*outputFile, []byte(output), 0644); err != nil {
			fmt.Fprintf(os.Stderr, "Error writing to file: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Results written to %s\n", *outputFile)
	} else {
		fmt.Println(output)
	}

	// Exit code
	if *failOnFind && len(result.Findings) > 0 {
		os.Exit(1)
	}
}

func scan(dir, minSeverity string, entropyCheck bool, entropyThreshold float64, ignoreRules []*regexp.Regexp) ScanResult {
	result := ScanResult{
		Findings: []Finding{},
	}

	severityLevel := severityToLevel(minSeverity)

	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}

		// Skip excluded directories
		if d.IsDir() {
			if excludeDirs[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}

		// Skip excluded extensions
		ext := strings.ToLower(filepath.Ext(path))
		if excludeExtensions[ext] {
			return nil
		}

		// Scan file
		findings := scanFile(path, severityLevel, entropyCheck, entropyThreshold, ignoreRules)
		result.Findings = append(result.Findings, findings...)
		result.TotalFiles++

		return nil
	})

	if err != nil {
		fmt.Fprintf(os.Stderr, "Error scanning: %v\n", err)
	}

	return result
}

func scanFile(path string, minLevel int, entropyCheck bool, entropyThreshold float64, ignoreRules []*regexp.Regexp) []Finding {
	var findings []Finding

	file, err := os.Open(path)
	if err != nil {
		return findings
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	lineNum := 0

	for scanner.Scan() {
		lineNum++
		line := scanner.Text()

		// Check against patterns
		for _, pattern := range patterns {
			if severityToLevel(pattern.Severity) < minLevel {
				continue
			}

			if matches := pattern.Pattern.FindAllString(line, -1); len(matches) > 0 {
				for _, match := range matches {
					// Check ignore rules
					if isIgnored(line, ignoreRules) {
						continue
					}

					findings = append(findings, Finding{
						File:        path,
						Line:        lineNum,
						PatternName: pattern.Name,
						Severity:    pattern.Severity,
						Match:       maskSecret(match),
						Context:     truncateLine(line, 100),
					})
				}
			}
		}

		// Entropy check
		if entropyCheck {
			words := extractPotentialSecrets(line)
			for _, word := range words {
				entropy := calculateEntropy(word)
				if entropy >= entropyThreshold && len(word) >= 16 {
					if isIgnored(line, ignoreRules) {
						continue
					}

					findings = append(findings, Finding{
						File:        path,
						Line:        lineNum,
						PatternName: "High Entropy String",
						Severity:    "medium",
						Match:       maskSecret(word),
						Context:     fmt.Sprintf("Entropy: %.2f", entropy),
					})
				}
			}
		}
	}

	return findings
}

func calculateEntropy(s string) float64 {
	if len(s) == 0 {
		return 0
	}

	freq := make(map[rune]int)
	for _, c := range s {
		freq[c]++
	}

	var entropy float64
	length := float64(len(s))

	for _, count := range freq {
		p := float64(count) / length
		entropy -= p * math.Log2(p)
	}

	return entropy
}

func extractPotentialSecrets(line string) []string {
	// Extract potential secret strings (alphanumeric with special chars)
	re := regexp.MustCompile(`['"]([a-zA-Z0-9+/=_-]{16,})['"]`)
	matches := re.FindAllStringSubmatch(line, -1)

	var result []string
	for _, m := range matches {
		if len(m) > 1 {
			result = append(result, m[1])
		}
	}
	return result
}

func maskSecret(s string) string {
	if len(s) <= 8 {
		return strings.Repeat("*", len(s))
	}
	return s[:4] + strings.Repeat("*", len(s)-8) + s[len(s)-4:]
}

func truncateLine(s string, maxLen int) string {
	s = strings.TrimSpace(s)
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

func severityToLevel(severity string) int {
	switch strings.ToLower(severity) {
	case "critical":
		return 4
	case "high":
		return 3
	case "medium":
		return 2
	case "low":
		return 1
	default:
		return 0
	}
}

func loadIgnoreRules(path string) []*regexp.Regexp {
	var rules []*regexp.Regexp

	file, err := os.Open(path)
	if err != nil {
		return rules
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		if re, err := regexp.Compile(line); err == nil {
			rules = append(rules, re)
		}
	}

	return rules
}

func isIgnored(line string, rules []*regexp.Regexp) bool {
	for _, rule := range rules {
		if rule.MatchString(line) {
			return true
		}
	}
	return false
}

func formatTextOutput(result ScanResult) string {
	var sb strings.Builder

	sb.WriteString("=== Secret Scan Results ===\n\n")
	sb.WriteString(fmt.Sprintf("Files scanned: %d\n", result.TotalFiles))
	sb.WriteString(fmt.Sprintf("Secrets found: %d\n\n", len(result.Findings)))

	if len(result.Findings) == 0 {
		sb.WriteString("No secrets detected.\n")
		return sb.String()
	}

	// Group by severity
	bySeverity := map[string][]Finding{
		"critical": {},
		"high":     {},
		"medium":   {},
		"low":      {},
	}

	for _, f := range result.Findings {
		bySeverity[f.Severity] = append(bySeverity[f.Severity], f)
	}

	for _, sev := range []string{"critical", "high", "medium", "low"} {
		findings := bySeverity[sev]
		if len(findings) == 0 {
			continue
		}

		sb.WriteString(fmt.Sprintf("--- %s (%d) ---\n", strings.ToUpper(sev), len(findings)))
		for _, f := range findings {
			sb.WriteString(fmt.Sprintf("  %s:%d\n", f.File, f.Line))
			sb.WriteString(fmt.Sprintf("    Pattern: %s\n", f.PatternName))
			sb.WriteString(fmt.Sprintf("    Match: %s\n", f.Match))
			if f.Context != "" {
				sb.WriteString(fmt.Sprintf("    Context: %s\n", f.Context))
			}
			sb.WriteString("\n")
		}
	}

	return sb.String()
}
