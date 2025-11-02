document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("theme-toggle");
  const body = document.body;

  const saved = localStorage.getItem("theme");
  if (saved) {
    body.dataset.theme = saved;
    toggle.textContent = saved === "dark" ? "🌙" : "☀️";
  } else {
    const prefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)"
    ).matches;
    const defaultTheme = prefersDark ? "dark" : "light";
    body.dataset.theme = defaultTheme;
    toggle.textContent = defaultTheme === "dark" ? "🌙" : "☀️";
  }

  toggle.addEventListener("click", () => {
    const next = body.dataset.theme === "dark" ? "light" : "dark";
    body.dataset.theme = next;
    localStorage.setItem("theme", next);
    toggle.textContent = next === "dark" ? "🌙" : "☀️";
  });
});
