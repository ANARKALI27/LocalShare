// Applies and persists the light/dark theme choice. Loaded before the
// page's own script on every page so the toggle button works
// identically everywhere, and the saved preference is applied
// immediately on load (before first paint) to avoid a flash of the
// wrong theme.

const THEME_STORAGE_KEY = "localshare_theme";

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle-btn");
  if (btn) {
    btn.textContent = theme === "light" ? "🌙 Dark" : "☀️ Light";
  }
}

function getStoredTheme() {
  return localStorage.getItem(THEME_STORAGE_KEY) || "dark";
}

function toggleTheme() {
  const current = getStoredTheme();
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_STORAGE_KEY, next);
  applyTheme(next);
}

// Apply immediately (theme.js is loaded in <head>, before body renders)
applyTheme(getStoredTheme());

document.addEventListener("DOMContentLoaded", () => {
  // Re-apply now that the button element actually exists in the DOM —
  // the earlier top-level call only had time to set data-theme (for
  // avoiding a flash of the wrong background color) but silently
  // skipped the button label since it wasn't in the document yet.
  applyTheme(getStoredTheme());

  const btn = document.getElementById("theme-toggle-btn");
  if (btn) {
    btn.addEventListener("click", toggleTheme);
  }
});

function hideLoadingOverlay() {
  const overlay = document.getElementById("loading-overlay");
  if (!overlay) return;
  overlay.classList.add("fade-out");
  setTimeout(() => overlay.remove(), 450);
}
