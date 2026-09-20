/* Studio 11 Master — local productivity controls, no network or publishing calls. */
(function () {
  "use strict";

  const root = document.documentElement;
  const tabs = [
    { id: "studio", label: "Studio", icon: "◆", detail: "Préparer le projet et les rushs" },
    { id: "pipeline", label: "Pipeline", icon: "▤", detail: "Suivre les générations en cours" },
    { id: "gallery", label: "Galerie", icon: "▶", detail: "Contrôler et télécharger les rendus" },
    { id: "intelligence", label: "Intelligence", icon: "✦", detail: "Lire les signaux du contenu" },
    { id: "learning", label: "Learning", icon: "↗", detail: "Enregistrer les performances" },
    { id: "publication", label: "Publication", icon: "⌁", detail: "Préparer l’export manuel" },
  ];
  const storage = { accent: "ad_master_accent", focus: "ad_master_focus", motion: "ad_master_motion" };
  const settings = document.getElementById("masterSettings");
  const palette = document.getElementById("commandPalette");
  const help = document.getElementById("shortcutHelp");
  const search = document.getElementById("commandSearch");
  const results = document.getElementById("commandResults");
  let selectedCommand = 0;
  let lastFocus = null;

  function read(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch (_) { return fallback; } }
  function write(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* local preferences only */ } }
  function isTyping(target) { return target && (target.matches("input,textarea,select") || target.isContentEditable); }
  function activeTab() { return document.querySelector("#nav button.active")?.dataset.tab || "studio"; }
  function go(tab) { document.querySelector(`#nav button[data-tab="${tab}"]`)?.click(); closePalette(); }

  function applyAccent(value) {
    const accent = ["violet", "cyan", "lime", "orange", "rose"].includes(value) ? value : "violet";
    root.dataset.accent = accent;
    document.querySelectorAll(".accent-grid [data-accent]").forEach(function (button) {
      button.classList.toggle("active", button.dataset.accent === accent);
      button.setAttribute("aria-pressed", String(button.dataset.accent === accent));
    });
    write(storage.accent, accent);
  }

  function applyFocus(enabled) {
    root.dataset.focus = enabled ? "on" : "off";
    const button = document.getElementById("focusModeBtn");
    const dock = document.getElementById("focusDockBtn");
    button?.setAttribute("aria-pressed", String(enabled));
    if (button) button.querySelector("i").textContent = enabled ? "On" : "Off";
    if (dock) dock.querySelector("b").textContent = enabled ? "Quitter" : "Focus";
    write(storage.focus, enabled ? "on" : "off");
  }

  function applyMotion(enabled) {
    root.dataset.motion = enabled ? "on" : "off";
    const button = document.getElementById("motionModeBtn");
    button?.setAttribute("aria-pressed", String(enabled));
    if (button) button.querySelector("i").textContent = enabled ? "On" : "Off";
    write(storage.motion, enabled ? "on" : "off");
  }

  function toggleSettings(force) {
    if (!settings) return;
    const open = force === undefined ? settings.hidden : force;
    settings.hidden = !open;
    document.getElementById("masterSettingsBtn")?.setAttribute("aria-expanded", String(open));
  }

  function openLayer(layer) {
    lastFocus = document.activeElement;
    layer.hidden = false;
    document.body.style.overflow = "hidden";
  }
  function closeLayer(layer) {
    if (!layer || layer.hidden) return;
    layer.hidden = true;
    document.body.style.overflow = "";
    lastFocus?.focus?.();
  }

  const commands = [
    ...tabs.map(function (tab, index) { return { label: tab.label, detail: tab.detail, icon: tab.icon, hint: `Alt ${index + 1}`, run: function () { go(tab.id); } }; }),
    { label: "Actualiser les données", detail: "Recharge l’état du Studio", icon: "↻", hint: "", run: function () { document.getElementById("refreshBtn")?.click(); closePalette(); } },
    { label: "Basculer le mode Focus", detail: "Isole l’espace de travail actif", icon: "◫", hint: "F", run: function () { applyFocus(root.dataset.focus !== "on"); closePalette(); } },
    { label: "Changer l’ambiance", detail: "Passe à l’ambiance visuelle suivante", icon: "◐", hint: "", run: function () { document.getElementById("themeToggle")?.click(); closePalette(); } },
    { label: "Changer la densité", detail: "Bascule entre Confort et Compact", icon: "↔", hint: "", run: function () { document.getElementById("densityToggle")?.click(); closePalette(); } },
    { label: "Personnaliser le Studio", detail: "Accent, mouvement et raccourcis", icon: "✦", hint: "", run: function () { closePalette(); toggleSettings(true); } },
    { label: "Afficher les raccourcis", detail: "Ouvre le guide clavier", icon: "?", hint: "?", run: function () { closePalette(); openHelp(); } },
  ];

  function filteredCommands() {
    const query = (search?.value || "").trim().toLocaleLowerCase("fr");
    return commands.filter(function (command) { return !query || `${command.label} ${command.detail}`.toLocaleLowerCase("fr").includes(query); });
  }

  function renderCommands() {
    if (!results) return;
    const list = filteredCommands();
    selectedCommand = Math.max(0, Math.min(selectedCommand, list.length - 1));
    results.replaceChildren();
    if (!list.length) {
      const empty = document.createElement("div"); empty.className = "command-empty"; empty.textContent = "Aucune commande correspondante."; results.appendChild(empty); return;
    }
    list.forEach(function (command, index) {
      const button = document.createElement("button");
      button.type = "button"; button.className = `command-item${index === selectedCommand ? " selected" : ""}`;
      button.innerHTML = `<i>${command.icon}</i><span><b></b><small></small></span><em></em>`;
      button.querySelector("b").textContent = command.label;
      button.querySelector("small").textContent = command.detail;
      button.querySelector("em").textContent = command.hint;
      button.addEventListener("mouseenter", function () {
        selectedCommand = index;
        results.querySelectorAll(".command-item").forEach(function (item, itemIndex) { item.classList.toggle("selected", itemIndex === index); });
      });
      button.addEventListener("click", command.run);
      results.appendChild(button);
    });
  }

  function openPalette() {
    if (!palette) return;
    toggleSettings(false); openLayer(palette); selectedCommand = 0;
    if (search) search.value = ""; renderCommands(); search?.focus();
  }
  function closePalette() { closeLayer(palette); }
  function openHelp() { if (help) { toggleSettings(false); openLayer(help); } }

  function updateHud() {
    const project = document.getElementById("projectSelect")?.selectedOptions?.[0]?.textContent?.trim() || "Aucun";
    const sources = document.getElementById("statSources")?.textContent || "0";
    const renders = document.getElementById("statRenders")?.textContent || "0";
    const jobs = Number(document.getElementById("navJobs")?.textContent || 0);
    const projectTarget = document.getElementById("hudProject");
    if (projectTarget) projectTarget.textContent = project === "Sélectionner un projet…" ? "Aucun" : project;
    if (document.getElementById("hudSources")) document.getElementById("hudSources").textContent = sources;
    if (document.getElementById("hudRenders")) document.getElementById("hudRenders").textContent = renders;
    if (document.getElementById("hudJobs")) document.getElementById("hudJobs").textContent = jobs ? `${jobs} actif${jobs > 1 ? "s" : ""}` : "Calme";
    document.querySelectorAll("#mobileMasterNav button").forEach(function (button) { button.classList.toggle("active", button.dataset.tab === activeTab()); });
  }

  function buildMobileNav() {
    const nav = document.getElementById("mobileMasterNav"); if (!nav) return;
    tabs.forEach(function (tab) {
      const button = document.createElement("button"); button.type = "button"; button.dataset.tab = tab.id;
      button.innerHTML = `<span>${tab.icon}</span><span></span>`; button.lastElementChild.textContent = tab.label;
      button.addEventListener("click", function () { go(tab.id); }); nav.appendChild(button);
    });
  }

  function moveSpace(delta) {
    const current = tabs.findIndex(function (tab) { return tab.id === activeTab(); });
    go(tabs[(current + delta + tabs.length) % tabs.length].id);
  }

  function updateScroll() {
    const height = document.documentElement.scrollHeight - window.innerHeight;
    const progress = height > 0 ? Math.min(100, Math.max(0, window.scrollY / height * 100)) : 0;
    const bar = document.querySelector("#scrollProgress i"); if (bar) bar.style.width = `${progress}%`;
  }

  function updateClock() {
    const clock = document.getElementById("hudClock");
    if (clock) clock.textContent = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(new Date());
  }

  applyAccent(read(storage.accent, "violet"));
  applyFocus(read(storage.focus, "off") === "on");
  applyMotion(read(storage.motion, "on") !== "off");
  buildMobileNav(); updateHud(); updateClock(); updateScroll();

  document.getElementById("commandBtn")?.addEventListener("click", openPalette);
  document.getElementById("masterSettingsBtn")?.addEventListener("click", function () { toggleSettings(); });
  document.querySelector("[data-master-close]")?.addEventListener("click", function () { toggleSettings(false); });
  document.querySelectorAll(".accent-grid [data-accent]").forEach(function (button) { button.addEventListener("click", function () { applyAccent(button.dataset.accent); }); });
  document.getElementById("focusModeBtn")?.addEventListener("click", function () { applyFocus(root.dataset.focus !== "on"); });
  document.getElementById("focusDockBtn")?.addEventListener("click", function () { applyFocus(root.dataset.focus !== "on"); });
  document.getElementById("motionModeBtn")?.addEventListener("click", function () { applyMotion(root.dataset.motion === "off"); });
  document.getElementById("shortcutHelpBtn")?.addEventListener("click", openHelp);
  document.querySelector("[data-help-close]")?.addEventListener("click", function () { closeLayer(help); });
  document.getElementById("previousSpaceBtn")?.addEventListener("click", function () { moveSpace(-1); });
  document.getElementById("nextSpaceBtn")?.addEventListener("click", function () { moveSpace(1); });
  search?.addEventListener("input", function () { selectedCommand = 0; renderCommands(); });
  search?.addEventListener("keydown", function (event) {
    const list = filteredCommands();
    if (event.key === "ArrowDown") { event.preventDefault(); selectedCommand = (selectedCommand + 1) % Math.max(1, list.length); renderCommands(); }
    if (event.key === "ArrowUp") { event.preventDefault(); selectedCommand = (selectedCommand - 1 + Math.max(1, list.length)) % Math.max(1, list.length); renderCommands(); }
    if (event.key === "Enter" && list[selectedCommand]) { event.preventDefault(); list[selectedCommand].run(); }
  });
  palette?.addEventListener("click", function (event) { if (event.target === palette) closePalette(); });
  help?.addEventListener("click", function (event) { if (event.target === help) closeLayer(help); });
  window.addEventListener("scroll", updateScroll, { passive: true });
  window.addEventListener("resize", updateScroll, { passive: true });
  window.addEventListener("online", function () { document.body.dataset.network = "online"; });
  window.addEventListener("offline", function () { document.body.dataset.network = "offline"; });
  document.body.dataset.network = navigator.onLine ? "online" : "offline";

  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); palette?.hidden ? openPalette() : closePalette(); return; }
    if (event.key === "Escape") { closePalette(); closeLayer(help); toggleSettings(false); return; }
    if (isTyping(event.target)) return;
    if (event.altKey && /^[1-6]$/.test(event.key)) { event.preventDefault(); go(tabs[Number(event.key) - 1].id); return; }
    if (event.key.toLowerCase() === "f") { event.preventDefault(); applyFocus(root.dataset.focus !== "on"); return; }
    if (event.key === "?") { event.preventDefault(); openHelp(); }
  });

  const observer = new MutationObserver(updateHud);
  ["nav", "statSources", "statRenders", "projectSelect"].forEach(function (id) { const node = document.getElementById(id); if (node) observer.observe(node, { subtree: true, childList: true, characterData: true, attributes: true }); });
  document.getElementById("projectSelect")?.addEventListener("change", updateHud);
  window.setInterval(updateClock, 30000);
}());
