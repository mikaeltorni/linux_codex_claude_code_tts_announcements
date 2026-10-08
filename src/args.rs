//! Parse agent-tts arguments into one command.
//!
//! The parser owns flag and positional shape. It does not read settings or speak.

use crate::wording::default_claude_voice;

/// One parsed agent-tts command.
pub enum Command {
    Voice {
        text: String,
        voice: String,
        codex_home: String,
        play: bool,
        workspace: Option<String>,
    },
    Announce {
        event: String,
        voice: String,
        codex_home: String,
        label: String,
        project_name: String,
        project_path: String,
        completion_message: String,
        model_name: String,
    },
    Clarify {
        voice: String,
        codex_home: String,
        project_name: String,
        project_path: String,
    },
    Silent {
        action: String,
        voice: String,
        codex_home: String,
    },
    Prewarm {
        voice: String,
        codex_home: String,
    },
    Speed {
        value: Option<String>,
    },
    Volume {
        value: Option<String>,
    },
}

/// Parse the command line after the program name.
///
/// Parameters: args - arguments after the program name.
///
/// Returns: the command, or a usage error.
pub fn parse(args: &[String]) -> Result<Command, String> {
    let command = args.first().ok_or_else(|| "usage: agent-tts COMMAND".to_string())?;
    let rest = &args[1..];
    match command.as_str() {
        "voice" | "say" => parse_voice(rest),
        "announce" => parse_announce(rest),
        "clarify" => parse_clarify(rest),
        "silent" => parse_silent(rest),
        "prewarm" => parse_prewarm(rest),
        "speed" => Ok(Command::Speed { value: rest.first().cloned() }),
        "volume" => Ok(Command::Volume { value: rest.first().cloned() }),
        other => Err(format!("unknown command: {other}")),
    }
}

fn parse_voice(args: &[String]) -> Result<Command, String> {
    let flags = flags(args)?;
    Ok(Command::Voice {
        text: required(&flags, "--text")?,
        voice: required(&flags, "--voice")?,
        codex_home: optional(&flags, "--codex-home"),
        play: !flag_present(&flags, "--no-play"),
        workspace: flags.iter().find(|(name, _)| name == "--workspace").map(|(_, value)| value.clone()),
    })
}

fn parse_announce(args: &[String]) -> Result<Command, String> {
    let flags = flags(args)?;
    let event = required(&flags, "--event")?;
    if !matches!(event.as_str(), "start" | "finish") {
        return Err("announce --event must be start or finish".into());
    }
    Ok(Command::Announce {
        event,
        voice: required(&flags, "--voice")?,
        codex_home: optional(&flags, "--codex-home"),
        label: optional(&flags, "--label"),
        project_name: optional(&flags, "--project-name"),
        project_path: optional(&flags, "--project-path"),
        completion_message: optional(&flags, "--completion-message"),
        model_name: optional(&flags, "--model-name"),
    })
}

fn parse_clarify(args: &[String]) -> Result<Command, String> {
    let flags = flags(args)?;
    Ok(Command::Clarify {
        voice: required(&flags, "--voice")?,
        codex_home: optional(&flags, "--codex-home"),
        project_name: optional(&flags, "--project-name"),
        project_path: optional(&flags, "--project-path"),
    })
}

fn parse_silent(args: &[String]) -> Result<Command, String> {
    let mut action = "toggle".to_string();
    let mut flag_args = Vec::new();
    let mut index = 0;
    while index < args.len() {
        let arg = &args[index];
        if arg.starts_with("--") {
            flag_args.push(arg.clone());
            if arg != "--no-play" {
                let value = args.get(index + 1).ok_or_else(|| format!("{arg} needs a value"))?;
                flag_args.push(value.clone());
                index += 2;
                continue;
            }
            index += 1;
            continue;
        }
        action = arg.clone();
        index += 1;
    }
    if !matches!(action.as_str(), "on" | "off" | "toggle" | "status") {
        return Err(format!("unknown silent action: {action}"));
    }
    let flags = flags(&flag_args)?;
    let voice = if flags.iter().any(|(name, _)| name == "--voice") {
        optional(&flags, "--voice")
    } else {
        default_claude_voice()
    };
    Ok(Command::Silent {
        action,
        voice,
        codex_home: optional(&flags, "--codex-home"),
    })
}

fn parse_prewarm(args: &[String]) -> Result<Command, String> {
    let flags = flags(args)?;
    let voice = if flags.iter().any(|(name, _)| name == "--voice") {
        optional(&flags, "--voice")
    } else {
        default_claude_voice()
    };
    Ok(Command::Prewarm { voice, codex_home: optional(&flags, "--codex-home") })
}

fn flags(args: &[String]) -> Result<Vec<(String, String)>, String> {
    let mut parsed = Vec::new();
    let mut index = 0;
    while index < args.len() {
        let name = &args[index];
        if name == "--no-play" {
            parsed.push((name.clone(), String::new()));
            index += 1;
            continue;
        }
        if !name.starts_with("--") {
            return Err(format!("unexpected argument: {name}"));
        }
        let value = args.get(index + 1).ok_or_else(|| format!("{name} needs a value"))?;
        parsed.push((name.clone(), value.clone()));
        index += 2;
    }
    Ok(parsed)
}

fn required(flags: &[(String, String)], name: &str) -> Result<String, String> {
    flags
        .iter()
        .find(|(flag, _)| flag == name)
        .map(|(_, value)| value.clone())
        .ok_or_else(|| format!("{name} is required"))
}

fn optional(flags: &[(String, String)], name: &str) -> String {
    flags.iter().find(|(flag, _)| flag == name).map(|(_, value)| value.clone()).unwrap_or_default()
}

fn flag_present(flags: &[(String, String)], name: &str) -> bool {
    flags.iter().any(|(flag, _)| flag == name)
}
