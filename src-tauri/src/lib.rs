//! Tauri v2 desktop shell for coin-finder.
//!
//! Wraps the existing Flask web app (`web/app.py`, frozen by PyInstaller
//! into a `--onedir` build, see
//! `packaging/pyinstaller/coin_finder_ui.spec`) as a sidecar process and
//! shows it in a native window. See `frontend/loading.html` for the
//! poll-then-navigate half of this story; this file owns:
//!
//! - port-collision detection (is something already bound to
//!   127.0.0.1:5050, e.g. a terminal `python web/app.py`?) before ever
//!   spawning our own sidecar,
//! - spawning the sidecar in the background without blocking `setup()`,
//! - detecting an unexpected sidecar exit and surfacing an explicit error
//!   state in the webview (never a silent hang), and
//! - killing the sidecar cleanly on app quit.
//!
//! Directly modeled on this author's `cleanup-tools` desktop shell, which
//! uses the exact same pattern for the same reason (a Flask sidecar frozen
//! with PyInstaller's `--onedir` mode).

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Matches `LOCALHOST` in `packaging/pyinstaller/entrypoint.py` -- the
/// Flask app is hard-bound to 127.0.0.1 only (see `web/app.py`'s
/// `create_app` host guard), so this is the one host we ever probe or
/// spawn against.
pub const SIDECAR_HOST: &str = "127.0.0.1";
/// Matches `DEFAULT_PORT` in `packaging/pyinstaller/entrypoint.py` and
/// `web/app.py`'s own `--port` default.
pub const SIDECAR_PORT: u16 = 5050;
/// Must match the `externalBin`/capabilities entry name in
/// `tauri.conf.json` / `capabilities/default.json` (filename only, no
/// path, no target-triple suffix).
const SIDECAR_NAME: &str = "coin-finder-sidecar";
/// Short and cheap on purpose: this fires on every app launch (including
/// the common case where nothing is listening yet and we're about to
/// spawn our own sidecar), so it must not make a normal cold start feel
/// slow while still giving a real, already-running instance enough time to
/// answer.
const HEALTHZ_PROBE_TIMEOUT: Duration = Duration::from_millis(800);

pub fn healthz_url(host: &str, port: u16) -> String {
    format!("http://{host}:{port}/healthz")
}

pub fn app_url(host: &str, port: u16) -> String {
    format!("http://{host}:{port}/")
}

/// True for navigation the window should perform itself: the bundled
/// `tauri://localhost/loading.html` page, or any page served by our own
/// sidecar (every route the Flask app renders is a same-origin full-page
/// navigation, not an SPA, so this has to cover the whole app, not just the
/// first load). Anything else -- rclone.org, github.com, electrum.org, any
/// external link this app ever renders -- is not.
///
/// This intentionally does NOT depend on `window.__TAURI__` being injected
/// into the sidecar's page. It isn't: Tauri only injects the IPC bridge
/// into origins it trusts by default, and `http://127.0.0.1:5050` (a plain
/// remote-looking origin as far as the webview is concerned, even though
/// it's our own sidecar) doesn't qualify without extra config that has its
/// own known bugs matching bare IP addresses
/// (https://github.com/tauri-apps/tauri/issues/7009). Deciding this in
/// Rust via `on_navigation` sidesteps that whole class of bug -- it runs
/// regardless of what JS is or isn't available on the page.
pub fn is_internal_navigation(url: &tauri::Url) -> bool {
    url.scheme() == "tauri"
        || (url.host_str() == Some(SIDECAR_HOST) && url.port() == Some(SIDECAR_PORT))
}

/// Cheap liveness probe against the sidecar's `/healthz` route (see
/// `web/app.py`'s `healthz()` -- deliberately zero I/O).
pub fn check_healthz(url: &str, timeout: Duration) -> bool {
    let config = ureq::Agent::config_builder()
        .timeout_global(Some(timeout))
        .build();
    let agent: ureq::Agent = config.into();
    matches!(agent.get(url).call(), Ok(response) if response.status().is_success())
}

/// Shared handle to the sidecar child process, if this app instance
/// spawned one (it may not have -- see the port-collision path in
/// `spawn_sidecar_in_background`, which deliberately leaves this `None`
/// when an existing instance is already answering `/healthz`).
#[derive(Default, Clone)]
pub struct SidecarState {
    child: Arc<Mutex<Option<CommandChild>>>,
    /// Set right before we deliberately kill the child ourselves (app
    /// quit) so the `CommandEvent::Terminated` handler can tell "we did
    /// this on purpose" apart from "it crashed on its own" -- only the
    /// latter should navigate the webview to an error state.
    shutting_down: Arc<AtomicBool>,
}

impl SidecarState {
    pub fn store(&self, child: CommandChild) {
        *self.child.lock().unwrap() = Some(child);
    }

