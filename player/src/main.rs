use futures_util::StreamExt;
use librespot::{
    connect::{
        ConnectConfig, LoadContextOptions, LoadRequest, LoadRequestOptions, Options, PlayingTrack,
        Spirc,
    },
    core::{Session, SessionConfig, SpotifyId, authentication::Credentials, cache::Cache},
    discovery::Discovery,
    metadata::audio::UniqueFields,
    metadata::{Lyrics, lyrics::SyncType},
    playback::{
        audio_backend,
        config::{AudioFormat, PlayerConfig},
        mixer::{self, MixerConfig},
        player::{Player, PlayerEvent},
    },
};
use librespot_oauth::OAuthClientBuilder;
use serde_json::{Map, Value, json};
use sha1::{Digest, Sha1};
use std::{
    env, fs,
    io::{Read, Write},
    os::unix::net::{UnixDatagram, UnixListener},
    path::PathBuf,
    sync::{Arc, Mutex},
    thread,
};

const OAUTH_SCOPES: &[&str] = &[
    "app-remote-control",
    "playlist-modify",
    "playlist-modify-private",
    "playlist-read-private",
    "playlist-read-collaborative",
    "streaming",
    "ugc-image-upload",
    "user-follow-modify",
    "user-follow-read",
    "user-library-modify",
    "user-library-read",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-email",
    "user-read-playback-position",
    "user-read-playback-state",
    "user-read-private",
    "user-read-recently-played",
    "user-top-read",
];

fn setting(name: &str, fallback: &str) -> String {
    env::var(name).unwrap_or_else(|_| fallback.to_string())
}

fn device_id(name: &str) -> String {
    format!("{:x}", Sha1::digest(name.as_bytes()))
}

fn start_control_server(
    path: PathBuf,
    handle: Arc<Mutex<Option<Spirc>>>,
    session: Session,
    runtime: tokio::runtime::Handle,
) -> std::io::Result<()> {
    if path.exists() {
        fs::remove_file(&path)?;
    }
    let listener = UnixListener::bind(&path)?;
    thread::spawn(move || {
        for connection in listener.incoming() {
            let Ok(mut connection) = connection else {
                continue;
            };
            let mut request = String::new();
            if let Err(error) = connection.read_to_string(&mut request) {
                write_control_response(connection, Err(error.to_string()));
                continue;
            }
            if request.trim_start().starts_with("lyrics ") {
                let handle = handle.clone();
                let session = session.clone();
                let runtime = runtime.clone();
                thread::spawn(move || {
                    let result = dispatch(&handle, &session, &runtime, request.trim());
                    write_control_response(connection, result);
                });
            } else {
                let result = dispatch(&handle, &session, &runtime, request.trim());
                write_control_response(connection, result);
            }
        }
    });
    Ok(())
}

fn write_control_response(
    mut connection: std::os::unix::net::UnixStream,
    result: Result<String, String>,
) {
    let response = match result {
        Ok(value) => format!("{value}\n"),
        Err(error) => format!("error {error}\n"),
    };
    let _ = connection.write_all(response.as_bytes());
}

