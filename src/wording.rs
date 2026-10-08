//! Spoken start, finish, and clarify sentences.
//!
//! Workspace suffixes stay in the Python engine's speak path so a message is
//! not labeled twice.

use crate::settings::first_env;
use std::env;
use std::fs;
use std::path::Path;

const TRUTHY: &[&str] = &["1", "true", "yes", "y", "on", "shutdown", "poweroff"];
const FALSEY: &[&str] = &["0", "false", "no", "n", "off", "disabled"];

/// Return whether this process opted out of lifecycle speech.
///
/// Parameters: none.
///
/// Returns: true when ATTS_SUPPRESS_ANNOUNCEMENTS is truthy.
pub fn announcements_suppressed() -> bool {
    env::var("ATTS_SUPPRESS_ANNOUNCEMENTS")
        .ok()
        .is_some_and(|value| TRUTHY.contains(&value.trim().to_ascii_lowercase().as_str()))
}

/// Return whether one announcement category should speak.
///
/// Parameters: event - start, finish, or attention.
///
/// Returns: true when the category is enabled. A missing setting stays enabled.
pub fn announcement_enabled(event: &str) -> bool {
    let key = match event.trim().to_ascii_lowercase().as_str() {
        "start" => "ATTS_ANNOUNCE_START",
        "finish" | "end" => "ATTS_ANNOUNCE_FINISH",
        "attention" | "clarify" => "ATTS_ANNOUNCE_ATTENTION",
        _ => return true,
    };
    let mut value = env::var(key).unwrap_or_default();
    if value.trim().is_empty() {
        value = configured_event(key).unwrap_or_default();
        if value.is_empty() {
            return true;
        }
    }
    let lowered = value.trim().trim_matches('"').trim_matches('\'').to_ascii_lowercase();
    if FALSEY.contains(&lowered.as_str()) {
        return false;
    }
    true
}

fn configured_event(key: &str) -> Option<String> {
    let path = event_config_file();
    let text = fs::read_to_string(path).ok()?;
    for raw in text.lines() {
        let Some((name, candidate)) = raw.split_once('=') else { continue };
        if name.trim() == key {
            return Some(candidate.trim().trim_matches('"').trim_matches('\'').to_string());
        }
    }
    None
}

fn event_config_file() -> std::path::PathBuf {
    if let Some(value) = first_env(&["ATTS_EVENT_CONFIG_FILE"]) {
        return Path::new(&value).to_path_buf();
    }
    home().join(".config/agent-tts/announcements.env")
}

fn home() -> std::path::PathBuf {
    env::var_os("HOME").map(std::path::PathBuf::from).unwrap_or_else(|| std::path::PathBuf::from("/"))
}

fn folder_name(project_path: &str) -> String {
    let path = project_path.trim();
    if path.is_empty() {
        return String::new();
    }
    Path::new(path)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("")
        .to_string()
}

/// Build the spoken start or finish sentence.
///
/// Parameters: label - runtime name; project_name - spoken project; event - start or finish;
/// project_path - folder fallback; completion_message - optional finish sentence;
/// model_name - optional leading model sentence.
///
/// Returns: the sentence, without a workspace suffix.
pub fn announcement_text(
    label: &str,
    project_name: &str,
    event: &str,
    project_path: &str,
    completion_message: &str,
    model_name: &str,
) -> String {
    let prefix = if model_name.trim().is_empty() {
        String::new()
    } else {
        format!("{}. ", model_name.trim())
    };
    if event == "finish" && !completion_message.trim().is_empty() {
        return format!("{prefix}{}", completion_message.trim());
    }
    let display = if matches!(label, "codex" | "claude") {
        label.to_string()
    } else if label.is_empty() {
        "Agent".to_string()
    } else {
        let mut chars = label.chars();
        match chars.next() {
            Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
            None => "Agent".to_string(),
        }
    };
    if event == "start" {
        if !project_name.is_empty() {
            return format!("{prefix}Project {project_name} started");
        }
        return format!("{prefix}{display} started");
    }
    if project_path.trim().is_empty() {
        if !project_name.is_empty() {
            return format!("{prefix}Finished working on Project {project_name}");
        }
        return format!("{prefix}{display} ended");
    }
    format!("{prefix}{display} finished on {}", folder_name(project_path))
}

/// Build the spoken clarification question.
///
/// Parameters: project_name - spoken project; project_path - folder fallback.
///
/// Returns: the question, without a workspace suffix.
pub fn clarify_text(project_name: &str, project_path: &str) -> String {
    let target = if !project_name.trim().is_empty() {
        project_name.trim().to_string()
    } else {
        folder_name(project_path)
    };
    if target.is_empty() {
        "I need your input. What should we do next?".to_string()
    } else {
        format!("Project {target} needs your input. What should we do next?")
    }
}

/// Return the Claude voice used when a command does not pass one.
///
/// Parameters: none.
///
/// Returns: the first configured Claude voice, or af_sky.
pub fn default_claude_voice() -> String {
    for name in ["ATTS_VOICE", "ATTS_CLAUDE_VOICE", "CLAUDE_TTS_VOICE", "CLAUDE_CODE_TTS_VOICE", "CODEX__TTS_VOICE"] {
        if let Some(value) = first_env(&[name]) {
            return value.trim().to_string();
        }
    }
    "af_sky".to_string()
}
