// Package main provides a secret rotation tool for TetraCore Hub.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/tetra/core-hub/internal/secrets"
)

func main() {
	// Parse flags
	providerType := flag.String("provider", "env", "Secret provider (env, aws, vault)")
	envFile := flag.String("env-file", ".env", "Path to .env file (for env provider)")
	rotateAll := flag.Bool("rotate-all", false, "Rotate all critical secrets")
	rotateKey := flag.String("rotate-key", "", "Rotate a specific key")
	secretType := flag.String("secret-type", "api_key", "Secret type (jwt_secret, api_key, password, encryption_key, token, webhook_secret)")
	listSecrets := flag.Bool("list", false, "List all secrets")
	verifyKey := flag.String("verify", "", "Verify a key was rotated")
	verifyOldValue := flag.String("old-value", "", "Old value for verification")
	dryRun := flag.Bool("dry-run", false, "Show what would be done without executing")
	backupDir := flag.String("backup-dir", "secrets_backup", "Directory for backups")
	logFile := flag.String("log-file", "logs/secret_rotation.log", "Log file for rotations")
	flag.Parse()

	// Create provider configuration
	providerCfg := secrets.ProviderConfig{
		Type:        *providerType,
		EnvFilePath: *envFile,
		AWSRegion:   os.Getenv("AWS_REGION"),
		AWSPrefix:   os.Getenv("AWS_SECRETS_PREFIX"),
		VaultURL:    os.Getenv("VAULT_URL"),
		VaultToken:  os.Getenv("VAULT_TOKEN"),
	}

	// Create context with timeout
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	// Create provider
	provider, err := secrets.NewProvider(providerCfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error creating provider: %v\n", err)
		os.Exit(1)
	}

	// Create rotator
	rotator, err := secrets.NewRotator(provider, secrets.RotatorConfig{
		BackupDir: *backupDir,
		LogFile:   *logFile,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error creating rotator: %v\n", err)
		os.Exit(1)
	}

	// Execute command
	switch {
	case *listSecrets:
		executeList(ctx, rotator)

	case *rotateAll:
		executeRotateAll(ctx, rotator, *dryRun)

	case *rotateKey != "":
		executeRotateKey(ctx, rotator, *rotateKey, secrets.ParseSecretType(*secretType), *dryRun)

	case *verifyKey != "":
		executeVerify(ctx, rotator, *verifyKey, *verifyOldValue)

	default:
		flag.Usage()
	}
}

func executeList(ctx context.Context, rotator *secrets.Rotator) {
	secretsList, err := rotator.List(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error listing secrets: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Available secrets:")
	sort.Strings(secretsList)
	for _, s := range secretsList {
		fmt.Printf("  - %s\n", s)
	}
	fmt.Printf("\nTotal: %d secrets\n", len(secretsList))
}

func executeRotateAll(ctx context.Context, rotator *secrets.Rotator, dryRun bool) {
	if dryRun {
		fmt.Println("DRY RUN: The following secrets would be rotated:")
		for _, key := range secrets.CriticalSecrets {
			secretType := secrets.GetSecretType(key)
			fmt.Printf("  - %s (type: %s)\n", key, secretType)
		}
		return
	}

	fmt.Println("Rotating critical secrets...")
	fmt.Println()

	results, err := rotator.RotateAll(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error during rotation: %v\n", err)
	}

	// Print results
	fmt.Println("Rotation results:")
	var successful, failed int
	for _, key := range secrets.CriticalSecrets {
		result := results[key]
		if result.Success {
			fmt.Printf("  [OK] %s\n", key)
			successful++
		} else {
			errMsg := "unknown error"
			if result.Error != nil {
				errMsg = result.Error.Error()
			}
			fmt.Printf("  [FAIL] %s: %s\n", key, errMsg)
			failed++
		}
	}

	fmt.Println()
	fmt.Printf("Successfully rotated: %d/%d\n", successful, successful+failed)

	if failed > 0 {
		os.Exit(1)
	}
}

func executeRotateKey(ctx context.Context, rotator *secrets.Rotator, key string, secretType secrets.SecretType, dryRun bool) {
	if dryRun {
		fmt.Printf("DRY RUN: Would rotate key '%s'\n", key)
		newValue, err := secrets.GenerateSecret(secretType)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error generating sample: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("Sample new value: %s...\n", maskValue(newValue))
		return
	}

	fmt.Printf("Rotating key '%s'...\n", key)

	result, err := rotator.Rotate(ctx, key, secretType, "")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error rotating key: %v\n", err)
		os.Exit(1)
	}

	if result.Success {
		fmt.Printf("[OK] Key successfully rotated\n")
		fmt.Printf("New value: %s\n", maskValue(result.NewValue))
	} else {
		fmt.Printf("[FAIL] Rotation failed\n")
		if result.Error != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", result.Error)
		}
		os.Exit(1)
	}
}

func executeVerify(ctx context.Context, rotator *secrets.Rotator, key, oldValue string) {
	if oldValue == "" {
		fmt.Fprintf(os.Stderr, "Error: --old-value is required for verification\n")
		os.Exit(1)
	}

	verified, err := rotator.Verify(ctx, key, oldValue)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error verifying: %v\n", err)
		os.Exit(1)
	}

	if verified {
		fmt.Printf("[OK] Rotation verified - value has changed\n")
	} else {
		fmt.Printf("[FAIL] Rotation not verified - value unchanged or missing\n")
		os.Exit(1)
	}
}

func maskValue(value string) string {
	if len(value) <= 8 {
		return strings.Repeat("*", len(value))
	}
	return value[:4] + strings.Repeat("*", len(value)-8) + value[len(value)-4:]
}