fn dispatch(
    handle: &Arc<Mutex<Option<Spirc>>>,
    session: &Session,
    runtime: &tokio::runtime::Handle,
    request: &str,
) -> Result<String, String> {
    if session.is_invalid() {
        return Err("Spotify connection lost; reconnecting".to_owned());
    }
    let mut parts = request.split_whitespace();
    let command = parts.next().ok_or("empty command")?;
    if command == "lyrics" {
        let id = SpotifyId::from_base62(parts.next().ok_or("missing track id")?)
            .map_err(|error| error.to_string())?;
        let lyrics = runtime
            .block_on(Lyrics::get(session, &id))
            .map_err(|error| error.to_string())?;
        let synced = matches!(lyrics.lyrics.sync_type, SyncType::LineSynced);
        return Ok(json!({
            "provider": lyrics.lyrics.provider_display_name,
            "synced": synced,
            "lines": lyrics.lyrics.lines.into_iter().map(|line| json!({
                "time_ms": line.start_time_ms.parse::<u64>().unwrap_or(0),
                "text": line.words,
            })).collect::<Vec<_>>(),
        })
        .to_string());
    }

    let guard = handle.lock().map_err(|_| "control lock poisoned")?;
    let spirc = guard.as_ref().ok_or("player is not connected")?;
    let result = match command {
        "disconnect" => spirc.disconnect(true),
        "play" => spirc.play(),
        "pause" => spirc.pause(),
        "play_pause" => spirc.play_pause(),
        "load" => {
            let uri = parts.next().ok_or("missing uri")?.to_string();
            let context = parts.next().map(str::to_string);
            let mut options = LoadRequestOptions {
                start_playing: true,
                ..LoadRequestOptions::default()
            };
            let request = if let Some(context_uri) = context {
                options.playing_track = Some(PlayingTrack::Uri(uri));
                LoadRequest::from_context_uri(context_uri, options)
            } else if uri.starts_with("spotify:track:") || uri.starts_with("spotify:episode:") {
                LoadRequest::from_tracks(vec![uri], options)
            } else {
                LoadRequest::from_context_uri(uri, options)
            };
            spirc.activate().and_then(|_| spirc.load(request))
        }
        "restore" => {
            let saved: Value = serde_json::from_str(
                request
                    .strip_prefix("restore ")
                    .ok_or("missing recovery state")?,
            )
            .map_err(|error| error.to_string())?;
            let uri = saved["uri"]
                .as_str()
                .ok_or("missing recovery uri")?
                .to_owned();
            let context = saved["context_uri"].as_str().unwrap_or("");
            let mode = saved["repeat_mode"].as_str().unwrap_or("None");
            let options = LoadRequestOptions {
                start_playing: saved["playing"].as_bool().ok_or("missing playback state")?,
                seek_to: saved["position_ms"]
                    .as_u64()
                    .ok_or("missing position")?
                    .min(u32::MAX as u64) as u32,
                context_options: Some(LoadContextOptions::Options(Options {
                    shuffle: saved["shuffle"].as_bool().unwrap_or(false),
                    repeat: mode == "Playlist",
                    repeat_track: mode == "Track",
                })),
                playing_track: if context.is_empty() {
                    None
                } else {
                    Some(PlayingTrack::Uri(uri.clone()))
                },
            };
            let load = if context.is_empty() {
                LoadRequest::from_tracks(vec![uri], options)
            } else {
                LoadRequest::from_context_uri(context.to_owned(), options)
            };
            let volume = saved["volume"]
                .as_u64()
                .ok_or("missing volume")?
                .min(u16::MAX as u64) as u16;
            spirc
                .activate()
                .and_then(|_| spirc.set_volume(volume))
                .and_then(|_| spirc.load(load))
        }
        "repeat_mode" => {
            let mode = parts.next().ok_or("missing repeat mode")?;
            match mode {
                "None" => spirc.repeat_track(false).and_then(|_| spirc.repeat(false)),
                "Playlist" => spirc.repeat_track(false).and_then(|_| spirc.repeat(true)),
                "Track" => spirc.repeat_track(true),
                _ => return Err("invalid repeat mode".into()),
            }
        }
        "next" => spirc.next(),
        "previous" => spirc.prev(),
        "seek" => spirc.set_position_ms(parse(parts.next(), "position")?),
        "volume" => spirc.set_volume(parse(parts.next(), "volume")?),
        "shuffle" => spirc.shuffle(parse_bool(parts.next())?),
        "repeat" => spirc.repeat(parse_bool(parts.next())?),
        "repeat_track" => spirc.repeat_track(parse_bool(parts.next())?),
        _ => return Err(format!("unknown command: {command}")),
    };
    result
        .map(|_| "ok".to_string())
        .map_err(|error| error.to_string())
}

fn parse<T: std::str::FromStr>(value: Option<&str>, name: &str) -> Result<T, String> {
    value
        .ok_or_else(|| format!("missing {name}"))?
        .parse()
        .map_err(|_| format!("invalid {name}"))
}

fn parse_bool(value: Option<&str>) -> Result<bool, String> {
    match value {
        Some("true") => Ok(true),
        Some("false") => Ok(false),
        _ => Err("invalid boolean".to_string()),
    }
}

fn start_event_relay(mut events: librespot::playback::player::PlayerEventChannel, path: PathBuf) {
    thread::spawn(move || {
        let socket = UnixDatagram::unbound().expect("create event socket");
        while let Some(event) = events.blocking_recv() {
            if let Some(payload) = event_payload(event) {
                let _ = socket.send_to(payload.to_string().as_bytes(), &path);
            }
        }
    });
}

