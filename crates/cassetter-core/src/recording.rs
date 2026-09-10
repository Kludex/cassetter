/// Controls whether a cassette replays or records requests.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum RecordMode {
    /// Replay only. A missing interaction is an error.
    None,
    /// Record a new cassette when no cassette exists, otherwise replay only.
    #[default]
    Once,
    /// Replay matching interactions and record requests that do not match.
    NewEpisodes,
    /// Record every request and replace the existing interactions.
    All,
    /// Remove the existing cassette, then record every request.
    Rewrite,
}

impl RecordMode {
    /// Whether existing interactions can be replayed in this mode.
    pub fn replays(self) -> bool {
        !matches!(self, RecordMode::All | RecordMode::Rewrite)
    }

    /// Whether a request can be recorded in this mode.
    pub fn can_record(self, cassette_exists: bool) -> bool {
        matches!(
            self,
            RecordMode::NewEpisodes | RecordMode::All | RecordMode::Rewrite
        ) || self == RecordMode::Once && !cassette_exists
    }

    /// Whether opening the cassette starts with no existing interactions.
    pub fn replaces(self) -> bool {
        matches!(self, RecordMode::All | RecordMode::Rewrite)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_modes_define_replay_and_recording_policy() {
        assert!(!RecordMode::None.can_record(false));
        assert!(RecordMode::Once.can_record(false));
        assert!(!RecordMode::Once.can_record(true));
        assert!(RecordMode::NewEpisodes.replays());
        assert!(!RecordMode::All.replays());
        assert!(RecordMode::Rewrite.replaces());
    }
}
