//! Optional buffered host startup timings. A trace is diagnostic, not a timer
//! for visible presentation; one record is written after the first dispatch.
use serde_json::json;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::time::Instant;

const PHASES: [&str; 7] = [
    "policy_ready",
    "channels_ready",
    "platform_ready",
    "app_callback",
    "session_ready",
    "first_dispatch_enter",
    "first_dispatch_return",
];

pub(crate) struct HostStartup {
    started: Instant,
    path: PathBuf,
    nonce: String,
    points: [Option<u128>; PHASES.len()],
}

impl HostStartup {
    pub(crate) fn from_environment() -> Option<Self> {
        if std::env::var("BUN_NATIVE_HOST_STARTUP_TRACE").as_deref() != Ok("1") {
            return None;
        }
        let started = Instant::now();
        let path = PathBuf::from(std::env::var_os("BUN_NATIVE_EVIDENCE_LOG")?);
        let nonce = std::env::var("BUN_NATIVE_EVIDENCE_NONCE").ok()?;
        if !valid_configuration(&path, &nonce) {
            return None;
        }
        Some(Self {
            started,
            path,
            nonce,
            points: [None; PHASES.len()],
        })
    }

    pub(crate) fn point(&mut self, index: usize) {
        self.points[index] = Some(self.started.elapsed().as_nanos());
    }

    pub(crate) fn write(self) {
        let mut phases = serde_json::Map::new();
        for (name, value) in PHASES.into_iter().zip(self.points) {
            if let Some(value) = value {
                phases.insert(name.into(), json!(value.to_string()));
            }
        }
        let record = json!({"stage": "host-startup-phases", "nonce": self.nonce,
            "pid": std::process::id(), "clock": "host_monotonic_relative",
            "phases_ns": phases});
        let line = format!("{record}\n");
        let result = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.path)
            .and_then(|mut file| file.write_all(line.as_bytes()));
        if result.is_err() {
            let _ = writeln!(
                std::io::stderr().lock(),
                "Bun Native host startup evidence unavailable"
            );
        }
    }
}

fn valid_configuration(path: &std::path::Path, nonce: &str) -> bool {
    path.is_absolute()
        && !nonce.is_empty()
        && nonce.len() <= 128
        && !nonce.chars().any(char::is_control)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configuration_requires_an_absolute_path_and_bounded_correlation() {
        let absolute = std::env::temp_dir().join("host-startup.jsonl");
        assert!(valid_configuration(&absolute, "correlation"));
        assert!(!valid_configuration(
            std::path::Path::new("relative"),
            "correlation"
        ));
        assert!(!valid_configuration(&absolute, ""));
        assert!(!valid_configuration(&absolute, &"a".repeat(129)));
        assert!(!valid_configuration(&absolute, "line\nbreak"));
    }

    #[test]
    fn writes_one_correlated_record_with_ordered_phase_times() {
        let path = std::env::temp_dir().join(format!(
            "bun-native-host-startup-{}-{:?}.jsonl",
            std::process::id(),
            std::thread::current().id()
        ));
        let mut trace = HostStartup {
            started: Instant::now(),
            path: path.clone(),
            nonce: "test-correlation".into(),
            points: [None; PHASES.len()],
        };
        for index in 0..PHASES.len() {
            trace.point(index);
        }
        trace.write();
        let data = std::fs::read_to_string(&path).unwrap();
        std::fs::remove_file(path).unwrap();
        assert_eq!(data.lines().count(), 1);
        let record: serde_json::Value = serde_json::from_str(&data).unwrap();
        assert_eq!(record["stage"], "host-startup-phases");
        assert_eq!(record["nonce"], "test-correlation");
        assert_eq!(record["pid"], std::process::id());
        let phases = record["phases_ns"].as_object().unwrap();
        assert_eq!(phases.len(), PHASES.len());
        let values: Vec<u128> = PHASES
            .iter()
            .map(|name| phases[*name].as_str().unwrap().parse().unwrap())
            .collect();
        assert!(values.windows(2).all(|pair| pair[0] <= pair[1]));
    }
}
