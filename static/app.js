document.addEventListener("DOMContentLoaded", () => {
  const menu = document.getElementById("menuBtn");
  const nav = document.getElementById("mainNav");
  if (menu && nav) menu.addEventListener("click", () => nav.classList.toggle("nav-open"));
  document.querySelectorAll("[data-copy]").forEach(btn => {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.copy);
        const old = btn.textContent; btn.textContent = "Copied ✓";
        setTimeout(() => btn.textContent = old, 1600);
      } catch { btn.textContent = btn.dataset.copy; }
    });
  });

  // Theme choice persists in this browser and applies across all pages.
  const themes = ["police", "paper", "cyber"];
  const savedTheme = localStorage.getItem("stu-theme");
  document.body.dataset.theme = themes.includes(savedTheme) ? savedTheme : "police";
  const updateThemeButtons = () => {
    document.querySelectorAll("[data-theme-choice]").forEach(button => {
      const active = button.dataset.themeChoice === document.body.dataset.theme;
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  };
  document.querySelectorAll("[data-theme-choice]").forEach(button => {
    button.addEventListener("click", () => {
      const theme = button.dataset.themeChoice;
      if (!themes.includes(theme)) return;
      document.body.dataset.theme = theme;
      localStorage.setItem("stu-theme", theme);
      updateThemeButtons();
    });
  });
  updateThemeButtons();
});