fn event_payload(event: PlayerEvent) -> Option<Value> {
    let mut data = Map::new();
    let mut put = |key: &str, value: String| {
        data.insert(key.to_string(), Value::String(value));
    };
    match event {
        PlayerEvent::TrackChanged { audio_item } => {
            put("PLAYER_EVENT", "track_changed".into());
            put("TRACK_ID", audio_item.track_id.to_id().ok()?);
            put("URI", audio_item.uri);
            put("NAME", audio_item.name);
            put(
                "COVERS",
                audio_item
                    .covers
                    .into_iter()
                    .map(|cover| cover.url)
                    .collect::<Vec<_>>()
                    .join("\n"),
            );
            put("DURATION_MS", audio_item.duration_ms.to_string());
            if let UniqueFields::Track { artists, album, .. } = audio_item.unique_fields {
                put(
                    "ARTISTS",
                    artists
                        .0
                        .into_iter()
                        .map(|artist| artist.name)
                        .collect::<Vec<_>>()
                        .join("\n"),
                );
                put("ALBUM", album);
            }
        }
        PlayerEvent::Playing {
            track_id,
            position_ms,
            ..
        } => position_event(&mut data, "playing", track_id, position_ms)?,
        PlayerEvent::Paused {
            track_id,
            position_ms,
            ..
        } => position_event(&mut data, "paused", track_id, position_ms)?,
        PlayerEvent::Seeked {
            track_id,
            position_ms,
            ..
        } => position_event(&mut data, "seeked", track_id, position_ms)?,
        PlayerEvent::PositionCorrection {
            track_id,
            position_ms,
            ..
        } => position_event(&mut data, "position_correction", track_id, position_ms)?,
        PlayerEvent::SessionDisconnected { .. } => {
            put("PLAYER_EVENT", "session_disconnected".into());
        }
        PlayerEvent::Stopped { track_id, .. } => {
            put("PLAYER_EVENT", "stopped".into());
            put("TRACK_ID", track_id.to_id().ok()?);
        }
        PlayerEvent::Unavailable { track_id, .. } => {
            put("PLAYER_EVENT", "unavailable".into());
            put("TRACK_ID", track_id.to_id().ok()?);
        }
        PlayerEvent::VolumeChanged { volume } => {
            put("PLAYER_EVENT", "volume_changed".into());
            put("VOLUME", volume.to_string());
        }
        PlayerEvent::ShuffleChanged { shuffle } => {
            put("PLAYER_EVENT", "shuffle_changed".into());
            put("SHUFFLE", shuffle.to_string());
        }
        PlayerEvent::RepeatChanged { context, track } => {
            put("PLAYER_EVENT", "repeat_changed".into());
            put("REPEAT", context.to_string());
            put("REPEAT_TRACK", track.to_string());
        }
        _ => return None,
    }
    Some(Value::Object(data))
}

