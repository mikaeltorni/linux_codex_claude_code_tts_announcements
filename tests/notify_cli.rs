//! Public checks for the notify-agent hook router.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_notify-agent"))
}

fn isolated(command: &mut Command, tracker: &str, log: &str) {
    for key in [
        "ATTS_SUPPRESS_ANNOUNCEMENTS",
        "ATTS_LIFECYCLE_TRACKED",
        "ATTS_VOICE",
        "ATTS_CODEX_HOOK_BACKGROUND",
        "CODEX_AGENT_RUN_ID",
        "CODEX_AGENT_FEATURE_KEY",
        "CODEX_AGENT_PROJECT_PATH",
        "CODEX_AGENT_PROJECT_NAME",
        "CODEX_AGENT_KIND",
        "CODEX_AGENT_LABEL",
        "CODEX_HOME",
        "CLAUDE_CLARIFY_VOICE",
        "GROK_EVENT",
        "GROK_MESSAGE",
    ] {
        command.env_remove(key);
    }
    command.env("CODEX_AGENT_TRACKER", tracker);
    command.env("TRACKER_LOG", log);
    command.env("ATTS_CODEX_HOOK_BACKGROUND", "1");
}

#[test]
fn untracked_prompt_announces_start_and_titles_twice() {
    let dir = std::env::temp_dir().join(format!("notify-agent-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let tracker = dir.join("tracker.sh");
    let log = dir.join("tracker.log");
    fs::write(&tracker, "#!/bin/bash\nprintf '%s\\n' \"$@\" >> \"$TRACKER_LOG\"\nprintf '\\n' >> \"$TRACKER_LOG\"\n").unwrap();
    fs::set_permissions(&tracker, fs::Permissions::from_mode(0o755)).unwrap();
    let payload = "{\"hook_event_name\":\"UserPromptSubmit\",\"prompt\":\"hello demo\",\"cwd\":\"/work/demo\"}";
    let mut logs = Vec::new();
    for _ in 0..2 {
        let _ = fs::write(&log, "");
        let mut command = Command::new(bin());
        isolated(&mut command, tracker.to_str().unwrap(), log.to_str().unwrap());
        let mut child = command.stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::piped()).spawn().unwrap();
        use std::io::Write;
        child.stdin.take().unwrap().write_all(payload.as_bytes()).unwrap();
        let output = child.wait_with_output().unwrap();
        assert_eq!(output.status.code(), Some(0), "{}", String::from_utf8_lossy(&output.stderr));
        logs.push(fs::read_to_string(&log).unwrap());
    }
    assert_eq!(logs[0], logs[1]);
    for needle in ["announce", "--event", "start", "title", "--prompt", "hello demo", "--project-path", "/work/demo"] {
        assert!(logs[0].contains(needle), "missing {needle} in {}", logs[0]);
    }
    let _ = fs::write(&log, "");
    let mut command = Command::new(bin());
    isolated(&mut command, tracker.to_str().unwrap(), log.to_str().unwrap());
    command.env_remove("ATTS_CODEX_HOOK_BACKGROUND");
    let mut child = command.stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::piped()).spawn().unwrap();
    use std::io::Write;
    child.stdin.take().unwrap().write_all(payload.as_bytes()).unwrap();
    let output = child.wait_with_output().unwrap();
    assert_eq!(output.status.code(), Some(0));
    let mut detached = String::new();
    for _ in 0..20 {
        detached = fs::read_to_string(&log).unwrap_or_default();
        if detached.contains("hello demo") {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    assert!(detached.contains("hello demo"), "{detached}");
    let _ = fs::remove_dir_all(dir);
}
