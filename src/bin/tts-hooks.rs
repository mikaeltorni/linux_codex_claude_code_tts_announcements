//! Write generated TTS hook configuration.

use serde_json::{json, Map, Value};
use std::env;
use std::fs;
use std::path::Path;

fn main() {
    let code = match run(env::args().skip(1).collect()) {
        Ok(()) => 0,
        Err(message) => {
            eprintln!("{message}");
            1
        }
    };
    std::process::exit(code);
}

fn run(args: Vec<String>) -> Result<(), String> {
    let command = args.first().cloned().ok_or_else(|| "usage: tts-hooks COMMAND".to_string())?;
    match command.as_str() {
        "codex-hooks" => codex_hooks(Path::new(arg(&args, 1)?), arg(&args, 2)?, &args[3..]),
        "claude" => claude_hooks(Path::new(arg(&args, 1)?), arg(&args, 2)?, &args[3..]),
        "cline" => cline_hook(Path::new(arg(&args, 1)?), arg(&args, 2)?, flag(&args, "--filter-tool").unwrap_or_default()),
        "grok" => grok_hooks(Path::new(arg(&args, 1)?), arg(&args, 2)?),
        "remove-codex" => remove_marked(Path::new(arg(&args, 1)?), &["# BEGIN TTS ANNOUNCEMENTS NOTIFY", "# BEGIN CODEX NOTIFY"]),
        "remove-codex-hooks" => remove_codex_hooks(Path::new(arg(&args, 1)?), &args[2..]),
        "remove-grok" => remove_marked(Path::new(arg(&args, 1)?), &["# BEGIN TTS ANNOUNCEMENTS GROK HOOKS"]),
        "remove-claude" => remove_claude(Path::new(arg(&args, 1)?), arg(&args, 2)?, &args[3..]),
        "remove-cline" => remove_cline(Path::new(arg(&args, 1)?)),
        other => Err(format!("unknown command: {other}")),
    }
}

fn arg(args: &[String], index: usize) -> Result<&str, String> {
    args.get(index).map(String::as_str).ok_or_else(|| format!("missing argument {index}"))
}

fn codex_hooks(path: &Path, command: &str, events: &[String]) -> Result<(), String> {
    let events: Vec<&str> = if events.is_empty() { vec!["PermissionRequest"] } else { events.iter().map(String::as_str).collect() };
    let mut settings = read_object(path);
    let hooks = object_entry(&mut settings, "hooks");
    for event in events {
        let kept = prune_generated(hooks.get(event).cloned().unwrap_or(Value::Null));
        let mut handler = Map::new();
        handler.insert("type".to_string(), json!("command"));
        handler.insert("command".to_string(), json!(command));
        handler.insert("timeout".to_string(), json!(if event == "Stop" { 120 } else { 20 }));
        if event == "Stop" {
            handler.insert("async".to_string(), json!(true));
        }
        let mut entries = kept;
        entries.push(json!({"matcher": "", "hooks": [Value::Object(handler)]}));
        hooks.insert(event.to_string(), Value::Array(entries));
    }
    write_pretty(path, &Value::Object(settings))
}

fn claude_hooks(path: &Path, command: &str, events: &[String]) -> Result<(), String> {
    let defaults = ["SessionStart", "Stop", "SubagentStop", "UserPromptSubmit", "Notification"];
    let events: Vec<&str> = if events.is_empty() { defaults.to_vec() } else { events.iter().map(String::as_str).collect() };
    let mut settings = read_object(path);
    let hooks = object_entry(&mut settings, "hooks");
    for event in events {
        let mut entries = prune_generated(hooks.get(event).cloned().unwrap_or(Value::Null));
        entries.push(json!({"matcher": "", "hooks": [{"type": "command", "command": command}]}));
        hooks.insert(event.to_string(), Value::Array(entries));
    }
    let retired = prune_generated(hooks.get("PreToolUse").cloned().unwrap_or(Value::Null));
    if retired.is_empty() {
        hooks.remove("PreToolUse");
    } else {
        hooks.insert("PreToolUse".to_string(), Value::Array(retired));
    }
    write_pretty(path, &Value::Object(settings))
}

