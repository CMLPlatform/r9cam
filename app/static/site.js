const THEME_STORAGE_KEY = "r9cam-theme";
const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
const themeStorage = window["localStorage"];
const THEME_SEQUENCE = ["auto", "light", "dark"];
// User-facing text, kept together for a later translation pass.
const STRINGS = {
  theme: {
    auto: "Theme: Auto",
    light: "Theme: Light",
    dark: "Theme: Dark",
  },
};

function resolveTheme(themePreference) {
  if (themePreference === "dark" || themePreference === "light") {
    return themePreference;
  }
  return mediaQuery.matches ? "dark" : "light";
}

function applyTheme(themePreference) {
  const resolvedTheme = resolveTheme(themePreference);
  document.documentElement.dataset.themePreference = themePreference;
  document.documentElement.dataset.theme = resolvedTheme;
}

function syncThemeToggle() {
  const toggle = document.querySelector("[data-theme-toggle]");
  const themePreference = document.documentElement.dataset.themePreference || "auto";

  if (!toggle) {
    return;
  }

  const themeLabel = STRINGS.theme[themePreference] || STRINGS.theme.auto;
  toggle.dataset.themeState = themePreference;
  toggle.setAttribute("aria-label", themeLabel);
  toggle.setAttribute("title", themeLabel);
}

// Announce only after a click, not on page load.
function announceTheme() {
  const live = document.querySelector("[data-theme-announce]");
  const themePreference = document.documentElement.dataset.themePreference || "auto";
  if (live) {
    live.textContent = STRINGS.theme[themePreference] || STRINGS.theme.auto;
  }
}

function onSystemThemeChange() {
  const themePreference = themeStorage ? themeStorage.getItem(THEME_STORAGE_KEY) || "auto" : "auto";
  if (themePreference === "auto") {
    applyTheme(themePreference);
    syncThemeToggle();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector("[data-theme-toggle]");
  const themePreference = themeStorage ? themeStorage.getItem(THEME_STORAGE_KEY) || "auto" : "auto";

  applyTheme(themePreference);
  syncThemeToggle();

  if (!toggle) {
    return;
  }

  toggle.addEventListener("click", () => {
    const currentTheme = document.documentElement.dataset.themePreference || "auto";
    const currentIndex = THEME_SEQUENCE.indexOf(currentTheme);
    const nextTheme = THEME_SEQUENCE[(currentIndex + 1) % THEME_SEQUENCE.length];
    if (themeStorage) {
      themeStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    }
    applyTheme(nextTheme);
    syncThemeToggle();
    announceTheme();
  });
});

mediaQuery.addEventListener("change", onSystemThemeChange);
