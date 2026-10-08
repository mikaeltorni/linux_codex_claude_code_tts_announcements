//! Hand a prepared sentence to the Python synthesis engine.
//!
//! Kokoro, ffmpeg gain, and playback stay in that engine. ATTS_SPEAK_RECORD
//! captures the sentence for tests and does not start synthesis.

use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

/// One request for the synthesis engine.
pub struct Speech<'a> {
    pub text: &'a str,
    pub voice: &'a str,
    pub codex_home: &'a str,
    pub play: bool,
    pub ignore_silent: bool,
    pub workspace: Option<&'a str>,
}

/// Speak one sentence, or record it when a test capture file is set.
///
/// Parameters: speech - the sentence, voice, and playback flags.
///
/// Returns: true when the sentence was recorded or the engine accepted it.
pub fn speak(speech: Speech<'_>) -> bool {
    if let Ok(path) = env::var("ATTS_SPEAK_RECORD") {
        return record(&path, speech.text, speech.voice);
    }
    let Some(lib) = python_lib() else {
        return false;
    };
    let workspace = speech.workspace.unwrap_or("\u{1f}");
    let status = Command::new("python3")
        .arg("-c")
        .arg(PYTHON_SPEAK)
        .arg(lib)
        .arg(speech.text)
        .arg(speech.voice)
        .arg(speech.codex_home)
        .arg(if speech.play { "1" } else { "0" })
        .arg(if speech.ignore_silent { "1" } else { "0" })
        .arg(workspace)
        .status();
    matches!(status, Ok(status) if status.success())
}

fn record(path: &str, text: &str, voice: &str) -> bool {
    if let Some(parent) = Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            let _ = fs::create_dir_all(parent);
        }
    }
    let mut file = match OpenOptions::new().create(true).append(true).open(path) {
        Ok(file) => file,
        Err(_) => return false,
    };
    writeln!(file, "{text}\t{voice}").is_ok()
}

fn python_lib() -> Option<PathBuf> {
    let exe = env::current_exe().ok()?;
    let dir = exe.parent()?;
    for relative in ["../lib", "../../lib", "../../../lib"] {
        let candidate = dir.join(relative);
        if candidate.join("agent_tts/engine.py").is_file() {
            return Some(candidate);
        }
    }
    None
}

const PYTHON_SPEAK: &str = r#"
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from agent_tts.engine import speak
text, voice, home, play, ignore, workspace = sys.argv[2:8]
spoken = speak(
    text,
    voice,
    Path(home) if home else None,
    play=(play == "1"),
    ignore_silent=(ignore == "1"),
    workspace=None if workspace == "\x1f" else workspace,
)
raise SystemExit(0 if spoken else 1)
"#;
