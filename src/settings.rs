//! Persisted speed, volume, and silent settings.
//!
//! File names and text match the Python engine so either command can read
//! a value the other saved.

use std::env;
use std::fs;
use std::path::PathBuf;

const TRUTHY: &[&str] = &["1", "true", "yes", "y", "on", "shutdown", "poweroff"];
const DEFAULT_SPEED: f64 = 1.5;
const LEGACY_VOLUME_ENV: &str = "125";

/// Return the first set, non-empty environment value.
///
/// Parameters: names - environment variable names in priority order.
///
/// Returns: the raw value, or None when every name is unset or blank.
pub fn first_env(names: &[&str]) -> Option<String> {
    names.iter().find_map(|name| {
        env::var(name).ok().and_then(|value| {
            if value.trim().is_empty() {
                None
            } else {
                Some(value)
            }
        })
    })
}

fn state_dir() -> PathBuf {
    if let Some(value) = first_env(&["ATTS_STATE_DIR", "CODEX_AGENT_TRACKER_STATE_DIR"]) {
        return PathBuf::from(value);
    }
    home().join(".local/state/agent-tts")
}

fn legacy_state_dir() -> PathBuf {
    home().join(".local/state/codex-agent-tracker")
}

fn home() -> PathBuf {
    env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}

fn read_state_file(filename: &str) -> String {
    for base in [state_dir(), legacy_state_dir()] {
        let path = base.join(filename);
        if let Ok(text) = fs::read_to_string(path) {
            let text = text.trim().to_string();
            if !text.is_empty() {
                return text;
            }
        }
    }
    String::new()
}

fn write_state_file(filename: &str, text: &str) -> Result<(), String> {
    let path = state_dir().join(filename);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, text).map_err(|err| err.to_string())?;
    fs::rename(&tmp, &path).map_err(|err| err.to_string())
}

/// Validate a speed multiplier.
///
/// Parameters: value - the raw speed token.
///
/// Returns: the parsed speed, or an error when it is not positive.
pub fn parse_speed(value: &str) -> Result<f64, String> {
    let speed = value.trim().parse::<f64>().map_err(|_| "speed must be a positive number".to_string())?;
    if speed <= 0.0 {
        return Err("speed must be greater than 0".into());
    }
    Ok(speed)
}

/// Format a speed the way the Python command prints it.
///
/// Parameters: speed - a validated multiplier.
///
/// Returns: a compact decimal string.
pub fn format_speed(speed: f64) -> String {
    format!("{speed:.3}").trim_end_matches('0').trim_end_matches('.').to_string()
}

/// Return the speed in effect for this process.
///
/// Parameters: none.
///
/// Returns: the environment override, the saved value, or 1.5.
pub fn current_speed() -> f64 {
    if let Some(value) = first_env(&["ATTS_SPEED", "AGENT_COMMAND_CENTER_TTS_SPEED"]) {
        if let Ok(speed) = parse_speed(value.trim()) {
            return speed;
        }
    }
    let text = read_state_file("tts-speed");
    parse_speed(&text).unwrap_or(DEFAULT_SPEED)
}

/// Save a speed multiplier.
///
/// Parameters: speed - the validated multiplier.
///
/// Returns: nothing, or an error when the state file cannot be written.
pub fn set_speed(speed: f64) -> Result<(), String> {
    write_state_file("tts-speed", &format!("{}\n", format_speed(speed)))
}

/// Validate a volume percentage.
///
/// Parameters: value - the raw percentage, with an optional trailing percent sign.
///
/// Returns: the parsed percentage, or an error when it is not positive.
pub fn parse_volume(value: &str) -> Result<f64, String> {
    let raw = value.trim().trim_end_matches('%').trim();
    let percent = raw.parse::<f64>().map_err(|_| "volume must be a positive percentage".to_string())?;
    if percent <= 0.0 {
        return Err("volume must be greater than 0%".into());
    }
    Ok(percent)
}

/// Format a volume percentage for display and for the state file.
///
/// Parameters: percent - a validated percentage.
///
/// Returns: a compact percentage string.
pub fn format_volume(percent: f64) -> String {
    format!("{}%", format!("{percent:.3}").trim_end_matches('0').trim_end_matches('.'))
}

fn persisted_volume() -> Option<f64> {
    let text = read_state_file("tts-volume");
    if text.is_empty() {
        None
    } else {
        parse_volume(&text).ok()
    }
}

/// Return the volume percentage in effect for this process.
///
/// Parameters: none.
///
/// Returns: the environment override, the saved value, or 1000.
pub fn current_volume() -> f64 {
    if let Some(value) = first_env(&["ATTS_VOLUME_PERCENT", "AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT"]) {
        let text = value.trim();
        if text == LEGACY_VOLUME_ENV {
            if let Some(saved) = persisted_volume() {
                return saved;
            }
        } else if let Ok(percent) = parse_volume(text) {
            return percent;
        }
    }
    persisted_volume().unwrap_or(1000.0)
}

/// Save a volume percentage.
///
/// Parameters: percent - the validated percentage.
///
/// Returns: nothing, or an error when the state file cannot be written.
pub fn set_volume(percent: f64) -> Result<(), String> {
    write_state_file("tts-volume", &format!("{}\n", format_volume(percent)))
}

fn truthy(value: &str) -> bool {
    TRUTHY.contains(&value.trim().to_ascii_lowercase().as_str())
}

/// Return whether announcements are muted.
///
/// Parameters: none.
///
/// Returns: true when the environment or the saved flag is truthy.
pub fn silent_enabled() -> bool {
    if let Some(value) = first_env(&["ATTS_SILENT", "ACC_SILENT"]) {
        return truthy(value.trim());
    }
    truthy(&read_state_file("silent"))
}

/// Save the silent flag.
///
/// Parameters: enabled - true mutes announcements.
///
/// Returns: nothing, or an error when the state file cannot be written.
pub fn set_silent(enabled: bool) -> Result<(), String> {
    write_state_file("silent", if enabled { "1\n" } else { "0\n" })
}

