use futures_util::StreamExt;
use librespot::{
    connect::{ConnectConfig, LoadRequest, LoadRequestOptions, PlayingTrack, Spirc},
    core::{Session, SessionConfig, authentication::Credentials, cache::Cache},
    discovery::Discovery,
    metadata::audio::UniqueFields,
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

fn start_control_server(path: PathBuf, handle: Arc<Mutex<Option<Spirc>>>) -> std::io::Result<()> {
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
            let result = connection
                .read_to_string(&mut request)
                .map_err(|error| error.to_string())
                .and_then(|_| dispatch(&handle, request.trim()));
            let response = match result {
                Ok(()) => "ok\n".to_string(),
                Err(error) => format!("error {error}\n"),
            };
            let _ = connection.write_all(response.as_bytes());
        }
    });
    Ok(())
}

fn dispatch(handle: &Arc<Mutex<Option<Spirc>>>, request: &str) -> Result<(), String> {
    let mut parts = request.split_whitespace();
    let command = parts.next().ok_or("empty command")?;
    let guard = handle.lock().map_err(|_| "control lock poisoned")?;
    let spirc = guard.as_ref().ok_or("player is not connected")?;
    let result = match command {
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
    result.map_err(|error| error.to_string())
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
        PlayerEvent::Stopped { track_id, .. } => {
            put("PLAYER_EVENT", "stopped".into());
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
    start_event_relay(player.get_player_event_channel(), event_path);

    let credentials = match cache.credentials() {
        Some(credentials) => credentials,
        None => oauth_credentials(&session_config.client_id)?,
    };
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

    let (spirc, spirc_task) =
        Spirc::new(connect_config, session.clone(), credentials, player, mixer).await?;
    let handle = Arc::new(Mutex::new(Some(spirc)));
    start_control_server(control_path.clone(), handle.clone())?;
    println!("spotifier-player ready: {}", control_path.display());

    tokio::pin!(spirc_task);
    loop {
        tokio::select! {
            _ = &mut spirc_task => return Err("Spotify Connect session stopped".into()),
            _ = tokio::signal::ctrl_c() => break,
            credentials = discovery.next() => {
                if credentials.is_none() {
                    return Err("Spotify discovery stopped".into());
                }
            }
        }
    }
    if let Some(spirc) = handle.lock().ok().and_then(|mut guard| guard.take()) {
        let _ = spirc.shutdown();
    }
    let _ = fs::remove_file(control_path);
    Ok(())
}

fn oauth_credentials(client_id: &str) -> Result<Credentials, Box<dyn std::error::Error>> {
    let client =
        OAuthClientBuilder::new(client_id, "http://127.0.0.1/login", OAUTH_SCOPES.to_vec())
            .open_in_browser()
            .build()?;
    let token = client.get_access_token()?;
    Ok(Credentials::with_access_token(token.access_token))
}