    pub fn begin_shutdown(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
    }

    pub fn is_shutting_down(&self) -> bool {
        self.shutting_down.load(Ordering::SeqCst)
    }

    /// Takes ownership of the tracked child (if any), leaving `None`
    /// behind. `CommandChild::kill` consumes `self` (it's not `&self`),
    /// so a shared reference alone can't kill it -- the caller needs
    /// ownership, taken out of the `Mutex` here.
    pub fn take(&self) -> Option<CommandChild> {
        self.child.lock().unwrap().take()
    }
}

/// Forces the webview to a bundled (not Flask-served) error state.
///
/// Deliberately uses `WebviewWindow::navigate` from the Rust side rather
/// than emitting a Tauri event for `frontend/loading.html`'s JS to listen
/// for: by the time a crash can happen, the webview has very likely
/// already navigated away from `loading.html` to the real Flask UI at
/// `http://127.0.0.1:5050/` (a different origin) -- so a JS-side listener
/// would silently stop working at exactly the moment it's needed.
/// `navigate()` works regardless of the webview's current page/origin.
fn navigate_to_error(app: &AppHandle, reason: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let target = format!("tauri://localhost/loading.html?error={reason}");
        match tauri::Url::parse(&target) {
            Ok(url) => {
                if let Err(err) = window.navigate(url) {
                    eprintln!("coin-finder: failed to navigate to error state: {err}");
                }
            }
            Err(err) => eprintln!("coin-finder: failed to build error url: {err}"),
        }
    }
}