fn cline_hook(path: &Path, command: &str, filter_tool: String) -> Result<(), String> {
    if path.exists() {
        let existing = fs::read_to_string(path).unwrap_or_default();
        if !existing.contains("TTS ANNOUNCEMENTS CLINE HOOK") {
            return Err(format!("refusing to replace unmanaged Cline hook: {}", path.display()));
        }
    }
    let body = if filter_tool.is_empty() {
        format!(
            "#!/usr/bin/env bash\n# TTS ANNOUNCEMENTS CLINE HOOK (generated)\n# Receives one Cline hook JSON object on stdin and must emit JSON on stdout.\nexport CODEX_AGENT_KIND=cline\nexport CODEX_AGENT_LABEL=cline\nexport CODEX_HOME=\"${{CODEX_HOME:-$HOME/.cline}}\"\n{command} >/dev/null || true\nprintf '%s\\n' '{{\"cancel\":false,\"contextModification\":\"\",\"errorMessage\":\"\"}}'\n"
        )
    } else {
        format!(
            "#!/usr/bin/env bash\n# TTS ANNOUNCEMENTS CLINE HOOK (generated)\n# Receives one Cline hook JSON object on stdin and must emit JSON on stdout.\n# PreToolUse fires for every tool call; only invoke the notifier for the\n# attention tool so routine tool execution stays cheap and silent.\nexport CODEX_AGENT_KIND=cline\nexport CODEX_AGENT_LABEL=cline\nexport CODEX_HOME=\"${{CODEX_HOME:-$HOME/.cline}}\"\ninput=$(cat)\ncase \"$input\" in\n  *{filter_tool}*) printf '%s' \"$input\" | {command} >/dev/null || true ;;\nesac\nprintf '%s\\n' '{{\"cancel\":false,\"contextModification\":\"\",\"errorMessage\":\"\"}}'\n"
        )
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    fs::write(path, body).map_err(|err| err.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o755));
    }
    Ok(())
}

fn grok_hooks(path: &Path, command: &str) -> Result<(), String> {
    let events = ["session_ready", "turn_complete", "task_complete", "agent_error", "approval_required"]
        .iter()
        .map(|event| format!("\"{event}\""))
        .collect::<Vec<_>>()
        .join(", ");
    let block = format!(
        "# BEGIN TTS ANNOUNCEMENTS GROK HOOKS (generated)\n[[ui.notifications.hooks]]\ncommand = \"{command} --grok\"\nevents = [{events}]\nonly_unfocused = false\ntimeout_secs = 30\n# END TTS ANNOUNCEMENTS GROK HOOKS (generated)\n"
    );
    let existing = fs::read_to_string(path).unwrap_or_default();
    let stripped = strip_between(&existing, "# BEGIN TTS ANNOUNCEMENTS GROK HOOKS", "# END TTS ANNOUNCEMENTS GROK HOOKS");
    let updated = if stripped.trim().is_empty() { block } else { format!("{}\n\n{block}", stripped.trim_end()) };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    fs::write(path, updated).map_err(|err| err.to_string())
}

fn remove_marked(path: &Path, markers: &[&str]) -> Result<(), String> {
    let Ok(text) = fs::read_to_string(path) else { return Ok(()) };
    let mut updated = text;
    for marker in markers {
        let end = marker.replacen("BEGIN", "END", 1);
        updated = strip_between(&updated, marker, &end);
    }
    fs::write(path, if updated.trim().is_empty() { String::new() } else { format!("{}\n", updated.trim()) }).map_err(|err| err.to_string())
}