fn position_event(
    data: &mut Map<String, Value>,
    name: &str,
    track_id: librespot::core::SpotifyUri,
    position_ms: u32,
) -> Option<()> {
    data.insert("PLAYER_EVENT".into(), json!(name));
    data.insert("TRACK_ID".into(), json!(track_id.to_id().ok()?));
    data.insert("POSITION_MS".into(), json!(position_ms.to_string()));
    Some(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    env_logger::init();
    let name = setting("SPOTIFIER_DEVICE_NAME", "Spotifier");
    let cache_path = PathBuf::from(setting("SPOTIFIER_CACHE", "/tmp/spotifier-cache"));
    let control_path = PathBuf::from(setting(
        "SPOTIFIER_CONTROL_SOCKET",
        "/tmp/spotifier-control.sock",
    ));
    let event_path = PathBuf::from(setting(
        "SPOTIFIER_EVENT_SOCKET",
        "/tmp/spotifier-events.sock",
    ));
    let zeroconf_port: u16 = setting("SPOTIFIER_ZEROCONF_PORT", "8766").parse()?;

    fs::create_dir_all(&cache_path)?;
    let cache = Cache::new(
        Some(cache_path.clone()),
        Some(cache_path.clone()),
        Some(cache_path.join("files")),
        None,
    )?;
    let mut session_config = SessionConfig::default();
    session_config.device_id = device_id(&name);
    let mut connect_config = ConnectConfig::default();
    connect_config.name = name.clone();
    if let Some(volume) = cache.volume() {
        connect_config.initial_volume = volume;
    }

    let credentials = match cache.credentials() {
        Some(credentials) => credentials,
        None => oauth_credentials(&session_config.client_id)?,
    };

    let backend = audio_backend::find(None).ok_or("no audio backend")?;
    let mixer_builder = mixer::find(Some("softvol")).ok_or("softvol mixer unavailable")?;
    let mixer = mixer_builder(MixerConfig::default())?;
    let mut player_config = PlayerConfig::default();
    player_config.normalisation = true;

    let session = Session::new(session_config.clone(), Some(cache.clone()));
    let player = Player::new(
        player_config,
        session.clone(),
        mixer.get_soft_volume(),
        move || backend(None, AudioFormat::S16),
    );
    let events = player.get_player_event_channel();

    let discovery_backend = librespot::discovery::find(None)?;
    let mut discovery = Discovery::builder(
        session_config.device_id.clone(),
        session_config.client_id.clone(),
    )
    .name(name)
    .device_type(connect_config.device_type)
    .port(zeroconf_port)
    .zeroconf_backend(discovery_backend)
    .launch()?;

    // Every exit after discovery starts must join its blocking worker while
    // Tokio can still run the mDNS responder. Dropping the runtime first makes
    // libmdns panic when its destructors send to the cancelled responder.
    let result = async {
        let (spirc, spirc_task) =
            Spirc::new(connect_config, session.clone(), credentials, player, mixer).await?;
        let handle = Arc::new(Mutex::new(Some(spirc)));
        let result = async {
            start_event_relay(events, event_path);
            start_control_server(
                control_path.clone(),
                handle.clone(),
                session.clone(),
                tokio::runtime::Handle::current(),
            )?;
            println!("spotifier-player ready: {}", control_path.display());

            let mut terminate =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
            tokio::pin!(spirc_task);
            let disconnected = wait_for_disconnect(&session);
            tokio::pin!(disconnected);
            loop {
                tokio::select! {
                    _ = &mut spirc_task => return Err("Spotify Connect session stopped".into()),
                    _ = &mut disconnected => return Err("Spotify connection lost".into()),
                    signal = tokio::signal::ctrl_c() => {
                        signal?;
                        break;
                    }
                    _ = terminate.recv() => break,
                    credentials = discovery.next() => {
                        if credentials.is_none() {
                            return Err("Spotify discovery stopped".into());
                        }
                    }
                }
            }
            Ok(())
        }
        .await;
        if let Some(spirc) = handle.lock().ok().and_then(|mut guard| guard.take()) {
            let _ = spirc.shutdown();
        }
        let _ = fs::remove_file(control_path);
        result
    }
    .await;
    discovery.shutdown().await;
    result
}

// Spirc can remain blocked waiting for a command after the underlying session
// dies. Exit independently so the daemon's supervisor can reconnect the player.
async fn wait_for_disconnect(session: &Session) {
    while !session.is_invalid() {
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    }
}

fn oauth_credentials(client_id: &str) -> Result<Credentials, Box<dyn std::error::Error>> {
    let client = OAuthClientBuilder::new(
        client_id,
        "http://127.0.0.1:8890/login",
        OAUTH_SCOPES.to_vec(),
    )
    .build()?;
    let token = client.get_access_token()?;
    Ok(Credentials::with_access_token(token.access_token))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn disconnected_session_exits_and_rejects_commands() {
        let session = Session::new(SessionConfig::default(), None);
        assert!(
            tokio::time::timeout(
                std::time::Duration::from_millis(20),
                wait_for_disconnect(&session),
            )
            .await
            .is_err()
        );
        session.shutdown();
        tokio::time::timeout(
            std::time::Duration::from_millis(100),
            wait_for_disconnect(&session),
        )
        .await
        .expect("invalid session should exit without waiting for Spirc");
        let result = dispatch(
            &Arc::new(Mutex::new(None)),
            &session,
            &tokio::runtime::Handle::current(),
            "play",
        );
        assert_eq!(result.unwrap_err(), "Spotify connection lost; reconnecting");
    }

    #[test]
    fn device_deactivation_is_relayed_without_exposing_account_details() {
        let event = event_payload(PlayerEvent::SessionDisconnected {
            connection_id: "test-connection".into(),
            user_name: "test-user".into(),
        })
        .unwrap();
        assert_eq!(event, json!({"PLAYER_EVENT": "session_disconnected"}));
    }

    // Exercise the real libmdns blocking worker on the same runtime flavor as
    // main. A teardown regression aborts the test process rather than unwinding.
    #[test]
    fn discovery_shutdown_completes_before_runtime_drop() {
        for _ in 0..10 {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .unwrap();
            runtime.block_on(async {
                let discovery = Discovery::builder(
                    "spotifier-shutdown-test".to_owned(),
                    "spotifier-shutdown-test".to_owned(),
                )
                .name("Spotifier shutdown test".to_owned())
                .port(0)
                .zeroconf_backend(librespot::discovery::find(Some("libmdns")).unwrap())
                .launch()
                .unwrap();
                tokio::task::yield_now().await;
                discovery.shutdown().await;
            });
            drop(runtime);
        }
    }
}
