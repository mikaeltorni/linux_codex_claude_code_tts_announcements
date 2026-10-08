//! Public checks for the agent-tts command.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_agent-tts"))
}

fn run(args: &[&str], env: &[(&str, &str)]) -> (i32, String, String) {
    let mut command = Command::new(bin());
    command.args(args);
    command.env_remove("ATTS_SPEED");
    command.env_remove("ATTS_VOLUME_PERCENT");
    command.env_remove("ATTS_SILENT");
    command.env_remove("ATTS_VOICE");
    command.env_remove("AGENT_COMMAND_CENTER_TTS_SPEED");
    command.env_remove("AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT");
    command.env_remove("ACC_SILENT");
    command.env_remove("CODEX__TTS_VOICE");
    command.env_remove("CLAUDE_TTS_VOICE");
    command.env_remove("CLAUDE_CODE_TTS_VOICE");
    command.env("ATTS_NO_AUDIO", "1");
    command.env("ATTS_ANNOUNCE_WORKSPACE", "0");
    for (key, value) in env {
        command.env(key, value);
    }
    let output = command.output().expect("run agent-tts");
    (
        output.status.code().unwrap_or(1),
        String::from_utf8_lossy(&output.stdout).to_string(),
        String::from_utf8_lossy(&output.stderr).to_string(),
    )
}

#[test]
fn speed_status_defaults_and_persists() {
    let state = std::env::temp_dir().join(format!("agent-tts-speed-{}", std::process::id()));
    let _ = fs::remove_dir_all(&state);
    fs::create_dir_all(&state).unwrap();
    let env = [("ATTS_STATE_DIR", state.to_str().unwrap())];
    let (code, out, err) = run(&["speed"], &env);
    assert_eq!(code, 0, "{err}");
    assert_eq!(out.trim(), "1.5");
    let (code, out, err) = run(&["speed", "2"], &env);
    assert_eq!(code, 0, "{err}");
    assert_eq!(out.trim(), "2");
    let (code, out, _) = run(&["speed", "status"], &env);
    assert_eq!(code, 0);
    assert_eq!(out.trim(), "2");
    let _ = fs::remove_dir_all(state);
}

#[test]
fn volume_zero_is_rejected() {
    let (code, _out, err) = run(&["volume", "0"], &[]);
    assert_eq!(code, 2);
    assert!(err.contains("invalid volume"), "{err}");
}

#[test]
fn silent_status_starts_off_and_on_persists() {
    let state = std::env::temp_dir().join(format!("agent-tts-silent-{}", std::process::id()));
    let record = state.join("spoken.txt");
    let _ = fs::remove_dir_all(&state);
    fs::create_dir_all(&state).unwrap();
    let env = [
        ("ATTS_STATE_DIR", state.to_str().unwrap()),
        ("ATTS_SPEAK_RECORD", record.to_str().unwrap()),
        ("CLAUDE_CODE_TTS_VOICE", "af_claude_code"),
        ("CODEX__TTS_VOICE", "af_wrapper"),
    ];
    let (code, out, err) = run(&["silent", "status"], &env);
    assert_eq!(code, 0, "{err}");
    assert_eq!(out.trim(), "off");
    let (code, out, err) = run(&["silent", "on"], &env);
    assert_eq!(code, 0, "{err}");
    assert_eq!(out.trim(), "on");
    let spoken = fs::read_to_string(&record).unwrap();
    assert!(spoken.contains("af_claude_code"), "{spoken}");
    assert!(spoken.contains("silent mode enabled"), "{spoken}");
    let _ = fs::remove_dir_all(state);
}

#[test]
fn announce_and_clarify_compose_wording_without_speaking_when_suppressed() {
    let state = std::env::temp_dir().join(format!("agent-tts-words-{}", std::process::id()));
    let record = state.join("spoken.txt");
    let _ = fs::remove_dir_all(&state);
    fs::create_dir_all(&state).unwrap();
    let env = [
        ("ATTS_STATE_DIR", state.to_str().unwrap()),
        ("ATTS_SPEAK_RECORD", record.to_str().unwrap()),
    ];
    let (code, _, err) = run(
        &["announce", "--event", "start", "--voice", "af_sky", "--project-name", "demo project"],
        &env,
    );
    assert_eq!(code, 0, "{err}");
    assert_eq!(
        fs::read_to_string(&record).unwrap().trim(),
        "Project demo project started\taf_sky"
    );
    let _ = fs::write(&record, "");
    let (code, _, err) = run(
        &[
            "announce",
            "--event",
            "finish",
            "--voice",
            "af_sky",
            "--completion-message",
            "shipped the feature",
        ],
        &env,
    );
    assert_eq!(code, 0, "{err}");
    assert_eq!(fs::read_to_string(&record).unwrap().trim(), "shipped the feature\taf_sky");
    let _ = fs::write(&record, "");
    let (code, _, _) = run(
        &["clarify", "--voice", "af_jessica", "--project-name", "demo", "--question", "anything"],
        &env,
    );
    assert_eq!(code, 0);
    let clarify = "Project demo needs your input. What should we do next?\taf_jessica";
    assert_eq!(fs::read_to_string(&record).unwrap().trim(), clarify);
    let (code, _, _) = run(
        &["announce", "--event", "finish", "--voice", "af_sky"],
        &[
            ("ATTS_STATE_DIR", state.to_str().unwrap()),
            ("ATTS_SPEAK_RECORD", record.to_str().unwrap()),
            ("ATTS_SUPPRESS_ANNOUNCEMENTS", "1"),
        ],
    );
    assert_eq!(code, 0);
    assert_eq!(fs::read_to_string(&record).unwrap().trim(), clarify);
    let _ = fs::remove_dir_all(state);
}
