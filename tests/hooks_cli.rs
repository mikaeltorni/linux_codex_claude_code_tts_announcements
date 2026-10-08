//! Public checks for the tts-hooks config writer.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_tts-hooks"))
}

fn run(args: &[&str]) -> (i32, String) {
    let output = Command::new(bin()).args(args).output().expect("run tts-hooks");
    (
        output.status.code().unwrap_or(1),
        String::from_utf8_lossy(&output.stderr).to_string(),
    )
}

#[test]
fn claude_session_start_matches_golden_and_keeps_user_hooks() {
    let dir = std::env::temp_dir().join(format!("tts-hooks-claude-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let settings = dir.join("settings.json");
    let (code, err) = run(&["claude", settings.to_str().unwrap(), "/opt/notify-agent", "SessionStart"]);
    assert_eq!(code, 0, "{err}");
    let golden = "{\n  \"hooks\": {\n    \"SessionStart\": [\n      {\n        \"matcher\": \"\",\n        \"hooks\": [\n          {\n            \"type\": \"command\",\n            \"command\": \"/opt/notify-agent\"\n          }\n        ]\n      }\n    ]\n  }\n}\n";
    assert_eq!(fs::read_to_string(&settings).unwrap(), golden);
    let prior = "{\n  \"hooks\": {\n    \"SessionStart\": [\n      {\"matcher\": \"\", \"hooks\": [{\"type\": \"command\", \"command\": \"/usr/local/bin/user-hook\"}]},\n      {\"matcher\": \"\", \"hooks\": [{\"type\": \"command\", \"command\": \"python3 /old/notify_agent.py\"}]}\n    ],\n    \"PreToolUse\": [\n      {\"matcher\": \"\", \"hooks\": [{\"type\": \"command\", \"command\": \"/usr/local/bin/keep-me\"}]}\n    ]\n  }\n}\n";
    fs::write(&settings, prior).unwrap();
    let (code, err) = run(&["claude", settings.to_str().unwrap(), "/opt/notify-agent", "SessionStart"]);
    assert_eq!(code, 0, "{err}");
    let written = fs::read_to_string(&settings).unwrap();
    assert!(written.contains("/usr/local/bin/user-hook"), "{written}");
    assert!(written.contains("/usr/local/bin/keep-me"), "{written}");
    assert!(!written.contains("notify_agent.py"), "{written}");
    assert!(written.contains("\"command\": \"/opt/notify-agent\""), "{written}");
    let (code, err) = run(&["claude", settings.to_str().unwrap(), "/opt/notify-agent", "SessionStart"]);
    assert_eq!(code, 0, "{err}");
    assert_eq!(fs::read_to_string(&settings).unwrap(), written);
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn codex_lifecycle_matches_golden_and_second_write_is_identical() {
    let dir = std::env::temp_dir().join(format!("tts-hooks-codex-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let hooks = dir.join("hooks.json");
    let command = "env CODEX_AGENT_KIND=codex /opt/notify-agent";
    let (code, err) = run(&["codex-hooks", hooks.to_str().unwrap(), command, "UserPromptSubmit", "Stop"]);
    assert_eq!(code, 0, "{err}");
    let golden = "{\n  \"hooks\": {\n    \"UserPromptSubmit\": [\n      {\n        \"matcher\": \"\",\n        \"hooks\": [\n          {\n            \"type\": \"command\",\n            \"command\": \"env CODEX_AGENT_KIND=codex /opt/notify-agent\",\n            \"timeout\": 20\n          }\n        ]\n      }\n    ],\n    \"Stop\": [\n      {\n        \"matcher\": \"\",\n        \"hooks\": [\n          {\n            \"type\": \"command\",\n            \"command\": \"env CODEX_AGENT_KIND=codex /opt/notify-agent\",\n            \"timeout\": 120,\n            \"async\": true\n          }\n        ]\n      }\n    ]\n  }\n}\n";
    let first = fs::read_to_string(&hooks).unwrap();
    assert_eq!(first, golden);
    let (code, err) = run(&["codex-hooks", hooks.to_str().unwrap(), command, "UserPromptSubmit", "Stop"]);
    assert_eq!(code, 0, "{err}");
    assert_eq!(fs::read_to_string(&hooks).unwrap(), first);
    let _ = fs::remove_dir_all(dir);
}
