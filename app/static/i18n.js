// The server renders the page's strings into #i18n-strings in the request's language.
// Each module keeps its English text as the fallback for a missing block or key.
let rendered = {};
try {
  rendered = JSON.parse(document.getElementById("i18n-strings")?.textContent || "{}");
} catch {
  // Malformed block: the English defaults stay.
}

// A function default takes one value (a status code); its rendered text holds a "{...}" placeholder for it.
export function loadStrings(section, defaults) {
  const merge = (base, over) => {
    if (typeof base === "function") {
      return typeof over === "string" ? (value) => over.replace(/\{\w+\}/, value) : base;
    }
    if (base && typeof base === "object") {
      return Object.fromEntries(Object.entries(base).map(([key, value]) => [key, merge(value, over?.[key])]));
    }
    return typeof over === "string" ? over : base;
  };
  return merge(defaults, rendered[section]);
}

// Minutes and seconds in the page language, e.g. "1m 05s" or "1 min 05 s".
export function formatRemainingTime(totalSeconds) {
  const unit = (value, name, minimumIntegerDigits = 1) =>
    new Intl.NumberFormat(document.documentElement.lang || undefined, {
      style: "unit",
      unit: name,
      unitDisplay: "narrow",
      minimumIntegerDigits,
    }).format(value);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${unit(minutes, "minute")} ${unit(seconds, "second", 2)}` : unit(seconds, "second");
}
