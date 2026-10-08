//! Route agent hook events to the tracker, which speaks through agent-tts.

use serde_json::Value;
use std::env;
use std::io::{self, Read};
use std::path::PathBuf;
use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};

fn main() {
    let _ = route();
    std::process::exit(0);
}

fn route() -> bool {
    if truthy(&env::var("ATTS_SUPPRESS_ANNOUNCEMENTS").unwrap_or_default()) {
        return true;
    }
    let args: Vec<String> = env::args().skip(1).collect();
    if args.iter().any(|arg| arg == "--grok") {
        return handle_grok();
    }
    let payload = parse_payload(&args);
    if payload.is_null() {
        return true;
    }
    if payload.get("hookName").is_some() {
        return true;
    }
    let event = payload.get("hook_event_name").and_then(Value::as_str).unwrap_or("").trim();
    let kind = env::var("CODEX_AGENT_KIND").unwrap_or_default();
    if !event.is_empty() && (kind == "codex" || kind.is_empty() && env::var("CODEX_AGENT_LABEL").unwrap_or_default().is_empty()) && env::var("CODEX_AGENT_LABEL").unwrap_or_else(|_| "codex".into()) == "codex" && kind != "claude" {
        return handle_codex(&payload);
    }
    if !event.is_empty() {
        return handle_claude(&payload);
    }
    handle_codex(&payload)
}

fn handle_codex(payload: &Value) -> bool {
    let event = text(payload, "hook_event_name");
    if (event == "UserPromptSubmit" || event == "Stop") && detach_foreground(payload) {
        return true;
    }
    let context = context(payload, "codex");
    let feature = feature_key(text(payload, "session_id"));
    if event == "UserPromptSubmit" {
        let prompt = text(payload, "prompt");
        if !(tracked() && turn_start(&prompt)) {
            announce("start", &context, "", &feature);
        }
        title(&prompt, &context, &feature);
    } else if event == "Stop" {
        if !(tracked() && turn_complete()) {
            announce("finish", &context, "", &feature);
        }
    } else if event == "PermissionRequest" {
        let message = text(payload, "message");
        let question = if message.is_empty() { format!("{} needs your attention", capitalize(&context.label)) } else { message };
        clarify(&context, &question);
    }
    true
}

fn handle_claude(payload: &Value) -> bool {
    let event = text(payload, "hook_event_name");
    if event == "SubagentStop" {
        return true;
    }
    let context = context(payload, "claude");
    let feature = feature_key(text(payload, "session_id"));
    let source = text(payload, "source");
    let source = if source.is_empty() { "startup" } else { source.as_str() };
    if event == "SessionStart" && source == "startup" && !tracked() {
        announce("start", &context, "", &feature);
    } else if event == "Stop" && !tracked() {
        announce("finish", &context, "", &feature);
    } else if event == "UserPromptSubmit" {
        title(&text(payload, "prompt"), &context, &feature);
    } else if event == "Notification" || event == "PermissionRequest" {
        let kind = text(payload, "notification_type");
        let alt = payload.get("notificationType").and_then(Value::as_str).unwrap_or("");
        let note = if kind.is_empty() { alt.to_string() } else { kind };
        if event == "Notification" && !note.is_empty() && note.to_ascii_lowercase() != "permission_prompt" {
            return true;
        }
        let message = text(payload, "message");
        if event == "Notification" && message.to_ascii_lowercase().contains("waiting for your input") {
            return true;
        }
        let question = if message.is_empty() { format!("{} needs your attention", capitalize(&context.label)) } else { message };
        clarify(&context, &question);
    }
    true
}

fn handle_grok() -> bool {
    let event = env::var("GROK_EVENT").unwrap_or_default();
    let context = context(&serde_json::json!({}), "grok");
    if event == "session_ready" {
        announce("start", &context, "", "");
    } else if event == "turn_complete" || event == "task_complete" {
        announce("finish", &context, "", "");
    } else if event == "approval_required" || event == "agent_error" {
        let message = env::var("GROK_MESSAGE").unwrap_or_default();
        clarify(&context, &message);
    }
    true
}

struct Speech {
    label: String,
    project_name: String,
    project_path: String,
    voice: String,
    home: String,
}

fn context(payload: &Value, default_label: &str) -> Speech {
    let label = nonempty(&env::var("CODEX_AGENT_LABEL").unwrap_or_default()).unwrap_or_else(|| default_label.to_string());
    let kind = env::var("CODEX_AGENT_KIND").ok().filter(|value| !value.is_empty()).unwrap_or_else(|| default_label.to_string());
    let project_path = nonempty(&env::var("CODEX_AGENT_PROJECT_PATH").unwrap_or_default()).unwrap_or_else(|| text(payload, "cwd"));
    let project_name = nonempty(&env::var("CODEX_AGENT_PROJECT_NAME").unwrap_or_default()).unwrap_or_else(|| {
        PathBuf::from(&project_path).file_name().and_then(|name| name.to_str()).unwrap_or("").to_string()
    });
    Speech {
        voice: voice_for(&kind),
        home: codex_home(&kind),
        label,
        project_name,
        project_path,
    }
}

fn announce(event: &str, speech: &Speech, task: &str, feature: &str) -> bool {
    let mut args = vec!["announce".to_string(), "--event".into(), event.into(), "--label".into(), speech.label.clone(), "--project-name".into(), speech.project_name.clone(), "--project-path".into(), speech.project_path.clone(), "--voice".into(), speech.voice.clone(), "--codex-home".into(), speech.home.clone()];
    if !task.is_empty() {
        args.extend(["--task-description".into(), task.into()]);
    }
    if !feature.is_empty() {
        args.extend(["--feature-key".into(), feature.into()]);
    }
    tracker(&args)
}

