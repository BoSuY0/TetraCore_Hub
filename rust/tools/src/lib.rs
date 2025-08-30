use anyhow::Result;
use clap::{Parser, Subcommand};
use regex::Regex;
use serde::Serialize;
use std::fs;
use std::path::PathBuf;
use walkdir::WalkDir;

#[derive(Parser, Debug)]
#[command(name = "tetratools", version, about = "TetraCore dev tools")] 
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand, Debug)]
pub enum Commands {
    SecretScan {
        #[arg(long, default_value = ".")]
        root: String,
        #[arg(long, value_delimiter = ',')]
        exclude: Vec<String>,
        #[arg(long, default_value_t = 2)]
        max_size_mb: u64,
        #[arg(long, default_value_t = 4.3)]
        entropy_threshold: f64,
        #[arg(long, default_value_t = 20)]
        min_length: usize,
        #[arg(long, default_value = "text", value_parser = ["text", "json"])]
        format: String,
    },
}

#[derive(Debug, Serialize)]
pub struct Finding {
    pub path: String,
    pub line: usize,
    pub kind: String,
}

pub fn run_cli() -> Result<i32> {
    let cli = Cli::parse();
    match cli.command {
        Commands::SecretScan { root, exclude, max_size_mb, entropy_threshold: _, min_length: _, format } => {
            let findings = secret_scan(PathBuf::from(root), exclude, max_size_mb)?;
            if format == "json" {
                println!("{}", serde_json::to_string_pretty(&findings)?);
            } else {
                if findings.is_empty() {
                    println!("No findings.");
                } else {
                    for f in &findings {
                        println!("[{}] {}:{}", f.kind, f.path, f.line);
                    }
                }
            }
            Ok(0)
        }
    }
}

fn is_probably_text(path: &PathBuf) -> bool {
    match path.extension().and_then(|s| s.to_str()) {
        Some(ext) => matches!(ext.to_ascii_lowercase().as_str(),
            "py" | "ts" | "tsx" | "js" | "jsx" | "json" | "yml" | "yaml" | "toml" | "ini" | "env" | "md" | "txt" | "cfg" | "conf" | "sql" | "sh" | "ps1" | "rs"
        ),
        None => true,
    }
}

pub fn secret_scan(root: PathBuf, exclude: Vec<String>, max_size_mb: u64) -> Result<Vec<Finding>> {
    let mut findings: Vec<Finding> = Vec::new();
    let secret_patterns: Vec<(&str, Regex)> = vec![
        ("aws_access_key_id", Regex::new(r"\bAKIA[0-9A-Z]{16}\b")?),
        ("github_pat", Regex::new(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")?),
        ("slack_token", Regex::new(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")?),
        ("stripe_secret", Regex::new(r"\bsk_live_[A-Za-z0-9]{24}\b")?),
        ("google_api_key", Regex::new(r"\bAIza[0-9A-Za-z-_]{35}\b")?),
        ("telegram_bot_token", Regex::new(r"\b\d{9,10}:[A-Za-z0-9_-]{35}\b")?),
    ];

    let max_bytes: u64 = max_size_mb * 1024 * 1024;
    'files: for entry in WalkDir::new(&root).into_iter().filter_map(Result::ok) {
        let p = entry.path();
        if !p.is_file() { continue; }
        if exclude.iter().any(|ex| p.to_string_lossy().contains(ex)) { continue; }
        let pb = p.to_path_buf();
        if !is_probably_text(&pb) { continue; }
        if let Ok(meta) = fs::metadata(&pb) {
            if meta.len() > max_bytes { continue; }
        }
        let Ok(content) = fs::read_to_string(&pb) else { continue };
        for (idx, line) in content.lines().enumerate() {
            for (kind, re) in &secret_patterns {
                if re.is_match(line) {
                    findings.push(Finding { path: pb.to_string_lossy().into_owned(), line: idx + 1, kind: kind.to_string() });
                    continue 'files; // перший збіг на файл достатній для швидкого скану
                }
            }
        }
    }
    Ok(findings)
}

