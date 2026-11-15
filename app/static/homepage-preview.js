const HLS_SRC = "/preview/hls/cam-preview/index.m3u8";
const THUMBNAIL_SRC = "/preview-thumbnail.jpg";
const START_DELAY_MS = 2000;
const THUMBNAIL_REFRESH_MS = 10000;

// User-facing text, kept together for a later translation pass.
const STRINGS = {
  loadPreview: "Load Preview",
  stopPreview: "Stop Preview",
  starting: "Starting...",
  stopping: "Stopping...",
  wakingEncoder: "Waking the encoder...",
  chipPreview: "Preview",
  chipLive: "Live",
  chipStarting: "Starting",
  streamDropped: "Preview stream dropped. Reload to retry.",
  startFailed: (status) => `The preview could not start (HTTP ${status}). Wait a moment and try again.`,
  networkError: "The preview could not start. Check the network and try again.",
  hlsUnsupported: "This browser cannot play the live preview.",
};

let hls = null;
let state = "idle";

function setChip(kind, text) {
  const chip = document.getElementById("preview-chip");
  chip.className = `status-chip status-chip--${kind}`;
  chip.textContent = text;
}

function setThumbnailAvailable(available) {
  document.getElementById("preview-thumbnail").hidden = !available;
  document.getElementById("preview-empty").hidden = available;
}

function refreshThumbnail() {
  document.getElementById("preview-thumbnail").src = `${THUMBNAIL_SRC}?t=${Date.now()}`;
}

function showThumbnail() {
  refreshThumbnail();
  document.getElementById("preview-video").hidden = true;
  document.getElementById("preview-thumbnail").hidden = false;
  document.getElementById("preview-empty").hidden = true;
}

function setupThumbnail() {
  const img = document.getElementById("preview-thumbnail");
  // A late load or error must not unhide the thumbnail over a live video.
  img.addEventListener("load", () => state === "idle" && setThumbnailAvailable(true));
  img.addEventListener("error", () => state === "idle" && setThumbnailAvailable(false));
  // The image may have failed before this module ran.
  if (img.complete && img.naturalWidth === 0) {
    setThumbnailAvailable(false);
  }
  window.setInterval(() => {
    if (state === "idle" && !document.hidden) {
      refreshThumbnail();
    }
  }, THUMBNAIL_REFRESH_MS);
  document.addEventListener("visibilitychange", () => {
    if (state === "idle" && !document.hidden) {
      refreshThumbnail();
    }
  });
}

function showVideo() {
  document.getElementById("preview-thumbnail").hidden = true;
  document.getElementById("preview-empty").hidden = true;
  document.getElementById("preview-video").hidden = false;
}

function attachPlayer() {
  const video = document.getElementById("preview-video");
  if (window.Hls && window.Hls.isSupported()) {
    hls = new window.Hls({
      liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 2,
      backBufferLength: 4,
      maxLiveSyncPlaybackRate: 1.5,
    });
    hls.loadSource(HLS_SRC);
    hls.attachMedia(video);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => video.play());
    hls.on(window.Hls.Events.ERROR, (_evt, data) => {
      if (data.fatal) {
        stopPreview(STRINGS.streamDropped);
      }
    });
  } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = HLS_SRC;
    video.play();
  } else {
    throw new Error(STRINGS.hlsUnsupported);
  }
}

async function startPreview() {
  if (state !== "idle") {
    return;
  }
  state = "starting";
  const btn = document.getElementById("preview-btn");
  const msg = document.getElementById("preview-msg");
  btn.disabled = true;
  btn.textContent = STRINGS.starting;
  msg.textContent = STRINGS.wakingEncoder;
  setChip("muted", STRINGS.chipStarting);
  try {
    const resp = await fetch("/preview/start", { method: "POST" });
    if (!resp.ok) {
      throw new Error(STRINGS.startFailed(resp.status));
    }
    await new Promise((resolve) => window.setTimeout(resolve, START_DELAY_MS));
    showVideo();
    attachPlayer();
    state = "live";
    btn.disabled = false;
    btn.textContent = STRINGS.stopPreview;
    msg.textContent = "";
    setChip("live", STRINGS.chipLive);
  } catch (err) {
    state = "idle";
    btn.disabled = false;
    btn.textContent = STRINGS.loadPreview;
    msg.textContent = err instanceof TypeError ? STRINGS.networkError : err.message;
    setChip("muted", STRINGS.chipPreview);
  }
}

async function stopPreview(message = "") {
  if (state === "idle") {
    return;
  }
  state = "stopping";
  const btn = document.getElementById("preview-btn");
  const msg = document.getElementById("preview-msg");
  btn.disabled = true;
  btn.textContent = STRINGS.stopping;
  if (hls) {
    hls.destroy();
    hls = null;
  }
  const video = document.getElementById("preview-video");
  video.removeAttribute("src");
  video.load();
  try {
    await fetch("/preview/stop", { method: "POST" });
  } catch (_err) {
    // Best-effort: the encoder hibernates on its own.
  }
  showThumbnail();
  state = "idle";
  btn.disabled = false;
  btn.textContent = STRINGS.loadPreview;
  msg.textContent = message;
  setChip("muted", STRINGS.chipPreview);
}

function togglePreview() {
  if (state === "idle") {
    startPreview();
  } else if (state === "live") {
    stopPreview();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupThumbnail();
  const button = document.querySelector("[data-preview-toggle]");
  if (button) {
    button.addEventListener("click", togglePreview);
  }
});