fn remove_codex_hooks(path: &Path, events: &[String]) -> Result<(), String> {
    let events: Vec<&str> = if events.is_empty() { vec!["PermissionRequest"] } else { events.iter().map(String::as_str).collect() };
    let mut settings = read_object(path);
    if let Some(hooks) = settings.get_mut("hooks").and_then(Value::as_object_mut) {
        for event in events {
            let kept = prune_generated(hooks.get(event).cloned().unwrap_or(Value::Null));
            if kept.is_empty() {
                hooks.remove(event);
            } else {
                hooks.insert(event.to_string(), Value::Array(kept));
            }
        }
        if hooks.is_empty() {
            settings.remove("hooks");
        }
    }
    write_pretty(path, &Value::Object(settings))
}

fn remove_claude(path: &Path, _command: &str, events: &[String]) -> Result<(), String> {
    let defaults = ["SessionStart", "Stop", "SubagentStop", "UserPromptSubmit", "Notification"];
    let events: Vec<&str> = if events.is_empty() { defaults.to_vec() } else { events.iter().map(String::as_str).collect() };
    let mut settings = read_object(path);
    if let Some(hooks) = settings.get_mut("hooks").and_then(Value::as_object_mut) {
        for event in events {
            let kept = prune_generated(hooks.get(event).cloned().unwrap_or(Value::Null));
            if kept.is_empty() {
                hooks.remove(event);
            } else {
                hooks.insert(event.to_string(), Value::Array(kept));
            }
        }
        if hooks.is_empty() {
            settings.remove("hooks");
        }
    }
    write_pretty(path, &Value::Object(settings))
}

fn is_generated_notify(command: &str) -> bool {
    command.contains("notify_agent.py") || command.contains("notify-agent")
}

fn prune_generated(entries: Value) -> Vec<Value> {
    let Some(entries) = entries.as_array() else { return Vec::new() };
    let mut kept = Vec::new();
    for entry in entries {
        let Some(obj) = entry.as_object() else { kept.push(entry.clone()); continue };
        let Some(handlers) = obj.get("hooks").and_then(Value::as_array) else { kept.push(entry.clone()); continue };
        let filtered: Vec<Value> = handlers.iter().filter(|handler| {
            let command = handler.get("command").and_then(Value::as_str).unwrap_or("");
            !is_generated_notify(command)
        }).cloned().collect();
        if !filtered.is_empty() {
            let mut updated = obj.clone();
            updated.insert("hooks".to_string(), Value::Array(filtered));
            kept.push(Value::Object(updated));
        }
    }
    kept
}

fn remove_cline(path: &Path) -> Result<(), String> {
    let Ok(text) = fs::read_to_string(path) else { return Ok(()) };
    if text.contains("TTS ANNOUNCEMENTS CLINE HOOK") {
        fs::remove_file(path).map_err(|err| err.to_string())?;
    }
    Ok(())
}

fn read_object(path: &Path) -> Map<String, Value> {
    fs::read_to_string(path).ok().and_then(|text| serde_json::from_str::<Value>(&text).ok()).and_then(|value| match value { Value::Object(map) => Some(map), _ => None }).unwrap_or_default()
}

fn object_entry<'a>(settings: &'a mut Map<String, Value>, key: &str) -> &'a mut Map<String, Value> {
    if !settings.get(key).map(Value::is_object).unwrap_or(false) {
        settings.insert(key.to_string(), json!({}));
    }
    settings.get_mut(key).and_then(Value::as_object_mut).unwrap()
}

fn write_pretty(path: &Path, value: &Value) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let text = serde_json::to_string_pretty(value).map_err(|err| err.to_string())?;
    fs::write(path, format!("{text}\n")).map_err(|err| err.to_string())
}

fn strip_between(text: &str, start: &str, end: &str) -> String {
    let mut rest = text;
    let mut out = String::new();
    while let Some(begin) = rest.find(start) {
        out.push_str(&rest[..begin]);
        let after = &rest[begin..];
        if let Some(stop) = after.find(end) {
            let tail = &after[stop + end.len()..];
            rest = tail.trim_start_matches('\n');
        } else {
            rest = "";
        }
    }
    out.push_str(rest);
    out
}

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|arg| arg == name).and_then(|index| args.get(index + 1)).cloned()
}
