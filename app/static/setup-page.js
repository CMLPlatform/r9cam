import { formatRemainingTime, loadStrings } from "./i18n.js";

// English fallback; the server renders the page language into #i18n-strings.
const STRINGS = loadStrings("page", {
  copied: {
    code: "Pairing code copied.",
    url: "Backend URL copied.",
    key: "Local API key copied.",
  },
  copyFailed: {
    code: "Could not copy the pairing code. Select it and copy it by hand.",
    url: "Could not copy the backend URL. Select it and copy it by hand.",
    key: "Could not copy the local API key. Select it and copy it by hand.",
  },
  srCopied: "Copied",
  srRefreshed: "Refreshed",
  srCopyFailed: "Copy failed",
  copyDone: "Copied",
  copyFailedShort: "Copy failed",
  refreshingLabel: "Getting a new pairing code...",
  refreshedLabel: "Pairing code refreshed",
  refreshFailedLabel: "Could not get a new pairing code",
  refreshPending: "Getting a new code...",
  refreshDone: "New code ready. Reloading page...",
  refreshFailedHttp: (status) => `Could not get a new code (HTTP ${status}). Try again.`,
  refreshFailedNetwork: "Could not get a new code. Check your connection and try again.",
  codeExpired: "Code expired. Getting a new one...",
  codeExpiredWaiting: "Code expired.",
  unpairing: "Unpairing...",
  unpair: "Unpair",
  unpairDone: "Unpaired. Reloading page...",
  unpairFailedHttp: (status) => `Unpair failed (HTTP ${status}). Try again.`,
  unpairFailedNetwork: "Unpair request failed. Check your connection and try again.",
  keyRevealing: "Revealing...",
  keyFetching: "Fetching local key...",
  keyEmpty: "Local key is empty.",
  keyRevealed: "Key shown. It hides again in 60 seconds.",
  keyHidden: "Key hidden.",
  keyFailed: "Could not show the local key from this client. Sign in as an operator and try again.",
  countdownExpired: "expired",
});

const STATUS_SUCCESS_MS = 4000;
const LOCAL_KEY_VISIBLE_MS = 60000;

// One polite status line and one persistent alert line per area.
function createAnnouncer(statusId, errorId) {
  let timer = null;
  const clear = () => {
    const status = document.getElementById(statusId);
    const error = document.getElementById(errorId);
    window.clearTimeout(timer);
    if (status) {
      status.textContent = "";
      status.dataset.state = "";
    }
    if (error) {
      error.textContent = "";
    }
  };
  return {
    status(text, state) {
      const status = document.getElementById(statusId);
      if (!status) {
        return;
      }
      clear();
      status.dataset.state = state || "";
      status.textContent = text || "";
      if (text && state === "success") {
        timer = window.setTimeout(clear, STATUS_SUCCESS_MS);
      }
    },
    error(text) {
      const error = document.getElementById(errorId);
      if (!error) {
        return;
      }
      clear();
      error.textContent = text;
    },
  };
}

const pairingMessages = createAnnouncer("pairing-action-status", "pairing-action-error");
const keyMessages = createAnnouncer("local-key-status", "local-key-error");

function fallbackCopyText(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  const ok = document.execCommand("copy");
  document.body.removeChild(textarea);
  return ok;
}

function pairingButtonFeedbackSvg(state) {
  if (state === "copied" || state === "success") {
    return `
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d="M20.25 6.75 9.75 17.25 3.75 11.25" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        </svg>
        <span class="sr-only">${state === "success" ? STRINGS.srRefreshed : STRINGS.srCopied}</span>
      `;
  }
  return `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M15.75 8.25 8.25 15.75M8.25 8.25l7.5 7.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>
      </svg>
      <span class="sr-only">${STRINGS.srCopyFailed}</span>
    `;
}

function setPairingButtonFeedback(button, state, label, title) {
  if (!button) {
    return;
  }
  if (!button.dataset.defaultHtml) {
    button.dataset.defaultHtml = button.innerHTML;
  }
  button.dataset.feedbackState = state;
  button.innerHTML = pairingButtonFeedbackSvg(state);
  button.setAttribute("aria-label", label);
  button.setAttribute("title", title);
}

function restorePairingButton(button, label, title, delay = 1200) {
  window.clearTimeout(button.restoreTimer);
  button.restoreTimer = window.setTimeout(() => {
    if (button.dataset.defaultHtml) {
      button.innerHTML = button.dataset.defaultHtml;
    }
    button.dataset.feedbackState = "";
    button.setAttribute("aria-label", label);
    button.setAttribute("title", title);
  }, delay);
}

