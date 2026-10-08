//! Agent TTS command dispatch.
//!
//! Parsing, settings, wording, and synthesis each have their own module.

mod args;
mod settings;
mod speak;
mod wording;

use args::Command;
use speak::{speak, Speech};

/// Run one agent-tts invocation.
///
/// Parameters: args - arguments after the program name.
///
/// Returns: the process exit code.
pub fn run(args: Vec<String>) -> i32 {
    match args::parse(&args) {
        Ok(command) => execute(command),
        Err(message) => {
            eprintln!("{message}");
            2
        }
    }
}

fn execute(command: Command) -> i32 {
    match command {
        Command::Voice { text, voice, codex_home, play, workspace } => speak_exit(&text, &voice, &codex_home, play, false, workspace.as_deref()),
        Command::Announce {
            event,
            voice,
            codex_home,
            label,
            project_name,
            project_path,
            completion_message,
            model_name,
        } => announce(&event, &voice, &codex_home, &label, &project_name, &project_path, &completion_message, &model_name),
        Command::Clarify { voice, codex_home, project_name, project_path } => clarify(&voice, &codex_home, &project_name, &project_path),
        Command::Silent { action, voice, codex_home } => silent(&action, &voice, &codex_home),
        Command::Prewarm { voice, codex_home } => {
            let _ = speak(Speech {
                text: "Agent text to speech ready.",
                voice: &voice,
                codex_home: &codex_home,
                play: false,
                ignore_silent: true,
                workspace: None,
            });
            0
        }
        Command::Speed { value } => speed(value.as_deref()),
        Command::Volume { value } => volume(value.as_deref()),
    }
}

fn announce(
    event: &str,
    voice: &str,
    codex_home: &str,
    label: &str,
    project_name: &str,
    project_path: &str,
    completion_message: &str,
    model_name: &str,
) -> i32 {
    if wording::announcements_suppressed() || !wording::announcement_enabled(event) {
        return 0;
    }
    let text = wording::announcement_text(label, project_name, event, project_path, completion_message, model_name);
    if text.is_empty() {
        return 0;
    }
    speak_exit(&text, voice, codex_home, true, false, None)
}

fn clarify(voice: &str, codex_home: &str, project_name: &str, project_path: &str) -> i32 {
    if wording::announcements_suppressed() || !wording::announcement_enabled("attention") {
        return 0;
    }
    let text = wording::clarify_text(project_name, project_path);
    speak_exit(&text, voice, codex_home, true, false, None)
}

fn silent(action: &str, voice: &str, codex_home: &str) -> i32 {
    if action == "status" {
        println!("{}", if settings::silent_enabled() { "on" } else { "off" });
        return 0;
    }
    let target = match action {
        "on" => true,
        "off" => false,
        "toggle" => !settings::silent_enabled(),
        _ => {
            eprintln!("unknown silent action: {action}");
            return 2;
        }
    };
    if let Err(message) = settings::set_silent(target) {
        eprintln!("{message}");
        return 1;
    }
    println!("{}", if target { "on" } else { "off" });
    let text = if target {
        "Agent command center silent mode enabled. Announcements muted."
    } else {
        "Agent command center silent mode unmuted. Announcements restored."
    };
    let _ = speak(Speech {
        text,
        voice,
        codex_home,
        play: true,
        ignore_silent: true,
        workspace: None,
    });
    0
}

fn speed(value: Option<&str>) -> i32 {
    match value {
        None | Some("status") => {
            println!("{}", settings::format_speed(settings::current_speed()));
            0
        }
        Some(value) => match settings::parse_speed(value) {
            Ok(speed) => match settings::set_speed(speed) {
                Ok(()) => {
                    println!("{}", settings::format_speed(speed));
                    0
                }
                Err(message) => {
                    eprintln!("{message}");
                    1
                }
            },
            Err(message) => {
                eprintln!("invalid speed: {message}");
                2
            }
        },
    }
}

fn volume(value: Option<&str>) -> i32 {
    match value {
        None | Some("status") => {
            println!("{}", settings::format_volume(settings::current_volume()));
            0
        }
        Some(value) => match settings::parse_volume(value) {
            Ok(percent) => match settings::set_volume(percent) {
                Ok(()) => {
                    println!("{}", settings::format_volume(percent));
                    0
                }
                Err(message) => {
                    eprintln!("{message}");
                    1
                }
            },
            Err(message) => {
                eprintln!("invalid volume: {message}");
                2
            }
        },
    }
}

fn speak_exit(text: &str, voice: &str, codex_home: &str, play: bool, ignore_silent: bool, workspace: Option<&str>) -> i32 {
    if speak(Speech { text, voice, codex_home, play, ignore_silent, workspace }) {
        0
    } else {
        1
    }
}