fn clarify(speech: &Speech, question: &str) -> bool {
    let voice = nonempty(&env::var("CLAUDE_CLARIFY_VOICE").unwrap_or_default()).unwrap_or_else(|| "af_jessica".into());
    tracker(&["clarify".into(), "--question".into(), question.into(), "--project-name".into(), speech.project_name.clone(), "--project-path".into(), speech.project_path.clone(), "--voice".into(), voice, "--codex-home".into(), speech.home.clone()])
}

fn title(prompt: &str, speech: &Speech, feature: &str) -> bool {
    let mut args = vec!["title".into(), "--prompt".into(), prompt.into(), "--project-path".into(), speech.project_path.clone(), "--codex-home".into(), speech.home.clone()];
    if !feature.is_empty() {
        args.extend(["--feature-key".into(), feature.into()]);
    }
    tracker(&args)
}

fn turn_start(prompt: &str) -> bool {
    let Some(token) = nonempty(&env::var("CODEX_AGENT_RUN_ID").unwrap_or_default()) else { return false };
    let mut args = vec!["turn-start".into(), "--token".into(), token];
    if !prompt.is_empty() {
        args.extend(["--prompt".into(), prompt.into()]);
    }
    tracker(&args)
}

fn turn_complete() -> bool {
    let Some(token) = nonempty(&env::var("CODEX_AGENT_RUN_ID").unwrap_or_default()) else { return false };
    tracker(&["turn-complete".into(), "--status".into(), "0".into(), "--token".into(), token])
}

fn detach_foreground(payload: &Value) -> bool {
    if env::var("ATTS_CODEX_HOOK_BACKGROUND").unwrap_or_default() == "1"
        || env::var("ATTS_CODEX_STOP_BACKGROUND").unwrap_or_default() == "1"
    {
        return false;
    }
    let Ok(raw) = serde_json::to_string(payload) else { return false };
    let Ok(exe) = env::current_exe() else { return false };
    let mut child = Command::new(exe);
    child.arg(raw).env("ATTS_CODEX_HOOK_BACKGROUND", "1");
    child.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    child.process_group(0);
    child.spawn().is_ok()
}

fn tracker(args: &[String]) -> bool {
    let program = env::var("CODEX_AGENT_TRACKER").unwrap_or_else(|_| {
        let local = home().join(".local/bin/codex-agent-tracker");
        if local.is_file() { local.display().to_string() } else { "codex-agent-tracker".into() }
    });
    Command::new(program).args(args).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).status().map(|status| status.success()).unwrap_or(false)
}

fn parse_payload(args: &[String]) -> Value {
    let positional = args.iter().find(|arg| !arg.trim().is_empty() && !arg.starts_with("--")).cloned();
    let raw = positional.unwrap_or_else(|| {
        let mut buffer = String::new();
        let _ = io::stdin().read_to_string(&mut buffer);
        buffer
    });
    serde_json::from_str(raw.trim()).unwrap_or(Value::Null)
}

fn voice_for(kind: &str) -> String {
    if let Some(voice) = nonempty(&env::var("ATTS_VOICE").unwrap_or_default()) {
        return voice;
    }
    match kind {
        "claude" => first_env(&["ATTS_CLAUDE_VOICE", "CLAUDE_TTS_VOICE", "CLAUDE_CODE_TTS_VOICE", "CODEX__TTS_VOICE"]).unwrap_or_else(|| "af_sky".into()),
        "grok" => first_env(&["ATTS_GROK_VOICE", "GROK_TTS_VOICE"]).unwrap_or_else(|| "af_kore".into()),
        _ => first_env(&["ATTS_CODEX_VOICE", "CODEX_TTS_VOICE", "CODEX__TTS_VOICE"]).unwrap_or_else(|| "af_bella".into()),
    }
}

fn codex_home(kind: &str) -> String {
    if let Some(home) = nonempty(&env::var("CODEX_HOME").unwrap_or_default()) {
        return home;
    }
    let base = home();
    match kind {
        "claude" => base.join(".claude"),
        "grok" => base.join(".grok"),
        "qwen" => base.join(".codex-qwen"),
        _ => base.join(".codex"),
    }.display().to_string()
}

fn feature_key(fallback: String) -> String {
    nonempty(&env::var("CODEX_AGENT_FEATURE_KEY").unwrap_or_default()).unwrap_or(fallback)
}

fn tracked() -> bool {
    truthy(&env::var("ATTS_LIFECYCLE_TRACKED").unwrap_or_default())
}

fn truthy(value: &str) -> bool {
    matches!(value.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on")
}

fn nonempty(value: &str) -> Option<String> {
    let text = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if text.is_empty() { None } else { Some(text) }
}

fn text(value: &Value, field: &str) -> String {
    value.get(field).and_then(Value::as_str).unwrap_or("").split_whitespace().collect::<Vec<_>>().join(" ")
}

fn first_env(names: &[&str]) -> Option<String> {
    names.iter().find_map(|name| nonempty(&env::var(name).unwrap_or_default()))
}

fn capitalize(value: &str) -> String {
    let mut chars = value.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
        None => String::new(),
    }
}

fn home() -> PathBuf {
    env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}