async function copyText(text, button) {
  const value = String(text || "").trim();
  let copied = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      copied = true;
    }
  } catch {
    copied = false;
  }

  if (!copied) {
    copied = fallbackCopyText(value);
  }

  const kind = button ? button.dataset.copyKind || "code" : "code";
  const messages = kind === "key" ? keyMessages : pairingMessages;
  if (copied) {
    messages.status(STRINGS.copied[kind], "success");
  } else {
    messages.error(STRINGS.copyFailed[kind]);
  }
  if (!button) {
    return;
  }

  if (button.classList.contains("setup-copy-code-btn")) {
    // Keep the original label on the button: a second click lands while it shows "Copied".
    button.dataset.defaultLabel ??= button.getAttribute("aria-label");
    button.dataset.defaultTitle ??= button.getAttribute("title") || button.dataset.defaultLabel;
    const previousLabel = button.dataset.defaultLabel;
    const previousTitle = button.dataset.defaultTitle;
    const nextLabel = copied ? STRINGS.copied[kind] : STRINGS.copyFailed[kind];
    setPairingButtonFeedback(button, copied ? "copied" : "failed", nextLabel, nextLabel);
    restorePairingButton(button, previousLabel, previousTitle);
  } else {
    // Text buttons keep their aria-label; the status line above carries the news.
    window.clearTimeout(button.restoreTimer);
    button.dataset.copyText0 ??= button.textContent;
    button.textContent = copied ? STRINGS.copyDone : STRINGS.copyFailedShort;
    button.restoreTimer = window.setTimeout(() => {
      button.textContent = button.dataset.copyText0;
    }, 1200);
  }
}

