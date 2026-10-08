//! Agent TTS command.

fn main() {
    let code = agent_tts::run(std::env::args().skip(1).collect());
    std::process::exit(code);
}