/// Port-collision check, then (only if needed) spawn the sidecar -- all on
/// a background OS thread so `setup()` returns immediately (blocking it on
/// sidecar readiness would leave the whole app looking hung -- no window,
/// no Dock icon -- for however long startup takes).
fn spawn_sidecar_in_background(app: AppHandle, state: SidecarState) {
    std::thread::spawn(move || {
        let healthz = healthz_url(SIDECAR_HOST, SIDECAR_PORT);

        if check_healthz(&healthz, HEALTHZ_PROBE_TIMEOUT) {
            // Something -- most likely a terminal `python web/app.py` --
            // is already bound to 127.0.0.1:5050 and answering /healthz.
            // Do NOT spawn a second Flask process: it would fail to bind
            // the port anyway, and frontend/loading.html's own poll loop
            // will see the healthy endpoint and navigate straight to the
            // existing instance on its own, with no help needed from us
            // here.
            eprintln!(
                "coin-finder: existing instance already answering on \
                 {SIDECAR_HOST}:{SIDECAR_PORT}, not spawning a sidecar"
            );
            return;
        }

        let sidecar_command = match app.shell().sidecar(SIDECAR_NAME) {
            Ok(cmd) => cmd,
            Err(err) => {
                eprintln!("coin-finder: failed to resolve sidecar {SIDECAR_NAME}: {err}");
                navigate_to_error(&app, "spawn_failed");
                return;
            }
        };

        let spawn_result = sidecar_command
            .args([SIDECAR_PORT.to_string(), SIDECAR_HOST.to_string()])
            .spawn();

        let (mut rx, child) = match spawn_result {
            Ok(pair) => pair,
            Err(err) => {
                eprintln!("coin-finder: failed to spawn sidecar: {err}");
                navigate_to_error(&app, "spawn_failed");
                return;
            }
        };

        eprintln!("coin-finder: spawned sidecar, pid={}", child.pid());
        state.store(child);

        // Drain the sidecar's stdout/stderr/lifecycle events for as long
        // as the process lives. This is also the crash-detection path: an
        // unexpected `CommandEvent::Terminated` (one we didn't cause via
        // `SidecarState::begin_shutdown`) means the sidecar died on its
        // own while the app was open, which must surface as an explicit
        // error state, never a silent hang or blank page.
        let app_for_events = app.clone();
        let state_for_events = state.clone();
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Terminated(payload) => {
                        if !state_for_events.is_shutting_down() {
                            eprintln!(
                                "coin-finder: sidecar exited unexpectedly \
                                 (code={:?}, signal={:?})",
                                payload.code, payload.signal
                            );
                            navigate_to_error(&app_for_events, "exited");
                        }
                        break;
                    }
                    CommandEvent::Error(err) => {
                        eprintln!("coin-finder: sidecar reported an error: {err}");
                    }
                    CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                        if let Ok(text) = String::from_utf8(bytes) {
                            eprintln!("coin-finder-sidecar: {text}");
                        }
                    }
                    _ => {}
                }
            }
        });
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_state = SidecarState::default();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(sidecar_state.clone())
        .setup(move |app| {
            // Built imperatively (not via tauri.conf.json's `windows`
            // array) specifically so `on_navigation` can be attached --
            // that hook is builder-only, there's no way to bolt it onto a
            // window Tauri auto-created from config. This is also the
            // fix for a real bug hit in testing: an external link
            // (rclone.org) opened *inside* this window with no way back,
            // because the old fix relied on JS calling
            // `window.__TAURI__.opener.openUrl()`, and that bridge was
            // never actually present on the sidecar's origin. Blocking
            // and redirecting non-internal navigation here in Rust
            // doesn't have that dependency.
            let nav_app_handle = app.handle().clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("loading.html".into()))
                .title("Coin Finder")
                .inner_size(1200.0, 850.0)
                .on_navigation(move |url| {
                    if is_internal_navigation(url) {
                        return true;
                    }
                    if let Err(err) = nav_app_handle
                        .opener()
                        .open_url(url.to_string(), None::<&str>)
                    {
                        eprintln!(
                            "coin-finder: failed to open external url {url} in browser: {err}"
                        );
                    }
                    false
                })
                .build()?;

            // Must return immediately -- see spawn_sidecar_in_background's
            // doc comment.
            spawn_sidecar_in_background(app.handle().clone(), sidecar_state.clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(move |app_handle, event| {
            // A normal macOS app quit does not reliably emit
            // `RunEvent::ExitRequested` -- only a bare `RunEvent::Exit`
            // fires for a Cmd+Q/Dock "Quit" (verified on this author's
            // other Tauri app, cleanup-tools, via direct `ps`/`lsof`
            // observation). Handling shutdown on BOTH events avoids
            // leaving the sidecar running as an orphan after a normal
            // quit; `SidecarState::take()` makes a second call a harmless
            // no-op if both somehow fire for the same quit.
            let is_quit = matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            );
            if is_quit {
                let state = app_handle.state::<SidecarState>();
                state.begin_shutdown();
                if let Some(child) = state.take() {
                    let pid = child.pid();
                    match child.kill() {
                        Ok(()) => eprintln!("coin-finder: sent kill to sidecar pid {pid} on quit"),
                        Err(err) => {
                            eprintln!("coin-finder: failed to kill sidecar pid {pid} on quit: {err}")
                        }
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    #[test]
    fn healthz_url_matches_flask_route() {
        assert_eq!(healthz_url("127.0.0.1", 5050), "http://127.0.0.1:5050/healthz");
    }

    #[test]
    fn app_url_matches_flask_root() {
        assert_eq!(app_url("127.0.0.1", 5050), "http://127.0.0.1:5050/");
    }

    #[test]
    fn internal_navigation_allows_bundled_loading_page() {
        let url = tauri::Url::parse("tauri://localhost/loading.html").unwrap();
        assert!(is_internal_navigation(&url));
    }

    #[test]
    fn internal_navigation_allows_sidecar_origin() {
        let url = tauri::Url::parse("http://127.0.0.1:5050/mounts").unwrap();
        assert!(is_internal_navigation(&url));
    }

    #[test]
    fn internal_navigation_rejects_external_host() {
        let url = tauri::Url::parse("https://rclone.org/").unwrap();
        assert!(!is_internal_navigation(&url));
    }

    #[test]
    fn internal_navigation_rejects_localhost_wrong_port() {
        let url = tauri::Url::parse("http://127.0.0.1:9999/").unwrap();
        assert!(!is_internal_navigation(&url));
    }

    fn spawn_fake_healthz_server(status_line: &'static str) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
        let addr = listener.local_addr().expect("local addr");
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 1024];
                let _ = stream.read(&mut buf);
                let body = b"{\"status\":\"ok\"}";
                let response = format!(
                    "{status_line}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.write_all(body);
                let _ = stream.flush();
            }
        });
        format!("http://{addr}/healthz")
    }

    #[test]
    fn check_healthz_true_on_200() {
        let url = spawn_fake_healthz_server("HTTP/1.1 200 OK");
        assert!(check_healthz(&url, Duration::from_secs(2)));
    }

    #[test]
    fn check_healthz_false_on_non_2xx() {
        let url = spawn_fake_healthz_server("HTTP/1.1 500 Internal Server Error");
        assert!(!check_healthz(&url, Duration::from_secs(2)));
    }

    #[test]
    fn check_healthz_false_on_connection_refused() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
        let addr = listener.local_addr().expect("local addr");
        drop(listener);

        let url = format!("http://{addr}/healthz");
        assert!(!check_healthz(&url, Duration::from_millis(500)));
    }

    #[test]
    fn sidecar_state_tracks_shutdown_intent() {
        let state = SidecarState::default();
        assert!(!state.is_shutting_down());
        state.begin_shutdown();
        assert!(state.is_shutting_down());
    }

    #[test]
    fn sidecar_state_take_returns_none_when_empty() {
        let state = SidecarState::default();
        assert!(state.take().is_none());
    }
}