async function refreshPairingCode(button) {
  const previousLabel = button ? button.getAttribute("aria-label") : "";
  const previousTitle = button ? button.getAttribute("title") || previousLabel : "";
  if (button) {
    button.disabled = true;
    if (previousLabel) {
      button.setAttribute("aria-label", STRINGS.refreshingLabel);
      button.setAttribute("title", STRINGS.refreshingLabel);
    }
  }
  pairingMessages.status(STRINGS.refreshPending, "pending");

  const fail = (message) => {
    pairingMessages.error(message);
    if (button && previousLabel) {
      setPairingButtonFeedback(button, "failed", STRINGS.refreshFailedLabel, STRINGS.refreshFailedLabel);
      restorePairingButton(button, previousLabel, previousTitle);
    }
  };

  try {
    const resp = await fetch("/pairing/code", { method: "POST", credentials: "same-origin" });
    if (!resp.ok) {
      fail(STRINGS.refreshFailedHttp(resp.status));
      return;
    }
    if (button && previousLabel) {
      setPairingButtonFeedback(button, "success", STRINGS.refreshedLabel, STRINGS.refreshedLabel);
    }
    pairingMessages.status(STRINGS.refreshDone, "success");
    window.setTimeout(() => window.location.reload(), 700);
  } catch {
    fail(STRINGS.refreshFailedNetwork);
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

function openUnpairDialog() {
  document.getElementById("unpair-dialog").showModal();
}

async function confirmUnpair() {
  const dialog = document.getElementById("unpair-dialog");
  const btn = document.getElementById("unpair-confirm-btn");
  btn.disabled = true;
  btn.textContent = STRINGS.unpairing;
  try {
    const resp = await fetch("/pairing", { method: "DELETE", credentials: "same-origin" });
    dialog.close();
    if (resp.ok) {
      pairingMessages.status(STRINGS.unpairDone, "success");
      window.setTimeout(() => window.location.reload(), 700);
    } else {
      pairingMessages.error(STRINGS.unpairFailedHttp(resp.status));
    }
  } catch {
    dialog.close();
    pairingMessages.error(STRINGS.unpairFailedNetwork);
  } finally {
    btn.disabled = false;
    btn.textContent = STRINGS.unpair;
  }
}

let localKeyTimer = null;

function hideLocalKey() {
  const target = document.getElementById("local-api-key");
  const revealButton = document.querySelector("[data-local-key-reveal]");
  const hideButton = document.querySelector("[data-local-key-hide]");
  const copyButton = document.querySelector("[data-local-key-copy]");
  window.clearTimeout(localKeyTimer);
  target.textContent = target.dataset.placeholder;
  if (copyButton) {
    copyButton.disabled = true;
  }
  const hadFocus = hideButton.contains(document.activeElement);
  hideButton.hidden = true;
  revealButton.hidden = false;
  revealButton.disabled = false;
  revealButton.textContent = revealButton.dataset.defaultText;
  if (hadFocus) {
    revealButton.focus();
  }
  keyMessages.status(STRINGS.keyHidden, "success");
}

async function revealLocalKey(button) {
  const target = document.getElementById("local-api-key");
  const copyButton = document.querySelector("[data-local-key-copy]");
  const hideButton = document.querySelector("[data-local-key-hide]");
  if (!target) {
    return;
  }

  button.disabled = true;
  button.textContent = STRINGS.keyRevealing;
  keyMessages.status(STRINGS.keyFetching, "pending");

  try {
    const resp = await fetch("/local-key", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!resp.ok) {
      const err = new Error(`HTTP ${resp.status}`);
      err.status = resp.status;
      throw err;
    }
    const key = (await resp.text()).trim();
    target.textContent = key || STRINGS.keyEmpty;
    if (copyButton) {
      copyButton.disabled = !key;
    }
    button.hidden = true;
    hideButton.hidden = false;
    hideButton.focus();
    keyMessages.status(STRINGS.keyRevealed, "success");
    window.clearTimeout(localKeyTimer);
    localKeyTimer = window.setTimeout(hideLocalKey, LOCAL_KEY_VISIBLE_MS);
  } catch (err) {
    button.disabled = false;
    button.textContent = button.dataset.defaultText;
    keyMessages.error(err.status === 401 || err.status === 403 ? STRINGS.keyFailed : STRINGS.keyFailedGeneric);
  }
}

// True when the server's mode or status differs from what this page was rendered with.
async function pairingStateChanged() {
  const stateEl = document.querySelector("[data-pairing-state]");
  try {
    const resp = await fetch("/pairing/state", { cache: "no-store" });
    if (!resp.ok) {
      return false;
    }
    const data = await resp.json();
    return data.mode !== (stateEl.dataset.initialMode || "") || data.status !== (stateEl.dataset.initialPairingStatus || "");
  } catch {
    // Network blip: the caller keeps polling.
    return false;
  }
}

async function handleCodeExpired() {
  pairingMessages.status(STRINGS.codeExpired, "pending");
  if (await pairingStateChanged()) {
    window.location.reload();
    return;
  }
  pairingMessages.status(STRINGS.codeExpiredWaiting, "");
  for (const el of document.querySelectorAll("[data-expired-refresh], [data-expired-hint]")) {
    el.hidden = false;
  }
  for (const el of document.querySelectorAll("[data-copy-source='pairing-code']")) {
    el.disabled = true;
  }
}

function setupCountdown() {
  const countdown = document.querySelector("[data-pairing-countdown]");
  const expiry = document.querySelector("[data-pairing-expiry]");
  const progress = document.querySelector("[data-pairing-progress]");

  if (!countdown || !expiry || !progress) {
    return;
  }

  const expiresAt = new Date(expiry.dataset.expiresAt || "");
  const ttlMs = Number(expiry.dataset.ttlMs || "0");

  if (Number.isNaN(expiresAt.getTime())) {
    return;
  }

  const formatRemaining = (ms) => {
    if (ms <= 0) {
      return STRINGS.countdownExpired;
    }
    return formatRemainingTime(Math.ceil(ms / 1000));
  };

  const tick = () => {
    const remainingMs = expiresAt.getTime() - Date.now();
    countdown.textContent = formatRemaining(remainingMs);

    const ratio = ttlMs > 0 ? Math.max(0, Math.min(1, remainingMs / ttlMs)) : 0;
    progress.style.width = `${ratio * 100}%`;
    progress.classList.toggle("is-expired", remainingMs <= 0);
  };

  tick();
  const intervalId = window.setInterval(() => {
    tick();
    if (expiresAt.getTime() - Date.now() <= 0) {
      window.clearInterval(intervalId);
      handleCodeExpired();
    }
  }, 1000);
}

function setupPairingStatePolling() {
  if (!document.querySelector("[data-pairing-state]")) {
    return;
  }

  let reloading = false;
  const poll = async () => {
    if (reloading) {
      return;
    }
    if (await pairingStateChanged()) {
      reloading = true;
      window.location.reload();
    }
  };

  const intervalId = window.setInterval(poll, 2000);
  window.addEventListener("beforeunload", () => window.clearInterval(intervalId));
}

function setupActions() {
  for (const button of document.querySelectorAll("[data-copy-source]")) {
    button.addEventListener("click", () => {
      const source = document.getElementById(button.dataset.copySource);
      copyText(source ? source.textContent : "", button);
    });
  }

  for (const button of document.querySelectorAll("[data-refresh-pairing], [data-expired-refresh]")) {
    button.addEventListener("click", () => refreshPairingCode(button));
  }

  const revealLocalKeyButton = document.querySelector("[data-local-key-reveal]");
  if (revealLocalKeyButton) {
    revealLocalKeyButton.dataset.defaultText = revealLocalKeyButton.textContent.trim();
    document.getElementById("local-api-key").dataset.placeholder = document.getElementById("local-api-key").textContent;
    revealLocalKeyButton.addEventListener("click", () => revealLocalKey(revealLocalKeyButton));
    document.querySelector("[data-local-key-hide]").addEventListener("click", hideLocalKey);
  }

  const openUnpairButton = document.querySelector("[data-unpair-open]");
  if (openUnpairButton) {
    openUnpairButton.addEventListener("click", openUnpairDialog);
  }

  const closeDialogButton = document.querySelector("[data-dialog-close]");
  if (closeDialogButton) {
    closeDialogButton.addEventListener("click", () => document.getElementById("unpair-dialog").close());
  }

  const confirmButton = document.querySelector("[data-unpair-confirm]");
  if (confirmButton) {
    confirmButton.addEventListener("click", confirmUnpair);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupActions();
  setupCountdown();
  setupPairingStatePolling();
});
