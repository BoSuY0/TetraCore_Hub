fn main() {
    let code = match tools::run_cli() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: {}", e);
            1
        }
    };
    std::process::exit(code);
}


