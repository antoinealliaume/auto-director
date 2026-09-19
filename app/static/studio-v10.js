/* Studio 10 appearance controls. Local-only: no API or publishing behavior. */
(function () {
  "use strict";

  const root = document.documentElement;
  const themeButton = document.getElementById("themeToggle");
  const densityButton = document.getElementById("densityToggle");
  const sidebarButton = document.getElementById("sidebarToggle");
  const themes = [
    { id: "aurora", label: "Aurora", color: "#090b14" },
    { id: "ember", label: "Ember", color: "#130c09" },
    { id: "daylight", label: "Clair", color: "#eef1f7" },
  ];
  const keys = {
    theme: "ad_ui_theme_v10",
    density: "ad_ui_density_v10",
    sidebar: "ad_ui_sidebar_v10",
  };

  function read(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch (_) { return fallback; }
  }

  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (_) { /* private browsing */ }
  }

  function setButtonLabel(button, label) {
    const target = button && button.querySelector("b");
    if (target) target.textContent = label;
  }

  function animateTheme() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    root.classList.add("theme-transition");
    window.setTimeout(function () { root.classList.remove("theme-transition"); }, 360);
  }

  function applyTheme(themeId, persist) {
    const theme = themes.find(function (item) { return item.id === themeId; }) || themes[0];
    animateTheme();
    root.dataset.theme = theme.id;
    setButtonLabel(themeButton, theme.label);
    if (themeButton) themeButton.title = "Ambiance : " + theme.label;
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (themeMeta) themeMeta.setAttribute("content", theme.color);
    if (persist) write(keys.theme, theme.id);
  }

  function applyDensity(value, persist) {
    const density = value === "compact" ? "compact" : "comfortable";
    root.dataset.density = density;
    setButtonLabel(densityButton, density === "compact" ? "Compact" : "Confort");
    if (densityButton) {
      densityButton.setAttribute("aria-pressed", String(density === "compact"));
      densityButton.title = density === "compact" ? "Revenir en vue confort" : "Passer en vue compacte";
    }
    if (persist) write(keys.density, density);
  }

  function applySidebar(value, persist) {
    const sidebar = value === "collapsed" ? "collapsed" : "expanded";
    root.dataset.sidebar = sidebar;
    if (sidebarButton) {
      const collapsed = sidebar === "collapsed";
      sidebarButton.setAttribute("aria-pressed", String(collapsed));
      sidebarButton.setAttribute("aria-label", collapsed ? "Déployer la navigation" : "Replier la navigation");
      sidebarButton.title = collapsed ? "Déployer la navigation" : "Replier la navigation";
    }
    if (persist) write(keys.sidebar, sidebar);
  }

  applyTheme(read(keys.theme, "aurora"), false);
  applyDensity(read(keys.density, "comfortable"), false);
  applySidebar(read(keys.sidebar, "expanded"), false);

  if (themeButton) themeButton.addEventListener("click", function () {
    const current = themes.findIndex(function (theme) { return theme.id === root.dataset.theme; });
    applyTheme(themes[(current + 1) % themes.length].id, true);
  });

  if (densityButton) densityButton.addEventListener("click", function () {
    applyDensity(root.dataset.density === "compact" ? "comfortable" : "compact", true);
  });

  if (sidebarButton) sidebarButton.addEventListener("click", function () {
    applySidebar(root.dataset.sidebar === "collapsed" ? "expanded" : "collapsed", true);
  });

  document.addEventListener("keydown", function (event) {
    if (event.altKey && event.key === "\\") {
      applySidebar(root.dataset.sidebar === "collapsed" ? "expanded" : "collapsed", true);
    }
  });
}());
