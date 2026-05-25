(function () {
  const TWITCH_TIERS = [
    { key: "1000", label: "1" },
    { key: "2000", label: "2" },
    { key: "3000", label: "3" },
  ];
  function patreonTiersForRules() {
    return (state.patreon && state.patreon.tiers) ? state.patreon.tiers.map((t) => ({
      key: String(t.amount_cents),
      label: patreonTierLabel(t),
      points: t.points,
    })) : [];
  }
  function patreonTierLabel(tier) {
    const dollars = (tier.amount_cents / 100).toFixed(2);
    const base = tier.title ? `${tier.title} ($${dollars}/mo)` : `$${dollars}/mo`;
    return `Patreon - ${base}`;
  }
      function tiersForEventType(eventKey) {
        if (eventKey.startsWith("patreon")) return patreonTiersForRules();
        return TWITCH_TIERS;
      }
      /** Scoring mode for UI rendering; YouTube memberships are always flat (never per-level). */
      function effectiveRuleMode(meta, rule) {
        if (meta.key === "youtube_membership") return "per_event";
        if (meta.key === "youtube_membership_gift") return "per_quantity";
        return rule.mode || meta.mode;
      }
      function usesTierRuleCards(meta, rule) {
        if (meta.key.startsWith("youtube_membership")) return false;
        if (meta.key === "patreon_pledge_create") {
          return effectiveRuleMode(meta, rule) === "per_event_tier";
        }
        return false;
      }
  function emptyTierRuleHint(meta) {
    if (meta.key.startsWith("patreon")) {
      return state.patreon && state.patreon.load_error
        ? state.patreon.load_error
        : "No Patreon tiers loaded. Connect Patreon in Monitors.";
    }
    return "No tiers loaded.";
  }
  const REVENUE_TYPES = [
    { key: "twitch_bits", label: "Bits (Twitch)", mode: "per_quantity" },
    { key: "twitch_subscription", label: "Sub (Twitch)", mode: "per_event_tier" },
    { key: "twitch_subscription_gift", label: "Sub gift (Twitch)", mode: "per_quantity_tier" },
    { key: "twitch_resubscription", label: "Resub (Twitch)", mode: "per_event_tier" },
    { key: "youtube_super_chat", label: "Super Chat (YouTube)", mode: "per_eur" },
    { key: "youtube_super_sticker", label: "Super Sticker (YouTube)", mode: "per_eur" },
    { key: "youtube_membership", label: "New member (YouTube)", mode: "per_event" },
    { key: "youtube_membership_gift", label: "Membership gift (YouTube)", mode: "per_quantity" },
    { key: "youtube_gift", label: "Gift (YouTube)", mode: "per_quantity" },
    { key: "patreon_pledge_create", label: "New pledge (Patreon)", mode: "per_event_tier" },
    { key: "streamlabs_donation", label: "Donation (Streamlabs)", mode: "per_eur" },
  ];
  const TEST_INPUTS = {
    twitch_bits: [{ key: "quantity", placeholder: "Bits", int: true }],
    twitch_subscription: [{ key: "tier", placeholder: "Tier (1–3)", int: true }],
    twitch_subscription_gift: [
      { key: "tier", placeholder: "Tier (1–3)", int: true },
      { key: "quantity", placeholder: "Gift count", int: true },
    ],
    twitch_resubscription: [{ key: "tier", placeholder: "Tier (1–3)", int: true }],
    youtube_super_chat: [
      { key: "amount", placeholder: "Amount", decimal: true },
      { key: "currency", placeholder: "Currency", currency: true },
    ],
    youtube_super_sticker: [
      { key: "amount", placeholder: "Amount", decimal: true },
      { key: "currency", placeholder: "Currency", currency: true },
    ],
    youtube_membership: [],
    youtube_membership_gift: [{ key: "quantity", placeholder: "Gift count", int: true }],
    youtube_gift: [{ key: "quantity", placeholder: "Jewels", int: true }],
    patreon_pledge_create: [{ key: "tier", placeholder: "Tier", tierSelect: true }],
    streamlabs_donation: [
      { key: "amount", placeholder: "Amount", decimal: true },
      { key: "currency", placeholder: "Currency", currency: true },
    ],
  };

  const BAR_FONT_OPTIONS = [
    { label: "System UI", value: "system-ui, Segoe UI, sans-serif" },
    { label: "Arial", value: "Arial, Helvetica, sans-serif" },
    { label: "Verdana", value: "Verdana, Geneva, sans-serif" },
    { label: "Trebuchet MS", value: "'Trebuchet MS', Helvetica, sans-serif" },
    { label: "Georgia", value: "Georgia, 'Times New Roman', serif" },
    { label: "Courier New", value: "'Courier New', Courier, monospace" },
    { label: "Impact", value: "Impact, Haettenschweiler, sans-serif" },
  ];

  const UI_TOKEN = (document.querySelector('meta[name="mrt-ui-token"]') || {}).content || "";
  const REQUIRE_WS_TOKEN = document.documentElement.dataset.requireWsToken === "true";

  let state = {
    goals: [], active_goal_id: null, point_rules: {}, exchange_rates: {}, progress: {},
    subathon: null,
    patreon: null, youtube: null, monitors: [], session_revenue: [], user_config: null, allow_test_events: false,
    supported_currencies: [],
    bar_appearance: null,
    timer_appearance: null,
    progress_effects: null,
    effects_catalog: null,
  };
  let savedBarAppearanceSignature = "";
  let savedProgressEffectsSignature = "";
  let progressEffectsFormSyncing = false;
  let lastProgressSnapshot = null;
  let savedTimerAppearanceSignature = "";
  let timerAppearanceFormSyncing = false;
  let barAppearanceFormSyncing = false;
  let savedConfigSignature = "";
  let savedTwitchChannel = "";
  let twitchChannelFormSyncing = false;
  let pendingTwitchChannelSave = false;
  let configFormSyncing = false;
  let patreonCampaignSwitching = false;
  let savedRulesSignature = "";
  let rulesFormSyncing = false;

  const monitorStatusList = document.getElementById("monitor-status-list");
  const sessionRevenueBody = document.getElementById("session-revenue-body");
  const sessionRevenueEmpty = document.getElementById("session-revenue-empty");
  const sessionRevenueTable = document.getElementById("session-revenue-table");
  const rulesSaveBtn = document.getElementById("rules-save-btn");
  const shutdownBtn = document.getElementById("shutdown-btn");
  const restartBtn = document.getElementById("restart-btn");
  const configForm = document.getElementById("config-form");
  const configSaveBtn = document.getElementById("config-save-btn");
  const configSaveStatus = document.getElementById("config-save-status");
  const dashTwitchChannelInput = document.getElementById("dash-twitch-channel");
  const dashTwitchChannelSaveBtn = document.getElementById("dash-twitch-channel-save-btn");
  const dashTwitchChannelStatus = document.getElementById("dash-twitch-channel-status");
  const dashboardEl = document.querySelector(".dashboard");
  const dashboardTop = document.querySelector(".dashboard-top");
  const panelRules = document.querySelector(".panel-rules");
  const panelGoals = document.querySelector(".panel-create-goal");
  const panelMonitors = document.querySelector(".panel-monitors");
  const testPanel = document.getElementById("test-panel");
  const logPanel = document.getElementById("log-panel");
  const logEl = document.getElementById("log-output");
  const autoScrollEl = document.getElementById("log-autoscroll");
  const alertsPanel = document.getElementById("alerts-panel");
  const alertsToggleBtn = document.getElementById("alerts-toggle-btn");
  const alertsToggleLabel = document.getElementById("alerts-toggle-label");
  const alertsBadge = document.getElementById("alerts-badge");
  const alertsClearBtn = document.getElementById("alerts-clear-btn");
  const alertsListEl = document.getElementById("alerts-list");
  const alertsEmptyEl = document.getElementById("alerts-empty");
  const MAX_USER_ALERTS = 20;
  const userAlerts = [];
  let alertsUnread = 0;
  let alertsVisible = false;
  let lastMonitorSnapshot = {};
  let lastPatreonLoadError = "";
  const goalNameEl = document.getElementById("goal-name");
  const goalBarFill = document.getElementById("goal-bar-fill");
  const progressPanel = document.getElementById("progress-panel");
  const goalPointsTextEl = document.getElementById("goal-points-text");
  const subathonDisplayEl = document.getElementById("subathon-display");
  const subathonPlayBtn = document.getElementById("subathon-play-btn");
  const subathonPauseBtn = document.getElementById("subathon-pause-btn");
  const subathonHoursInput = document.getElementById("subathon-hours");
  const subathonMinutesInput = document.getElementById("subathon-minutes");
  const subathonSecondsInput = document.getElementById("subathon-seconds-input");
  const subathonApplyTimeBtn = document.getElementById("subathon-apply-time-btn");
  const subathonPointsInput = document.getElementById("subathon-points");
  const subathonSecondsAddedInput = document.getElementById("subathon-seconds-added");
  const subathonSaveSettingsBtn = document.getElementById("subathon-save-settings-btn");
  const subathonSettingsStatus = document.getElementById("subathon-settings-status");
  const subathonOverlayUrlInput = document.getElementById("subathon-overlay-url");
  const goalOverlayUrlInput = document.getElementById("goal-overlay-url");
  const goalOverlayOpenBtn = document.getElementById("goal-overlay-open-btn");
  const subathonOverlayOpenBtn = document.getElementById("subathon-overlay-open-btn");
  const timerFontColorInput = document.getElementById("timer-font-color");
  const timerFontFamilySelect = document.getElementById("timer-font-family");
  const timerShowDaysInput = document.getElementById("timer-show-days");
  const timerAppearanceSaveBtn = document.getElementById("timer-appearance-save-btn");
  const subathonPanel = document.getElementById("subathon-panel");
  const barFillColorInput = document.getElementById("bar-fill-color");
  const barGradientColorInput = document.getElementById("bar-gradient-color");
  const barUseGradientInput = document.getElementById("bar-use-gradient");
  const barShowDecimalsInput = document.getElementById("bar-show-decimals");
  const themeToggleBtn = document.getElementById("theme-toggle-btn");
  const barFontFamilySelect = document.getElementById("bar-font-family");
  const barAppearanceSaveBtn = document.getElementById("bar-appearance-save-btn");
  const goalCompleteEffectSelect = document.getElementById("goal-complete-effect");
  const pointsAddedEffectSelect = document.getElementById("points-added-effect");
  const goalCompletePreviewBtn = document.getElementById("goal-complete-preview-btn");
  const pointsAddedPreviewBtn = document.getElementById("points-added-preview-btn");
  const progressEffectsSaveBtn = document.getElementById("progress-effects-save-btn");
  const goalCompleteRepeatInput = document.getElementById("goal-complete-repeat");
  let goalCompleteRepeatTimer = null;
  const GOAL_COMPLETE_REPEAT_MS = 7000;
  const rulesFieldsEl = document.getElementById("rules-fields");
  const ratesDisplayEl = document.getElementById("rates-display");
  const ratesMetaEl = document.getElementById("rates-meta");
  const goalSelectEl = document.getElementById("goal-select");
  const pointsChangeEl = document.getElementById("points-change");
  const goalStartInput = document.getElementById("goal-start-input");
  const testEventsGrid = document.getElementById("test-events-grid");
  const patreonCampaignRow = document.getElementById("patreon-campaign-row");
  const patreonCampaignSelect = document.getElementById("patreon-campaign-select");
  const patreonStatusEl = document.getElementById("patreon-status");
  const restartLoadingEl = document.getElementById("restart-loading");
  const restartLoadingTextEl = document.getElementById("restart-loading-text");

  let ws = null;
  let wsPingTimer = null;
  const WS_PING_INTERVAL_MS = 20000;
  let restartInProgress = false;
  let restartReconnecting = false;
  let shutdownInProgress = false;
  let dashboardReconnecting = false;

  function send(message) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      appendLog("[app] not connected — action was not sent");
      pushUserAlert("Not connected to the app — your action was not sent. Wait a moment or refresh the page.");
      return false;
    }
    ws.send(JSON.stringify(message));
    return true;
  }

  function sanitizeAlertMessage(text) {
    if (text == null || text === "") return "Something went wrong.";
    let msg = String(text).trim().replace(/\s+/g, " ");
    msg = msg.replace(/[A-Za-z]:\\[^\s]+/g, "[path]");
    msg = msg.replace(/\/[\w./-]+\.(py|json|txt|log|db)\b/gi, "[file]");
    msg = msg.replace(/\b(?:sk|pk)_(?:live|test)?_?[A-Za-z0-9]{8,}\b/gi, "[token]");
    msg = msg.replace(/\bBearer\s+[A-Za-z0-9._-]+\b/gi, "Bearer [token]");
    if (msg.length > 280) msg = `${msg.slice(0, 277)}…`;
    return msg;
  }

  function pushUserAlert(message, { source = "app", monitorId = null } = {}) {
    const text = sanitizeAlertMessage(message);
    const now = Date.now();
    if (userAlerts.some((entry) => entry.message === text && now - entry.at < 5000)) return;
    userAlerts.unshift({
      id: `${now}-${Math.random().toString(36).slice(2, 8)}`,
      message: text,
      source,
      monitorId,
      at: now,
    });
    while (userAlerts.length > MAX_USER_ALERTS) userAlerts.pop();
    if (!alertsVisible) alertsUnread += 1;
    renderAlerts();
  }

  function updateAlertsChrome() {
    const count = userAlerts.length;
    const unread = alertsVisible ? 0 : alertsUnread;
    if (alertsBadge) {
      if (unread > 0) {
        alertsBadge.hidden = false;
        alertsBadge.textContent = String(unread);
        alertsBadge.setAttribute("aria-hidden", "false");
      } else {
        alertsBadge.hidden = true;
        alertsBadge.setAttribute("aria-hidden", "true");
      }
    }
    if (alertsToggleLabel) {
      if (alertsVisible) {
        alertsToggleLabel.textContent = count ? `Hide alerts (${count})` : "Hide alerts";
      } else {
        alertsToggleLabel.textContent = unread ? `Show alerts (${unread})` : "Show alerts";
      }
    }
    if (alertsClearBtn) alertsClearBtn.disabled = count === 0;
    if (alertsPanel) {
      alertsPanel.classList.toggle("alerts-has-unread", unread > 0);
      alertsPanel.classList.toggle("alerts-expanded", alertsVisible);
    }
    if (alertsToggleBtn) alertsToggleBtn.setAttribute("aria-expanded", String(alertsVisible));
  }

  function renderAlerts() {
    if (!alertsListEl) return;
    alertsListEl.innerHTML = "";
    for (const entry of userAlerts) {
      const li = document.createElement("li");
      li.className = "alert-item";
      li.setAttribute("role", "listitem");
      const msg = document.createElement("p");
      msg.className = "alert-item-message";
      msg.textContent = entry.message;
      const time = document.createElement("span");
      time.className = "alert-item-time";
      time.textContent = new Date(entry.at).toLocaleTimeString();
      const dismiss = document.createElement("button");
      dismiss.type = "button";
      dismiss.className = "alert-item-dismiss secondary outline";
      dismiss.textContent = "×";
      dismiss.title = "Dismiss";
      dismiss.setAttribute("aria-label", "Dismiss alert");
      dismiss.addEventListener("click", () => {
        const idx = userAlerts.findIndex((a) => a.id === entry.id);
        if (idx >= 0) userAlerts.splice(idx, 1);
        renderAlerts();
      });
      li.appendChild(msg);
      li.appendChild(time);
      li.appendChild(dismiss);
      alertsListEl.appendChild(li);
    }
    if (alertsEmptyEl) alertsEmptyEl.hidden = userAlerts.length > 0;
    updateAlertsChrome();
  }

  function clearUserAlerts() {
    userAlerts.length = 0;
    alertsUnread = 0;
    renderAlerts();
  }

  function setAlertsVisible(visible) {
    alertsVisible = visible;
    if (alertsPanel) alertsPanel.classList.toggle("collapsed", !visible);
    if (visible) {
      alertsUnread = 0;
      if (alertsPanel) alertsPanel.classList.remove("alerts-has-unread");
    }
    renderAlerts();
  }

  function syncMonitorAlerts(monitors) {
    for (const row of monitors || []) {
      const prev = lastMonitorSnapshot[row.id];
      const isError = row.status === "error";
      const detail = (row.detail || "").trim();
      if (isError && detail && (!prev || prev.status !== "error" || prev.detail !== detail)) {
        pushUserAlert(`${row.label || row.id}: ${detail}`, { source: "monitor", monitorId: row.id });
      }
      lastMonitorSnapshot[row.id] = { status: row.status, detail: row.detail };
    }
  }

  function syncPatreonAlert(patreon) {
    const err = (patreon && patreon.load_error) ? String(patreon.load_error).trim() : "";
    if (err && err !== lastPatreonLoadError) {
      pushUserAlert(`Patreon: ${err}`, { source: "patreon" });
    }
    lastPatreonLoadError = err;
  }

  function showLoadingOverlay(message) {
    if (restartLoadingTextEl) restartLoadingTextEl.textContent = message;
    if (restartLoadingEl) restartLoadingEl.hidden = false;
  }

  function hideLoadingOverlay() {
    if (restartLoadingEl) restartLoadingEl.hidden = true;
  }

  function showDashboardTab() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === "dashboard");
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === "tab-dashboard");
    });
  }

  // The on-screen log pane is diagnostic only — never let it grow without
  // bound. Long-running sessions previously kept the entire history,
  // which becomes a multi-MB string that slows down DOM updates.
  const LOG_BUFFER_MAX_LINES = 1000;
  const LOG_BUFFER_TRIM_TO = 800;
  function appendLog(line) {
    logEl.textContent += line + "\n";
    // Trim from the top occasionally instead of every append, so we
    // don't pay the O(n) split/join cost on every log line.
    const text = logEl.textContent;
    if (text.length > 32768) {
      const lines = text.split("\n");
      if (lines.length > LOG_BUFFER_MAX_LINES) {
        logEl.textContent = lines.slice(lines.length - LOG_BUFFER_TRIM_TO).join("\n");
      }
    }
    if (autoScrollEl.checked) logEl.scrollTop = logEl.scrollHeight;
  }

  function barShowDecimals() {
    if (barShowDecimalsInput) return barShowDecimalsInput.checked;
    return Boolean((state.bar_appearance || {}).show_decimals);
  }

  function exactPointsValue(value) {
    return Math.round((Number(value) || 0) * 100) / 100;
  }

  function formatPoints(value) {
    const exact = exactPointsValue(value);
    if (barShowDecimals()) {
      return exact.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return Math.round(exact).toLocaleString();
  }

  function formatPointsExact(value) {
    return exactPointsValue(value).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatProgressPointsCaption(current, target, { hasGoal = true } = {}) {
    const exactCurrent = exactPointsValue(current);
    const exactTarget = exactPointsValue(target);
    const roundedCurrent = Math.round(exactCurrent);
    const roundedTarget = Math.round(exactTarget);
    const targetStr = formatPoints(exactTarget);
    if (
      !barShowDecimals()
      && hasGoal
      && exactTarget > 0
      && roundedCurrent === roundedTarget
      && exactCurrent !== exactTarget
    ) {
      return `${formatPoints(exactCurrent)} (${formatPointsExact(exactCurrent)}) / ${targetStr} pts`;
    }
    return `${formatPoints(exactCurrent)} / ${targetStr} pts`;
  }

  function formatNumber(value) {
    return formatPoints(value);
  }

  function formatRuleNumber(value) {
    const n = Math.max(0, Number(value) || 0);
    const rounded = Math.round(n * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
  }

  function applyTheme(theme) {
    const next = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("mrt-ui-theme", next);
    if (themeToggleBtn) {
      const isDark = next === "dark";
      themeToggleBtn.textContent = isDark ? "Light mode" : "Dark mode";
      themeToggleBtn.setAttribute("aria-pressed", String(isDark));
      themeToggleBtn.title = isDark ? "Switch to light mode" : "Switch to dark mode";
    }
  }

  function initThemeToggle() {
    applyTheme(document.documentElement.dataset.theme || "dark");
    if (!themeToggleBtn) return;
    themeToggleBtn.addEventListener("click", () => {
      const current = document.documentElement.dataset.theme || "dark";
      applyTheme(current === "dark" ? "light" : "dark");
    });
  }

  function normalizeHexColor(value, fallback) {
    let text = String(value || fallback).trim();
    if (!text.startsWith("#")) text = `#${text}`;
    if (/^#[0-9A-Fa-f]{6}$/.test(text)) return text.toUpperCase();
    return String(fallback).toUpperCase();
  }

  function normalizeBarAppearance(appearance) {
    const app = appearance || {};
    const font = String(app.font_family || BAR_FONT_OPTIONS[0].value).trim() || BAR_FONT_OPTIONS[0].value;
    return {
      fill_color: normalizeHexColor(app.fill_color, "#FFA8BC"),
      gradient_color: normalizeHexColor(app.gradient_color, "#22C55E"),
      use_gradient: Boolean(app.use_gradient),
      show_decimals: Boolean(app.show_decimals),
      font_family: BAR_FONT_OPTIONS.some((o) => o.value === font) ? font : BAR_FONT_OPTIONS[0].value,
    };
  }

  function barAppearanceSignature(appearance) {
    return JSON.stringify(normalizeBarAppearance(appearance));
  }

  function barFillBackground(appearance) {
    const fill = (appearance && appearance.fill_color) || "#FFA8BC";
    if (appearance && appearance.use_gradient) {
      const end = appearance.gradient_color || "#22C55E";
      return `linear-gradient(90deg, ${fill}, ${end})`;
    }
    return fill;
  }

  function applyBarAppearance(appearance, { preview = false } = {}) {
    const app = appearance || state.bar_appearance || {};
    const bg = barFillBackground(app);
    const font = app.font_family || "system-ui, Segoe UI, sans-serif";
    if (goalBarFill) goalBarFill.style.background = bg;
    if (progressPanel) progressPanel.style.setProperty("--bar-fill-background", bg);
    if (progressPanel) progressPanel.style.setProperty("--bar-font-family", font);
    if (!preview) state.bar_appearance = { ...app };
  }

  function populateBarFontSelect() {
    if (!barFontFamilySelect || barFontFamilySelect.options.length) return;
    for (const opt of BAR_FONT_OPTIONS) {
      const el = document.createElement("option");
      el.value = opt.value;
      el.textContent = opt.label;
      barFontFamilySelect.appendChild(el);
    }
  }

  function collectBarAppearanceFromForm() {
    return normalizeBarAppearance({
      fill_color: barFillColorInput ? barFillColorInput.value : "#FFA8BC",
      gradient_color: barGradientColorInput ? barGradientColorInput.value : "#22C55E",
      use_gradient: Boolean(barUseGradientInput && barUseGradientInput.checked),
      show_decimals: Boolean(barShowDecimalsInput && barShowDecimalsInput.checked),
      font_family: barFontFamilySelect ? barFontFamilySelect.value : BAR_FONT_OPTIONS[0].value,
    });
  }

  function syncBarAppearanceForm(appearance) {
    barAppearanceFormSyncing = true;
    const app = normalizeBarAppearance(appearance || state.bar_appearance || collectBarAppearanceFromForm());
    if (barFillColorInput) barFillColorInput.value = app.fill_color;
    if (barGradientColorInput) barGradientColorInput.value = app.gradient_color;
    if (barUseGradientInput) barUseGradientInput.checked = app.use_gradient;
    if (barShowDecimalsInput) barShowDecimalsInput.checked = app.show_decimals;
    if (barFontFamilySelect) barFontFamilySelect.value = app.font_family;
    savedBarAppearanceSignature = barAppearanceSignature(collectBarAppearanceFromForm());
    applyBarAppearance(app, { preview: true });
    barAppearanceFormSyncing = false;
    updateBarAppearanceSaveButton();
  }

  function barAppearanceIsDirty() {
    if (!barAppearanceSaveBtn) return false;
    try {
      return barAppearanceSignature(collectBarAppearanceFromForm()) !== savedBarAppearanceSignature;
    } catch (_) {
      return false;
    }
  }

  function updateBarAppearanceSaveButton() {
    if (!barAppearanceSaveBtn || barAppearanceFormSyncing) return;
    const dirty = barAppearanceIsDirty();
    barAppearanceSaveBtn.disabled = !dirty;
    barAppearanceSaveBtn.classList.toggle("bar-pending", dirty);
    applyBarAppearance(collectBarAppearanceFromForm(), { preview: true });
  }

  function saveBarAppearance() {
    send({ type: "bar_appearance.save", bar_appearance: collectBarAppearanceFromForm() });
  }

  const DEFAULT_EFFECTS_CATALOG = {
    goal_complete: [
      { id: "none", label: "None" },
      { id: "glow", label: "Glow" },
      { id: "finish_shine", label: "Finish shine" },
      { id: "ring_burst", label: "Ring burst" },
      { id: "confetti", label: "Confetti" },
    ],
    points_added: [
      { id: "none", label: "None" },
      { id: "bar_flash", label: "Bar flash" },
      { id: "number_pop", label: "Number pop" },
      { id: "caption_glow", label: "Caption glow" },
    ],
  };
  const POINTS_EPSILON = 0.001;

  function effectsCatalog() {
    return state.effects_catalog
      || (state.user_config && state.user_config.effects_catalog)
      || DEFAULT_EFFECTS_CATALOG;
  }

  function normalizeProgressEffects(effects) {
    const fx = effects || {};
    const goalIds = new Set((effectsCatalog().goal_complete || []).map((o) => o.id));
    const pointIds = new Set((effectsCatalog().points_added || []).map((o) => o.id));
    const goal = String(fx.goal_complete || "none");
    const points = String(fx.points_added || "none");
    return {
      goal_complete: goalIds.has(goal) ? goal : "none",
      points_added: pointIds.has(points) ? points : "none",
      goal_complete_repeat: fx.goal_complete_repeat !== false,
    };
  }

  function goalCompleteRepeatEnabled(effects) {
    const fx = effects || state.progress_effects || {};
    return fx.goal_complete_repeat !== false;
  }

  function clearGoalCompleteRepeat() {
    if (goalCompleteRepeatTimer) {
      clearInterval(goalCompleteRepeatTimer);
      goalCompleteRepeatTimer = null;
    }
  }

  function startGoalCompleteRepeat(effectId, effects) {
    clearGoalCompleteRepeat();
    const id = effectId || "none";
    if (!goalCompleteRepeatEnabled(effects) || id === "none") return;
    goalCompleteRepeatTimer = setInterval(() => {
      const progress = state.progress || {};
      if (!progress.goal_id || !isGoalCompleteSnapshot(progressSnapshotFrom(progress))) {
        clearGoalCompleteRepeat();
        return;
      }
      playGoalCompleteEffect(id);
    }, GOAL_COMPLETE_REPEAT_MS);
  }

  function syncGoalCompleteRepeat(progress, effects) {
    const fx = normalizeProgressEffects(effects || state.progress_effects);
    const snapshot = progressSnapshotFrom(progress || {});
    if (isGoalCompleteSnapshot(snapshot) && fx.goal_complete !== "none" && goalCompleteRepeatEnabled(fx)) {
      if (!goalCompleteRepeatTimer) {
        startGoalCompleteRepeat(fx.goal_complete, fx);
      }
    } else {
      clearGoalCompleteRepeat();
    }
  }

  function progressEffectsSignature(effects) {
    return JSON.stringify(normalizeProgressEffects(effects));
  }

  function goalBarTrackEl() {
    return progressPanel ? progressPanel.querySelector(".goal-bar-track") : null;
  }

  function addFxWithCleanup(element, className, durationMs) {
    if (!element || !className) return;
    element.classList.remove(className);
    void element.offsetWidth;
    element.classList.add(className);
    const done = () => {
      element.classList.remove(className);
      element.removeEventListener("animationend", done);
    };
    element.addEventListener("animationend", done, { once: true });
    setTimeout(done, durationMs);
  }

  function pointsCaptionEl() {
    if (!goalPointsTextEl) return null;
    let inner = goalPointsTextEl.querySelector(".goal-points-caption");
    if (!inner) {
      inner = document.createElement("span");
      inner.className = "goal-points-caption";
      inner.textContent = goalPointsTextEl.textContent;
      goalPointsTextEl.textContent = "";
      goalPointsTextEl.appendChild(inner);
    }
    return inner;
  }

  function spawnConfetti(host, durationMs = 2800) {
    if (!host) return;
    host.classList.add("fx-confetti-host");
    const layer = document.createElement("div");
    layer.className = "fx-confetti-layer";
    const colors = ["#ef4444", "#3b82f6", "#eab308", "#22c55e", "#a855f7", "#ec4899", "#f97316"];
    for (let i = 0; i < 48; i++) {
      const piece = document.createElement("span");
      piece.className = "fx-confetti-piece";
      piece.style.setProperty("--fx-left", `${Math.random() * 100}%`);
      piece.style.setProperty("--fx-delay", `${Math.random() * 0.35}s`);
      piece.style.setProperty("--fx-drift", `${Math.random() * 70 - 35}px`);
      piece.style.setProperty("--fx-color", colors[i % colors.length]);
      piece.style.setProperty("--fx-rotate", `${Math.random() * 360}deg`);
      layer.appendChild(piece);
    }
    host.appendChild(layer);
    setTimeout(() => {
      layer.remove();
      if (!host.querySelector(".fx-confetti-layer")) {
        host.classList.remove("fx-confetti-host");
      }
    }, durationMs);
  }

  function playGoalCompleteEffect(effectId) {
    const id = effectId || "none";
    if (id === "none") return;
    if (id === "glow" || id === "ring_burst") {
      addFxWithCleanup(goalBarTrackEl(), `fx-goal-${id}`, id === "glow" ? 2000 : 1600);
      return;
    }
    if (id === "finish_shine") {
      addFxWithCleanup(goalBarFill, "fx-goal-finish_shine", 3400);
      return;
    }
    if (id === "confetti") {
      spawnConfetti(progressPanel || goalBarTrackEl(), 2800);
    }
  }

  function playPointsAddedEffect(effectId) {
    const id = effectId || "none";
    if (id === "none") return;
    if (id === "bar_flash") {
      addFxWithCleanup(goalBarFill, "fx-points-bar_flash", 450);
      return;
    }
    if (id === "number_pop") {
      addFxWithCleanup(pointsCaptionEl(), "fx-points-number_pop", 550);
      return;
    }
    if (id === "caption_glow") {
      addFxWithCleanup(pointsCaptionEl(), "fx-points-caption_glow", 850);
    }
  }

  function progressSnapshotFrom(progress) {
    return {
      goal_id: progress.goal_id || null,
      current_points: Number(progress.current_points) || 0,
      target_points: Number(progress.target_points) || 0,
    };
  }

  function isGoalCompleteSnapshot(snapshot) {
    const target = snapshot.target_points || 0;
    const current = snapshot.current_points || 0;
    return target > 0 && current >= target - POINTS_EPSILON;
  }

  function wasBelowGoalSnapshot(snapshot) {
    const target = snapshot.target_points || 0;
    const current = snapshot.current_points || 0;
    return target > 0 && current < target - POINTS_EPSILON;
  }

  function pointsIncreased(previous, current) {
    return current.current_points > previous.current_points + POINTS_EPSILON;
  }

  function maybeTriggerProgressEffects(prev, next, effectsOverride) {
    if (!next || !next.goal_id) {
      lastProgressSnapshot = null;
      clearGoalCompleteRepeat();
      return;
    }
    const effects = normalizeProgressEffects(effectsOverride || state.progress_effects);
    let previous = prev;
    if (previous && previous.goal_id !== next.goal_id) {
      previous = null;
      clearGoalCompleteRepeat();
    }
    const current = progressSnapshotFrom(next);
    if (!previous) {
      lastProgressSnapshot = current;
      syncGoalCompleteRepeat(next, effects);
      return;
    }
    if (
      effects.goal_complete !== "none"
      && isGoalCompleteSnapshot(current)
      && wasBelowGoalSnapshot(previous)
    ) {
      playGoalCompleteEffect(effects.goal_complete);
      startGoalCompleteRepeat(effects.goal_complete, effects);
    } else {
      syncGoalCompleteRepeat(next, effects);
    }
    if (effects.points_added !== "none" && pointsIncreased(previous, current)) {
      playPointsAddedEffect(effects.points_added);
    }
    lastProgressSnapshot = current;
  }

  function broadcastEffectPreview(channel, effectId) {
    send({ type: "progress_effects.preview", channel, effect_id: effectId });
  }

  function previewGoalCompleteEffect() {
    const id = goalCompleteEffectSelect ? goalCompleteEffectSelect.value : "none";
    if (!goalBarFill || id === "none") return;
    const savedWidth = goalBarFill.style.width;
    goalBarFill.style.width = "100%";
    playGoalCompleteEffect(id);
    broadcastEffectPreview("goal", id);
    const restoreMs = id === "confetti" ? 3200 : id === "finish_shine" ? 3600 : 2200;
    setTimeout(() => {
      if (goalBarFill) goalBarFill.style.width = savedWidth;
    }, restoreMs);
  }

  function previewPointsAddedEffect() {
    const id = pointsAddedEffectSelect ? pointsAddedEffectSelect.value : "none";
    playPointsAddedEffect(id);
    broadcastEffectPreview("points", id);
  }

  function populateProgressEffectSelects() {
    const catalog = effectsCatalog();
    const fill = (select, options) => {
      if (!select) return;
      const previous = select.value;
      select.replaceChildren();
      for (const opt of options || []) {
        const el = document.createElement("option");
        el.value = opt.id;
        el.textContent = opt.label;
        el.title = opt.description || opt.label;
        select.appendChild(el);
      }
      const ids = new Set((options || []).map((o) => o.id));
      if (ids.has(previous)) select.value = previous;
    };
    fill(goalCompleteEffectSelect, catalog.goal_complete);
    fill(pointsAddedEffectSelect, catalog.points_added);
  }

  function collectProgressEffectsFromForm() {
    return normalizeProgressEffects({
      goal_complete: goalCompleteEffectSelect ? goalCompleteEffectSelect.value : "none",
      points_added: pointsAddedEffectSelect ? pointsAddedEffectSelect.value : "none",
      goal_complete_repeat: Boolean(goalCompleteRepeatInput && goalCompleteRepeatInput.checked),
    });
  }

  function syncProgressEffectsForm(effects) {
    progressEffectsFormSyncing = true;
    const fx = normalizeProgressEffects(effects || state.progress_effects || collectProgressEffectsFromForm());
    if (goalCompleteEffectSelect) goalCompleteEffectSelect.value = fx.goal_complete;
    if (pointsAddedEffectSelect) pointsAddedEffectSelect.value = fx.points_added;
    if (goalCompleteRepeatInput) goalCompleteRepeatInput.checked = fx.goal_complete_repeat !== false;
    if (!state.progress_effects) state.progress_effects = { ...fx };
    savedProgressEffectsSignature = progressEffectsSignature(collectProgressEffectsFromForm());
    progressEffectsFormSyncing = false;
    updateProgressEffectsSaveButton();
  }

  function progressEffectsIsDirty() {
    if (!progressEffectsSaveBtn) return false;
    try {
      return progressEffectsSignature(collectProgressEffectsFromForm()) !== savedProgressEffectsSignature;
    } catch (_) {
      return false;
    }
  }

  function updateProgressEffectsSaveButton() {
    if (!progressEffectsSaveBtn || progressEffectsFormSyncing) return;
    const dirty = progressEffectsIsDirty();
    progressEffectsSaveBtn.disabled = !dirty;
    progressEffectsSaveBtn.classList.toggle("bar-pending", dirty);
  }

  function saveProgressEffects() {
    send({ type: "progress_effects.save", progress_effects: collectProgressEffectsFromForm() });
  }

  function bindNonNegativeInput(input, { decimal = false, maxDecimals = 2 } = {}) {
    input.addEventListener("keydown", (e) => {
      if (["e", "E", "+", "-"].includes(e.key)) e.preventDefault();
    });
    input.addEventListener("input", () => {
      let v = input.value;
      if (decimal) {
        v = v.replace(/[^0-9.]/g, "");
        const parts = v.split(".");
        if (parts.length > 2) v = parts[0] + "." + parts.slice(1).join("");
        if (parts.length === 2 && parts[1].length > maxDecimals) {
          v = parts[0] + "." + parts[1].slice(0, maxDecimals);
        }
      } else {
        v = v.replace(/\D/g, "");
      }
      if (input.value !== v) input.value = v;
    });
    input.addEventListener("blur", () => {
      if (input.value === "") return;
      const n = Number(input.value);
      if (!Number.isFinite(n) || n < 0) {
        input.value = "0";
        return;
      }
      if (decimal) input.value = formatRuleNumber(n);
    });
  }

  function readNonNegativeInt(input) {
    const n = parseInt(input.value, 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }

  function readNonNegativeDecimal(input, { maxDecimals = 2 } = {}) {
    const n = parseFloat(input.value);
    if (!Number.isFinite(n) || n < 0) return 0;
    const factor = 10 ** maxDecimals;
    return Math.round(n * factor) / factor;
  }

  function currencyCodes() {
    if (Array.isArray(state.supported_currencies) && state.supported_currencies.length) {
      return state.supported_currencies;
    }
    return Object.keys(state.exchange_rates.rates_to_eur || {}).sort();
  }

  function syncCurrencyDatalist() {
    const datalist = document.getElementById("currency-options");
    if (!datalist) return;
    datalist.innerHTML = "";
    for (const code of currencyCodes()) {
      const option = document.createElement("option");
      option.value = code;
      datalist.appendChild(option);
    }
  }

  function bindCurrencyInput(input, defaultCode = "EUR") {
    input.classList.add("currency-input");
    input.setAttribute("list", "currency-options");
    input.maxLength = 3;
    input.autocomplete = "off";
    input.value = defaultCode;
    input.addEventListener("input", () => {
      input.value = input.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3);
    });
  }

  function localDatetimeInputValue(date) {
    const d = date ? new Date(date) : new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function localDatetimeToIso(value) { return value ? new Date(value).toISOString() : null; }

  function renderProgress() {
    const progress = state.progress || {};
    const hasGoal = Boolean(progress.goal_id);
    goalNameEl.textContent = hasGoal ? progress.name : "No active goal";
    const current = progress.current_points || 0;
    const target = progress.target_points || 0;
    const pct = target > 0 ? Math.min(100, (current / target) * 100) : 0;
    if (goalBarFill) goalBarFill.style.width = pct + "%";
    const captionText = formatProgressPointsCaption(current, target, { hasGoal });
    const caption = pointsCaptionEl();
    if (caption) caption.textContent = captionText;
    else if (goalPointsTextEl) goalPointsTextEl.textContent = captionText;
    pointsChangeEl.hidden = !hasGoal;
    scheduleSyncDashboardColumnHeights();
  }

  function updateOverlayUrls() {
    const port = (state.user_config && state.user_config.app && state.user_config.app.ui_port) || 8080;
    const tokenParam = REQUIRE_WS_TOKEN && UI_TOKEN ? `&token=${encodeURIComponent(UI_TOKEN)}` : "";
    if (goalOverlayUrlInput) {
      goalOverlayUrlInput.value = `http://127.0.0.1:${port}/overlay?w=400&h=100${tokenParam}`;
    }
    if (subathonOverlayUrlInput) {
      subathonOverlayUrlInput.value = `http://127.0.0.1:${port}/timer?w=400&h=120${tokenParam}`;
    }
  }

  function formatSubathonDisplay(totalSeconds, showDays) {
    const total = Math.max(0, parseInt(totalSeconds, 10) || 0);
    if (showDays) {
      const days = Math.floor(total / 86400);
      const rem = total % 86400;
      const hours = Math.floor(rem / 3600);
      const rem2 = rem % 3600;
      const minutes = Math.floor(rem2 / 60);
      const seconds = rem2 % 60;
      return `${days} Days ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }
    const hours = Math.floor(total / 3600);
    const rem = total % 3600;
    const minutes = Math.floor(rem / 60);
    const seconds = rem % 60;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function normalizeTimerAppearance(app) {
    app = app || {};
    const font = String(app.font_family || BAR_FONT_OPTIONS[0].value).trim() || BAR_FONT_OPTIONS[0].value;
    return {
      font_family: BAR_FONT_OPTIONS.some((o) => o.value === font) ? font : BAR_FONT_OPTIONS[0].value,
      font_color: normalizeHexColor(app.font_color, "#FFFFFF"),
      show_days: Boolean(app.show_days),
    };
  }

  function timerAppearanceSignature(appearance) {
    return JSON.stringify(normalizeTimerAppearance(appearance));
  }

  function timerAppearanceIsDirty() {
    return timerAppearanceSignature(collectTimerAppearanceFromForm()) !== savedTimerAppearanceSignature;
  }

  function applyTimerAppearance(appearance, { preview = false } = {}) {
    const app = appearance || state.timer_appearance || {};
    const font = app.font_family || "system-ui, Segoe UI, sans-serif";
    const color = app.font_color || "#FFFFFF";
    if (subathonDisplayEl) {
      subathonDisplayEl.style.fontFamily = font;
      subathonDisplayEl.style.color = color;
    }
    if (subathonPanel) {
      subathonPanel.style.setProperty("--subathon-font-family", font);
      subathonPanel.style.setProperty("--subathon-font-color", color);
    }
    if (!preview) state.timer_appearance = { ...app };
  }

  function populateTimerFontSelect() {
    if (!timerFontFamilySelect || timerFontFamilySelect.options.length) return;
    for (const opt of BAR_FONT_OPTIONS) {
      const el = document.createElement("option");
      el.value = opt.value;
      el.textContent = opt.label;
      timerFontFamilySelect.appendChild(el);
    }
  }

  function collectTimerAppearanceFromForm() {
    return normalizeTimerAppearance({
      font_color: timerFontColorInput ? timerFontColorInput.value : "#FFFFFF",
      font_family: timerFontFamilySelect ? timerFontFamilySelect.value : BAR_FONT_OPTIONS[0].value,
      show_days: Boolean(timerShowDaysInput && timerShowDaysInput.checked),
    });
  }

  function syncTimerAppearanceForm(appearance) {
    timerAppearanceFormSyncing = true;
    const app = normalizeTimerAppearance(appearance || state.timer_appearance || collectTimerAppearanceFromForm());
    if (timerFontColorInput) timerFontColorInput.value = app.font_color;
    if (timerFontFamilySelect) timerFontFamilySelect.value = app.font_family;
    if (timerShowDaysInput) timerShowDaysInput.checked = app.show_days;
    savedTimerAppearanceSignature = timerAppearanceSignature(collectTimerAppearanceFromForm());
    applyTimerAppearance(app, { preview: true });
    timerAppearanceFormSyncing = false;
    updateTimerAppearanceSaveButton();
    renderSubathon();
  }

  function updateTimerAppearanceSaveButton() {
    if (!timerAppearanceSaveBtn || timerAppearanceFormSyncing) return;
    const dirty = timerAppearanceSignature(collectTimerAppearanceFromForm()) !== savedTimerAppearanceSignature;
    timerAppearanceSaveBtn.disabled = !dirty;
    timerAppearanceSaveBtn.classList.toggle("bar-pending", dirty);
    applyTimerAppearance(collectTimerAppearanceFromForm(), { preview: true });
    renderSubathon();
  }

  function saveTimerAppearance() {
    send({ type: "timer_appearance.save", timer_appearance: collectTimerAppearanceFromForm() });
  }

  function syncSubathonSettingsForm() {
    const app = (state.user_config && state.user_config.app) || {};
    const sub = state.subathon || {};
    if (subathonPointsInput) {
      subathonPointsInput.value = String(sub.points ?? app.subathon_points ?? 10);
    }
    if (subathonSecondsAddedInput) {
      subathonSecondsAddedInput.value = String(sub.seconds ?? app.subathon_seconds ?? 60);
    }
  }

  function renderSubathon() {
    const sub = state.subathon || {};
    const showDays = timerShowDaysInput
      ? timerShowDaysInput.checked
      : Boolean((state.timer_appearance || {}).show_days);
    if (subathonDisplayEl) {
      const display = sub.remaining_seconds != null
        ? formatSubathonDisplay(sub.remaining_seconds, showDays)
        : (sub.display || "00:00:00");
      subathonDisplayEl.textContent = display;
    }
    if (subathonPlayBtn) subathonPlayBtn.disabled = Boolean(sub.running);
    if (subathonPauseBtn) subathonPauseBtn.disabled = !sub.running;
    syncSubathonSettingsForm();
    updateOverlayUrls();
  }

  const LAYOUT_DEBUG = new URLSearchParams(location.search).has("debug_layout");

  let syncHeightsQueued = false;
  function scheduleSyncDashboardColumnHeights() {
    if (syncHeightsQueued) return;
    syncHeightsQueued = true;
    requestAnimationFrame(() => {
      syncHeightsQueued = false;
      syncDashboardColumnHeights();
    });
  }

  function logColumnHeights(phase) {
    if (!LAYOUT_DEBUG) return;
    const rows = [
      ["rules", panelRules],
      ["goals", panelGoals],
      ["monitors", panelMonitors],
    ].map(([name, el]) => ({
      column: name,
      rect_h: Math.round(el.getBoundingClientRect().height * 10) / 10,
      scroll_h: el.scrollHeight,
      style_height: el.style.height || "(css)",
    }));
    console.groupCollapsed(`[layout] ${phase}`);
    console.table(rows);
    if (dashboardTop) {
      console.log("dashboard-top rect:", Math.round(dashboardTop.getBoundingClientRect().height * 10) / 10);
    }
    console.groupEnd();
  }

  /** Row height = max(goals, monitors); rules scrolls when taller than viewport allows. */
  function syncDashboardColumnHeights() {
    if (!dashboardTop || !panelRules || !panelGoals || !panelMonitors) return;

    dashboardTop.style.height = "auto";
    dashboardTop.style.minHeight = "0";
    for (const el of [panelRules, panelGoals, panelMonitors]) {
      el.style.height = "auto";
      el.style.minHeight = "0";
      el.style.maxHeight = "none";
    }

    logColumnHeights("before measure");

    const goalsH = panelGoals.getBoundingClientRect().height;
    const monitorsH = panelMonitors.getBoundingClientRect().height;
    const minFromSideColumns = Math.max(goalsH, monitorsH, 1);

    const topOffset = dashboardTop.getBoundingClientRect().top;
    const viewportCap = Math.max(minFromSideColumns, window.innerHeight - topOffset - 24);

    const rulesH = panelRules.getBoundingClientRect().height;
    const rowH = Math.ceil(Math.max(minFromSideColumns, Math.min(rulesH, viewportCap)));

    dashboardTop.style.height = `${rowH}px`;
    dashboardTop.style.minHeight = `${rowH}px`;
    for (const el of [panelRules, panelGoals, panelMonitors]) {
      el.style.height = "100%";
      el.style.minHeight = "";
      el.style.maxHeight = "";
    }

    logColumnHeights(`after apply rowH=${rowH}`);

    if (LAYOUT_DEBUG) {
      const rects = [panelRules, panelGoals, panelMonitors].map((el) => el.getBoundingClientRect().height);
      const spread = Math.max(...rects) - Math.min(...rects);
      if (spread > 1) {
        console.warn(`[layout] column height mismatch: ${spread.toFixed(1)}px spread`, rects);
      }
    }
  }

  function renderGoalsSelect() {
    goalSelectEl.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = state.goals.length ? "— select —" : "Create first goal";
    goalSelectEl.appendChild(placeholder);
    for (const goal of state.goals) {
      const option = document.createElement("option");
      option.value = goal.id;
      option.textContent = `${goal.name} (${formatNumber(goal.target_points)})`;
      if (goal.id === state.active_goal_id) option.selected = true;
      goalSelectEl.appendChild(option);
    }
  }

  function rulesSignature(rules) {
    return JSON.stringify(rules);
  }

  function syncSavedRulesFromState() {
    savedRulesSignature = rulesSignature(state.point_rules || {});
    updateRulesSaveButton();
  }

  function updateRulesSaveButton() {
    if (!rulesSaveBtn || rulesFormSyncing) return;
    const dirty = rulesSignature(collectRulesFromForm()) !== savedRulesSignature;
    rulesSaveBtn.disabled = !dirty;
    rulesSaveBtn.classList.toggle("rules-pending", dirty);
  }

  function renderTierRuleCards(meta, rule) {
    const tierPoints = rule.tier_points || {};
    const tiers = tiersForEventType(meta.key);
    if (!tiers.length) {
      const card = document.createElement("div");
      card.className = "rule-card tier-rule-card";
      card.dataset.eventType = meta.key;
      const title = document.createElement("h4");
      title.textContent = meta.label;
      card.appendChild(title);
      const hint = document.createElement("p");
      hint.className = "muted";
      hint.textContent = emptyTierRuleHint(meta);
      card.appendChild(hint);
      rulesFieldsEl.appendChild(card);
      return;
    }
    for (const tier of tiers) {
      const card = document.createElement("div");
      card.className = "rule-card tier-rule-card";
      card.dataset.eventType = meta.key;
      card.dataset.tierKey = tier.key;
      const title = document.createElement("h4");
      title.textContent = tier.label;
      card.appendChild(title);
      const pts = tier.points ?? tierPoints[tier.key] ?? 0;
      card.appendChild(numberField(`tier_${tier.key}`, "Pts", pts, `${tier.label} pts`));
      rulesFieldsEl.appendChild(card);
    }
  }

  function renderRulesForm() {
    rulesFormSyncing = true;
    rulesFieldsEl.innerHTML = "";
        for (const meta of REVENUE_TYPES) {
          const rule = state.point_rules[meta.key] || {};
          if (usesTierRuleCards(meta, rule)) {
            renderTierRuleCards(meta, rule);
            continue;
          }
          const mode = effectiveRuleMode(meta, rule);
          const card = document.createElement("div");
          card.className = "rule-card";
          card.dataset.eventType = meta.key;
          const title = document.createElement("h4");
          title.textContent = meta.label;
          card.appendChild(title);
          if (mode === "per_quantity") {
            card.appendChild(numberField("points_per_unit", "Pts/unit", rule.points_per_unit ?? 0, "Pts per unit"));
          } else if (mode === "per_eur") {
            card.appendChild(numberField("points_per_eur", "Pts/EUR", rule.points_per_eur ?? 0, "Pts per EUR"));
          } else if (mode === "per_event") {
            card.appendChild(numberField("points_per_event", "Pts", rule.points_per_event ?? 0, "Points"));
          } else {
        const row = document.createElement("div");
        row.className = "tier-row";
        const tierPoints = rule.tier_points || {};
        const tiers = tiersForEventType(meta.key);
        for (const tier of tiers) {
          const label = `T${tier.label}`;
          const pts = tierPoints[tier.key] ?? 0;
          row.appendChild(numberField(`tier_${tier.key}`, label, pts, `${label} pts`));
        }
        card.appendChild(row);
      }
      rulesFieldsEl.appendChild(card);
    }
    rulesFormSyncing = false;
    updateRulesSaveButton();
  }

  function sendRevenueEventAction(eventId, actionType) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: actionType, event_id: eventId }));
  }

  function renderSessionRevenue() {
    if (!sessionRevenueBody) return;
    const events = state.session_revenue || [];
    sessionRevenueBody.innerHTML = "";
    if (sessionRevenueEmpty) sessionRevenueEmpty.hidden = events.length > 0;
    if (sessionRevenueTable) sessionRevenueTable.hidden = events.length === 0;
    for (const row of [...events].reverse()) {
      const tr = document.createElement("tr");
      if (row.is_test) tr.classList.add("is-test");
      if (row.is_valid === false) tr.classList.add("is-invalid");
      for (const key of ["platform", "type", "amount", "user", "status"]) {
        const td = document.createElement("td");
        td.textContent = row[key] ?? "—";
        tr.appendChild(td);
      }
      const actionsTd = document.createElement("td");
      actionsTd.className = "session-revenue-actions";
      if (row.id != null) {
        if (row.can_remove) {
          const removeBtn = document.createElement("button");
          removeBtn.type = "button";
          removeBtn.className = "secondary outline";
          removeBtn.textContent = "REMOVE";
          removeBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            sendRevenueEventAction(row.id, "revenue_event.invalidate");
          });
          actionsTd.appendChild(removeBtn);
        }
        if (row.can_add) {
          const addBtn = document.createElement("button");
          addBtn.type = "button";
          addBtn.className = "secondary outline";
          addBtn.textContent = "ADD";
          addBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            sendRevenueEventAction(row.id, "revenue_event.validate");
          });
          actionsTd.appendChild(addBtn);
        }
      }
      tr.appendChild(actionsTd);
      sessionRevenueBody.appendChild(tr);
    }
  }

  function numberField(name, label, value, placeholder) {
    const wrap = document.createElement("label");
    wrap.textContent = label + " ";
    const input = document.createElement("input");
    input.type = "text";
    input.inputMode = "numeric";
    input.name = name;
    input.value = formatRuleNumber(value);
    if (placeholder) input.placeholder = placeholder;
    bindNonNegativeInput(input, { decimal: true, maxDecimals: 2 });
    wrap.appendChild(input);
    return wrap;
  }

  function renderRatesDisplay() {
    const rates = state.exchange_rates.rates_to_eur || {};
    const fetched = state.exchange_rates.fetched_at;
    const source = state.exchange_rates.source || "";
    const parts = [];
    if (fetched) parts.push(`${source}, ${new Date(fetched).toLocaleString()}`);
    else if (source) parts.push(source);
    if (state.exchange_rates.attribution) parts.push(state.exchange_rates.attribution);
    ratesMetaEl.textContent = parts.length ? `(${parts.join(" · ")})` : "";
    syncCurrencyDatalist();
    ratesDisplayEl.innerHTML = "";
    for (const code of Object.keys(rates).sort()) {
      const span = document.createElement("span");
      span.textContent = `${code}: ${Number(rates[code]).toFixed(4)}`;
      ratesDisplayEl.appendChild(span);
    }
  }

  function renderTestEvents() {
    syncCurrencyDatalist();
    testEventsGrid.innerHTML = "";
    for (const meta of REVENUE_TYPES) {
      const card = document.createElement("div");
      card.className = "test-card";
      card.dataset.eventType = meta.key;
      const title = document.createElement("h4");
      title.textContent = meta.label;
      card.appendChild(title);
      const fields = document.createElement("div");
      fields.className = "test-card-fields";
      for (const spec of TEST_INPUTS[meta.key] || []) {
        if (spec.tierSelect) {
          const select = document.createElement("select");
          select.name = spec.key;
          const tiers = tiersForEventType(meta.key);
          if (!tiers.length) {
            const opt = document.createElement("option");
            opt.value = "";
            opt.textContent = "No tiers";
            select.appendChild(opt);
          } else {
            for (const tier of tiers) {
              const opt = document.createElement("option");
              // Scoring keys: Patreon = amount_cents, YouTube = level_id, Twitch = tier key.
              opt.value = tier.key;
              opt.textContent = tier.label;
              select.appendChild(opt);
            }
          }
          fields.appendChild(select);
          continue;
        }
        const input = document.createElement("input");
        input.type = "text";
        input.name = spec.key;
        input.placeholder = spec.placeholder;
        if (spec.currency) {
          bindCurrencyInput(input, meta.key === "youtube_super_sticker" ? "USD" : "EUR");
        } else {
          input.inputMode = spec.decimal ? "decimal" : "numeric";
          bindNonNegativeInput(input, { decimal: Boolean(spec.decimal) });
        }
        fields.appendChild(input);
      }
      card.appendChild(fields);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Send test";
      btn.addEventListener("click", () => {
        const overrides = {};
        for (const spec of TEST_INPUTS[meta.key] || []) {
          const field = card.querySelector(`[name="${spec.key}"]`);
          if (!field || field.value === "") continue;
          if (spec.tierSelect) {
            overrides[spec.key] = field.value;
          } else if (spec.currency) {
            overrides.currency = field.value.toUpperCase();
          } else if (spec.decimal) {
            overrides.amount = field.value;
          } else {
            overrides[spec.key] = readNonNegativeInt(field);
          }
        }
        send({ type: "test_event.inject", event_type: meta.key, overrides });
      });
      card.appendChild(btn);
      testEventsGrid.appendChild(card);
    }
  }

  function renderPatreonCampaignSelect() {
    const p = state.patreon;
    if (!p || !p.feature_enabled) {
      patreonCampaignRow.hidden = true;
      return;
    }
    patreonCampaignRow.hidden = false;
    const prev = patreonCampaignSelect.value;
    patreonCampaignSelect.innerHTML = "";
    for (const c of p.campaigns || []) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name;
      if (c.id === p.active_campaign_id) opt.selected = true;
      patreonCampaignSelect.appendChild(opt);
    }
    if (!patreonCampaignSwitching && prev && prev !== p.active_campaign_id) {
      patreonCampaignSelect.value = p.active_campaign_id || "";
    }
    if (p.load_error) {
      patreonStatusEl.textContent = p.load_error;
    } else if (!p.enabled) {
      patreonStatusEl.textContent = "Connect Patreon in Monitors to load campaigns and tiers.";
    } else {
      patreonStatusEl.textContent = `${(p.tiers || []).length} tier(s) for monitoring.`;
    }
  }

  const MONITOR_STATUS_LABELS = {
    idle: "Ready",
    authenticating: "Authenticating…",
    connecting: "Connecting…",
    active: "Active",
    error: "Error",
  };

  function requestMonitorConnect(monitorId) {
    send({ type: "monitor.connect.request", monitor_id: monitorId });
  }

  function requestMonitorDisconnect(monitorId) {
    send({ type: "monitor.disconnect.request", monitor_id: monitorId });
  }

  function streamlabsTokenConfigured() {
    return Boolean((state.user_config?.streamlabs?.socket_api_token || "").trim());
  }

  function renderMonitorStatus() {
    if (!monitorStatusList) return;
    monitorStatusList.innerHTML = "";
    for (const row of state.monitors || []) {
      const li = document.createElement("li");
      li.dataset.monitorId = row.id;
      const label = document.createElement("span");
      label.className = "monitor-label";
      label.textContent = row.label || row.id;
      const statusKey = row.status === "disabled" ? "idle" : (row.status || "idle");
      const statusGroup = document.createElement("span");
      statusGroup.className = "monitor-status-group";

      if (statusKey === "idle" || statusKey === "error") {
        const connectBtn = document.createElement("button");
        connectBtn.type = "button";
        connectBtn.className = "monitor-action-btn secondary outline";
        connectBtn.textContent = "Connect";
        connectBtn.title = `Connect ${row.label || row.id}`;
        connectBtn.addEventListener("click", () => requestMonitorConnect(row.id));
        statusGroup.appendChild(connectBtn);
      }
      if (statusKey === "authenticating" || statusKey === "connecting") {
        const cancelBtn = document.createElement("button");
        cancelBtn.type = "button";
        cancelBtn.className = "monitor-action-btn secondary outline";
        cancelBtn.textContent = "Cancel";
        cancelBtn.title = `Cancel ${row.label || row.id} connection`;
        cancelBtn.addEventListener("click", () => requestMonitorDisconnect(row.id));
        statusGroup.appendChild(cancelBtn);
      }
      if (statusKey === "active") {
        const disconnectBtn = document.createElement("button");
        disconnectBtn.type = "button";
        disconnectBtn.className = "monitor-action-btn secondary outline";
        disconnectBtn.textContent = "Disconnect";
        disconnectBtn.title = `Disconnect ${row.label || row.id}`;
        disconnectBtn.addEventListener("click", () => requestMonitorDisconnect(row.id));
        statusGroup.appendChild(disconnectBtn);
      }
      const badge = document.createElement("span");
      badge.className = `monitor-status status-${statusKey}`;
      badge.dataset.testid = `monitor-status-${row.id}`;
      if (statusKey === "authenticating") {
        const spinner = document.createElement("span");
        spinner.className = "monitor-auth-spinner";
        spinner.setAttribute("aria-hidden", "true");
        badge.appendChild(spinner);
        badge.appendChild(document.createTextNode(MONITOR_STATUS_LABELS.authenticating));
      } else {
        badge.textContent = MONITOR_STATUS_LABELS[statusKey] || statusKey;
      }
      statusGroup.appendChild(badge);
      li.appendChild(label);
      li.appendChild(statusGroup);
      let detailText = row.detail;
      if (row.id === "streamlabs" && !streamlabsTokenConfigured()
        && statusKey !== "active" && statusKey !== "connecting") {
        detailText = "Add your Streamlabs Socket API token on the Configuration tab, then save and connect.";
      }
      if (detailText && statusKey !== "authenticating") {
        const detail = document.createElement("span");
        detail.className = "monitor-detail muted";
        detail.textContent = detailText;
        li.appendChild(detail);
      }
      monitorStatusList.appendChild(li);
    }
  }

  function configSignature(cfg) {
    return JSON.stringify(cfg || {});
  }

  function collectConfigFromForm() {
    return {
      app: {
        enable_test_events: document.getElementById("cfg-enable-test-events").checked,
        log_chat_messages_for_testing: document.getElementById("cfg-log-chat-testing").checked,
        require_ws_token: document.getElementById("cfg-require-ws-token").checked,
        base_currency: document.getElementById("cfg-base-currency").value.trim().toUpperCase(),
        ui_port: Number(document.getElementById("cfg-ui-port").value) || 8080,
        twitch_sub_resub_dedupe_seconds: Number(document.getElementById("cfg-twitch-sub-resub-dedupe").value) || 0,
      },
      streamlabs: {
        socket_api_token: document.getElementById("cfg-streamlabs-token").value.trim(),
      },
      patreon: {
        client_id: document.getElementById("cfg-patreon-client-id").value.trim(),
        client_secret: document.getElementById("cfg-patreon-client-secret").value.trim(),
      },
      youtube: {
        oauth_client_json: document.getElementById("cfg-youtube-oauth-client-json").value.trim(),
      },
    };
  }

  // Project the saved user_config into the SAME shape collectConfigFromForm()
  // produces, so configSignature() compares like-for-like and the Save button
  // accurately reflects whether the form has unsaved edits.
  function collectConfigFromUserConfig(userConfig) {
    const cfg = userConfig || {};
    const app = cfg.app || {};
    const sl = cfg.streamlabs || {};
    return {
      app: {
        enable_test_events: Boolean(app.enable_test_events),
        log_chat_messages_for_testing: Boolean(app.log_chat_messages_for_testing),
        require_ws_token: Boolean(app.require_ws_token),
        base_currency: (app.base_currency || "EUR").toUpperCase(),
        ui_port: Number(app.ui_port) || 8080,
        twitch_sub_resub_dedupe_seconds: Number(app.twitch_sub_resub_dedupe_seconds) || 0,
      },
      streamlabs: {
        socket_api_token: sl.socket_api_token || "",
      },
      patreon: {
        client_id: (cfg.patreon && cfg.patreon.client_id) || "",
        client_secret: (cfg.patreon && cfg.patreon.client_secret) || "",
      },
      youtube: {
        oauth_client_json: (cfg.youtube && cfg.youtube.oauth_client_json) || "",
      },
    };
  }

  function collectTwitchChannelFromForm() {
    return (dashTwitchChannelInput && dashTwitchChannelInput.value.trim()) || "";
  }

  function renderTwitchChannelForm() {
    if (!dashTwitchChannelInput) return;
    twitchChannelFormSyncing = true;
    const tw = (state.user_config && state.user_config.twitch) || {};
    dashTwitchChannelInput.value = tw.channel_name || "";
    twitchChannelFormSyncing = false;
    updateTwitchChannelSaveButton();
  }

  function syncSavedTwitchChannelFromState() {
    const tw = (state.user_config && state.user_config.twitch) || {};
    savedTwitchChannel = tw.channel_name || "";
    updateTwitchChannelSaveButton();
  }

  function setTwitchChannelSaveStatus(message, kind) {
    if (!dashTwitchChannelStatus) return;
    dashTwitchChannelStatus.textContent = message || "";
    dashTwitchChannelStatus.classList.remove("is-success", "is-error");
    if (kind) dashTwitchChannelStatus.classList.add(kind === "success" ? "is-success" : "is-error");
    if (kind === "error" && message) pushUserAlert(message, { source: "config" });
  }

  function updateTwitchChannelSaveButton() {
    if (!dashTwitchChannelSaveBtn || twitchChannelFormSyncing) return;
    const value = collectTwitchChannelFromForm();
    const dirty = value !== savedTwitchChannel;
    dashTwitchChannelSaveBtn.disabled = !dirty;
    dashTwitchChannelSaveBtn.classList.toggle("twitch-channel-pending", dirty);
  }

  function renderConfigForm() {
    const cfg = state.user_config || {};
    configFormSyncing = true;
    const app = cfg.app || {};
    document.getElementById("cfg-enable-test-events").checked = Boolean(app.enable_test_events);
    document.getElementById("cfg-log-chat-testing").checked = Boolean(app.log_chat_messages_for_testing);
    document.getElementById("cfg-require-ws-token").checked = Boolean(app.require_ws_token);
    document.getElementById("cfg-base-currency").value = app.base_currency || "EUR";
    document.getElementById("cfg-ui-port").value = String(app.ui_port ?? 8080);
    document.getElementById("cfg-twitch-sub-resub-dedupe").value = String(
      app.twitch_sub_resub_dedupe_seconds ?? 300
    );
    const sl = cfg.streamlabs || {};
    document.getElementById("cfg-streamlabs-token").value = sl.socket_api_token || "";
    const pa = cfg.patreon || {};
    document.getElementById("cfg-patreon-client-id").value = pa.client_id || "";
    document.getElementById("cfg-patreon-client-secret").value = pa.client_secret || "";
    const yt = cfg.youtube || {};
    document.getElementById("cfg-youtube-oauth-client-json").value = yt.oauth_client_json || "";
    configFormSyncing = false;
    updateConfigSaveButton();
  }

  function syncSavedConfigFromState() {
    savedConfigSignature = configSignature(collectConfigFromUserConfig(state.user_config));
    updateConfigSaveButton();
  }

  function configFormIsValid() {
    const cfg = collectConfigFromForm();
    const currency = cfg.app.base_currency;
    if (!currency || currency.length !== 3) return false;
    if (state.supported_currencies.length && !state.supported_currencies.includes(currency)) {
      return false;
    }
    const portRaw = document.getElementById("cfg-ui-port").value.trim();
    if (portRaw === "") return false;
    const port = Number(portRaw);
    if (!Number.isFinite(port) || port < 1024 || port > 65535) return false;
    const dedupeRaw = document.getElementById("cfg-twitch-sub-resub-dedupe").value.trim();
    if (dedupeRaw === "") return false;
    const dedupe = Number(dedupeRaw);
    if (!Number.isFinite(dedupe) || dedupe < 0 || dedupe > 3600) return false;
    return true;
  }

  function updateConfigSaveButton() {
    if (!configSaveBtn || configFormSyncing) return;
    const valid = configFormIsValid();
    const dirty = configSignature(collectConfigFromForm()) !== savedConfigSignature;
    configSaveBtn.disabled = !(valid && dirty);
    configSaveBtn.classList.toggle("config-pending", valid && dirty);
  }

  function setConfigSaveStatus(message, kind) {
    if (!configSaveStatus) return;
    configSaveStatus.textContent = message || "";
    configSaveStatus.classList.remove("is-success", "is-error");
    if (kind) configSaveStatus.classList.add(kind === "success" ? "is-success" : "is-error");
    if (kind === "error" && message) pushUserAlert(message, { source: "config" });
  }

  function applyTestEventsVisibility() {
    if (!dashboardEl) return;
    dashboardEl.classList.toggle("test-events-hidden", !state.allow_test_events);
  }

  function renderState() {
    // Dirty-guards: never clobber in-progress user edits when a fresh
    // server state arrives. We still update the internal "saved" state
    // so the diff highlight stays accurate, but the form values are
    // only re-synced if the user hasn't started editing.
    if (!barAppearanceIsDirty()) {
      if (state.bar_appearance) syncBarAppearanceForm(state.bar_appearance);
      else if (state.user_config && state.user_config.bar_appearance) {
        state.bar_appearance = state.user_config.bar_appearance;
        syncBarAppearanceForm(state.bar_appearance);
      }
    }
    if (!timerAppearanceIsDirty()) {
      if (state.timer_appearance) syncTimerAppearanceForm(state.timer_appearance);
      else if (state.user_config && state.user_config.timer_appearance) {
        state.timer_appearance = state.user_config.timer_appearance;
        syncTimerAppearanceForm(state.timer_appearance);
      }
    }
    if (!progressEffectsIsDirty()) {
      if (state.progress_effects) syncProgressEffectsForm(state.progress_effects);
      else if (state.user_config && state.user_config.progress_effects) {
        state.progress_effects = state.user_config.progress_effects;
        syncProgressEffectsForm(state.progress_effects);
      }
    }
    if (state.user_config && state.user_config.effects_catalog) {
      state.effects_catalog = state.user_config.effects_catalog;
    }
    renderProgress();
    renderSubathon();
    updateOverlayUrls();
    renderGoalsSelect();
    renderPatreonCampaignSelect();
    renderRulesForm();
    renderRatesDisplay();
    applyTestEventsVisibility();
    if (state.allow_test_events) renderTestEvents();
    syncMonitorAlerts(state.monitors);
    syncPatreonAlert(state.patreon);
    renderMonitorStatus();
    renderSessionRevenue();
    renderTwitchChannelForm();
    renderConfigForm();
    scheduleSyncDashboardColumnHeights();
  }

  function collectRulesFromForm() {
    const rules = {};
    for (const meta of REVENUE_TYPES) {
      const saved = state.point_rules[meta.key] || {};
      const rule = { mode: effectiveRuleMode(meta, saved) };
      if (usesTierRuleCards(meta, saved)) {
        rule.tier_points = {};
        const tierCards = rulesFieldsEl.querySelectorAll(`[data-event-type="${meta.key}"][data-tier-key]`);
        for (const tierCard of tierCards) {
          const tierKey = tierCard.dataset.tierKey;
          rule.tier_points[tierKey] = readNumber(tierCard, `tier_${tierKey}`);
        }
        rules[meta.key] = rule;
        continue;
      }
      const card = rulesFieldsEl.querySelector(`[data-event-type="${meta.key}"]:not([data-tier-key])`);
      if (!card) continue;
      if (rule.mode === "per_quantity") rule.points_per_unit = readNumber(card, "points_per_unit");
      else if (rule.mode === "per_eur") rule.points_per_eur = readNumber(card, "points_per_eur");
      else if (rule.mode === "per_event") rule.points_per_event = readNumber(card, "points_per_event");
      else {
        rule.tier_points = {};
        for (const tier of tiersForEventType(meta.key)) rule.tier_points[tier.key] = readNumber(card, `tier_${tier.key}`);
      }
      rules[meta.key] = rule;
    }
    return rules;
  }

  function readNumber(container, name) {
    const input = container.querySelector(`input[name="${name}"]`);
    return input ? readNonNegativeDecimal(input) : 0;
  }

  let goalStartTouched = false;
  goalStartInput.addEventListener("input", () => { goalStartTouched = true; });
  goalStartInput.addEventListener("change", () => { goalStartTouched = true; });
  bindNonNegativeInput(document.getElementById("points-amount"), { decimal: true, maxDecimals: 2 });
  populateBarFontSelect();
  populateTimerFontSelect();
  populateProgressEffectSelects();
  syncBarAppearanceForm(state.bar_appearance);
  syncProgressEffectsForm(state.progress_effects);
  syncTimerAppearanceForm(
    state.timer_appearance || (state.user_config && state.user_config.timer_appearance) || {},
  );
  initThemeToggle();
  [barFillColorInput, barGradientColorInput, barUseGradientInput, barShowDecimalsInput, barFontFamilySelect].forEach((el) => {
    if (!el) return;
    el.addEventListener("input", () => {
      updateBarAppearanceSaveButton();
      if (el === barShowDecimalsInput) renderProgress();
    });
    el.addEventListener("change", () => {
      updateBarAppearanceSaveButton();
      if (el === barShowDecimalsInput) renderProgress();
    });
  });
  if (barAppearanceSaveBtn) barAppearanceSaveBtn.addEventListener("click", saveBarAppearance);
  if (progressEffectsSaveBtn) progressEffectsSaveBtn.addEventListener("click", saveProgressEffects);
  if (goalCompletePreviewBtn) goalCompletePreviewBtn.addEventListener("click", previewGoalCompleteEffect);
  if (pointsAddedPreviewBtn) pointsAddedPreviewBtn.addEventListener("click", previewPointsAddedEffect);
  for (const el of [goalCompleteEffectSelect, pointsAddedEffectSelect, goalCompleteRepeatInput]) {
    if (!el) continue;
    el.addEventListener("input", updateProgressEffectsSaveButton);
    el.addEventListener("change", updateProgressEffectsSaveButton);
  }
  function openOverlayUrl(input) {
    const url = input && input.value ? input.value.trim() : "";
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  }
  if (goalOverlayOpenBtn) {
    goalOverlayOpenBtn.addEventListener("click", () => openOverlayUrl(goalOverlayUrlInput));
  }
  if (subathonOverlayOpenBtn) {
    subathonOverlayOpenBtn.addEventListener("click", () => openOverlayUrl(subathonOverlayUrlInput));
  }
  if (timerAppearanceSaveBtn) timerAppearanceSaveBtn.addEventListener("click", saveTimerAppearance);
  for (const el of [timerFontColorInput, timerFontFamilySelect, timerShowDaysInput]) {
    if (!el) continue;
    el.addEventListener("input", updateTimerAppearanceSaveButton);
    el.addEventListener("change", updateTimerAppearanceSaveButton);
  }
  if (goalOverlayUrlInput) {
    goalOverlayUrlInput.addEventListener("focus", () => goalOverlayUrlInput.select());
  }
  if (state.allow_test_events) renderTestEvents();

  if (typeof ResizeObserver !== "undefined") {
    const columnResizeObserver = new ResizeObserver(scheduleSyncDashboardColumnHeights);
    columnResizeObserver.observe(panelGoals);
    columnResizeObserver.observe(panelMonitors);
    columnResizeObserver.observe(rulesFieldsEl);
    if (patreonCampaignRow) columnResizeObserver.observe(patreonCampaignRow);
  }
  window.addEventListener("resize", scheduleSyncDashboardColumnHeights);

  document.getElementById("rules-form").addEventListener("input", () => {
    if (!rulesFormSyncing) updateRulesSaveButton();
  });

  configForm.addEventListener("input", () => {
    if (!configFormSyncing) updateConfigSaveButton();
  });
  if (dashTwitchChannelInput) {
    dashTwitchChannelInput.addEventListener("input", () => {
      if (!twitchChannelFormSyncing) updateTwitchChannelSaveButton();
    });
  }
  if (dashTwitchChannelSaveBtn) {
    dashTwitchChannelSaveBtn.addEventListener("click", () => {
      if (dashTwitchChannelSaveBtn.disabled) return;
      pendingTwitchChannelSave = true;
      setTwitchChannelSaveStatus("");
      send({
        type: "config.save",
        config: { twitch: { channel_name: collectTwitchChannelFromForm() } },
      });
    });
  }
  document.getElementById("cfg-base-currency").addEventListener("input", (e) => {
    e.target.value = e.target.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3);
  });
  configForm.addEventListener("submit", (e) => {
    e.preventDefault();
    if (configSaveBtn.disabled) return;
    setConfigSaveStatus("");
    send({ type: "config.save", config: collectConfigFromForm() });
  });

  document.getElementById("rules-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (rulesSaveBtn.disabled) return;
    send({ type: "point_rules.save", rules: collectRulesFromForm() });
  });

  document.getElementById("goal-create-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (!goalStartTouched) {
      goalStartInput.value = localDatetimeInputValue();
    }
    send({
      type: "goal.create",
      name: document.getElementById("goal-name-input").value.trim(),
      target_points: Number(document.getElementById("goal-target-input").value),
      started_at: localDatetimeToIso(goalStartInput.value),
      select: true,
    });
    e.target.reset();
    goalStartTouched = false;
    goalStartInput.value = localDatetimeInputValue();
  });

  goalSelectEl.addEventListener("change", () => {
    if (goalSelectEl.value) send({ type: "goal.select", goal_id: goalSelectEl.value });
  });

  patreonCampaignSelect.addEventListener("change", () => {
    const campaign_id = patreonCampaignSelect.value;
    if (!campaign_id || campaign_id === (state.patreon && state.patreon.active_campaign_id)) return;
    patreonCampaignSwitching = true;
    send({ type: "patreon.campaign.select", campaign_id });
  });

  document.getElementById("goal-delete-btn").addEventListener("click", () => {
    const goal_id = goalSelectEl.value;
    if (goal_id && confirm("Delete this goal?")) send({ type: "goal.delete", goal_id });
  });

  const pointsAmountInput = document.getElementById("points-amount");

  document.getElementById("points-add-btn").addEventListener("click", () => {
    send({ type: "goal.points_change", amount: readNonNegativeDecimal(pointsAmountInput), add: true });
  });

  document.getElementById("points-remove-btn").addEventListener("click", () => {
    send({ type: "goal.points_change", amount: readNonNegativeDecimal(pointsAmountInput), add: false });
  });

  document.getElementById("points-reset-btn").addEventListener("click", () => {
    if (!confirm("Reset the active goal progress to 0 points?")) return;
    send({ type: "goal.points_reset" });
  });

  if (subathonPlayBtn) {
    subathonPlayBtn.addEventListener("click", () => send({ type: "subathon.play" }));
  }
  if (subathonPauseBtn) {
    subathonPauseBtn.addEventListener("click", () => send({ type: "subathon.pause" }));
  }
  if (subathonApplyTimeBtn) {
    subathonApplyTimeBtn.addEventListener("click", () => {
      send({
        type: "subathon.set_time",
        hours: parseInt(subathonHoursInput.value, 10) || 0,
        minutes: parseInt(subathonMinutesInput.value, 10) || 0,
        seconds: parseInt(subathonSecondsInput.value, 10) || 0,
      });
    });
  }
  if (subathonSaveSettingsBtn) {
    subathonSaveSettingsBtn.addEventListener("click", () => {
      send({
        type: "subathon.save_settings",
        points: parseInt(subathonPointsInput.value, 10) || 1,
        seconds: parseInt(subathonSecondsAddedInput.value, 10) || 1,
      });
    });
  }
  if (subathonOverlayUrlInput) {
    subathonOverlayUrlInput.addEventListener("focus", () => subathonOverlayUrlInput.select());
  }

  document.getElementById("test-delete-all-btn").addEventListener("click", () => {
    if (confirm("Delete all test revenue transactions from the database?")) send({ type: "test_event.delete_all" });
  });

  if (alertsToggleBtn) {
    alertsToggleBtn.addEventListener("click", () => setAlertsVisible(!alertsVisible));
  }
  if (alertsClearBtn) {
    alertsClearBtn.addEventListener("click", () => clearUserAlerts());
  }
  renderAlerts();

  let logsVisible = false;
  document.getElementById("log-toggle-btn").addEventListener("click", () => {
    logsVisible = !logsVisible;
    logPanel.classList.toggle("collapsed", !logsVisible);
    document.getElementById("log-toggle-btn").textContent = logsVisible ? "Hide logs" : "Show logs";
  });

  let testEventsVisible = false;
  document.getElementById("test-toggle-btn").addEventListener("click", () => {
    testEventsVisible = !testEventsVisible;
    testPanel.classList.toggle("collapsed", !testEventsVisible);
    document.getElementById("test-toggle-btn").textContent = testEventsVisible ? "Hide test events" : "Show test events";
  });

  const ratesPanel = document.getElementById("rates-panel");
  let ratesVisible = false;
  document.getElementById("rates-toggle-btn").addEventListener("click", () => {
    ratesVisible = !ratesVisible;
    ratesPanel.classList.toggle("collapsed", !ratesVisible);
    document.getElementById("rates-toggle-btn").textContent = ratesVisible ? "Hide exchange rates" : "Show exchange rates";
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `tab-${tab}`);
      });
    });
  });

  function requestRestart() {
    if (!confirm("Restart the application? Monitors will stop briefly and reload with saved settings.")) return;
    if (!send({ type: "app.restart.request" })) {
      pushUserAlert("Cannot restart: not connected to the app. Wait a moment and try again, or refresh the page.");
    }
  }

  function setAppBusy(kind) {
    const restarting = kind === "restarting";
    const shuttingDown = kind === "shutting_down";
    if (restartBtn) {
      restartBtn.disabled = restarting || shuttingDown;
      restartBtn.textContent = restarting ? "Restarting…" : "Restart";
    }
    if (shutdownBtn) {
      shutdownBtn.disabled = restarting || shuttingDown;
      shutdownBtn.textContent = shuttingDown ? "Shutting down…" : "Shutdown";
    }
  }

  async function waitForServerAndReconnect() {
    if (restartReconnecting) return;
    restartReconnecting = true;
    showLoadingOverlay("Loading...");
    const maxAttempts = 60;
    for (let i = 0; i < maxAttempts; i++) {
      try {
        const response = await fetch(window.location.origin + "/", { method: "GET", cache: "no-store" });
        if (response.ok) break;
      } catch (_) { /* server not up yet */ }
      if (i === maxAttempts - 1) {
        appendLog("[app] restart timed out waiting for server");
        restartInProgress = false;
        hideLoadingOverlay();
        setAppBusy();
        restartReconnecting = false;
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (ws) {
      ws.onclose = null;
      try { ws.close(); } catch (_) { /* already closed */ }
    }
    connectWebSocket();
    restartReconnecting = false;
  }

  function finishShutdownUi() {
    shutdownInProgress = false;
    window.close();
    setTimeout(() => {
      if (!document.hidden) {
        showLoadingOverlay("Shutdown complete. You can now close this tab.");
      }
    }, 400);
  }

  function handleWebSocketMessage(event) {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "log" && typeof message.line === "string") {
      appendLog(message.line);
      return;
    }
    if (message.type === "error") {
      pushUserAlert(message.message || "Something went wrong.", { source: "server" });
      return;
    }
    if (message.type === "state") {
      const prevProgressSnapshot = lastProgressSnapshot ? { ...lastProgressSnapshot } : null;
      if (restartInProgress) {
        restartInProgress = false;
        hideLoadingOverlay();
        setAppBusy();
        showDashboardTab();
        appendLog("[app] restart complete");
      }
      state.goals = message.goals || [];
      state.active_goal_id = message.active_goal_id || null;
      state.point_rules = message.point_rules || {};
      state.exchange_rates = message.exchange_rates || {};
      state.progress = message.progress || {};
      if (message.subathon) state.subathon = message.subathon;
      if (message.timer_appearance) state.timer_appearance = message.timer_appearance;
      else if (state.user_config && state.user_config.timer_appearance) {
        state.timer_appearance = state.user_config.timer_appearance;
      }
      state.patreon = message.patreon || state.patreon;
      state.youtube = message.youtube || state.youtube;
      state.monitors = message.monitors || state.monitors || [];
      state.session_revenue = message.session_revenue || [];
      state.user_config = message.user_config || state.user_config;
      if (message.bar_appearance) state.bar_appearance = message.bar_appearance;
      else if (state.user_config && state.user_config.bar_appearance) {
        state.bar_appearance = state.user_config.bar_appearance;
      }
      if (message.progress_effects) state.progress_effects = message.progress_effects;
      else if (state.user_config && state.user_config.progress_effects) {
        state.progress_effects = state.user_config.progress_effects;
      }
      if (state.user_config && state.user_config.effects_catalog) {
        state.effects_catalog = state.user_config.effects_catalog;
      }
      state.allow_test_events = Boolean(message.allow_test_events);
      if (Array.isArray(message.supported_currencies)) {
        state.supported_currencies = message.supported_currencies;
        syncCurrencyDatalist();
      }
      patreonCampaignSwitching = false;
      renderState();
      maybeTriggerProgressEffects(prevProgressSnapshot, state.progress, message.progress_effects);
      syncSavedRulesFromState();
      syncSavedConfigFromState();
      syncSavedTwitchChannelFromState();
      return;
    }
    if (message.type === "bar_appearance.saved") {
      state.bar_appearance = message.bar_appearance || state.bar_appearance;
      syncBarAppearanceForm(state.bar_appearance);
      renderProgress();
      appendLog("[ui] bar appearance saved");
      return;
    }
    if (message.type === "progress_effects.saved") {
      state.progress_effects = message.progress_effects || state.progress_effects;
      syncProgressEffectsForm(state.progress_effects);
      appendLog("[ui] progress effects saved");
      return;
    }
    if (message.type === "progress_effects") {
      state.progress_effects = normalizeProgressEffects(message);
      if (!progressEffectsIsDirty()) {
        syncProgressEffectsForm(state.progress_effects);
      }
      return;
    }
    if (message.type === "bar_appearance") {
      if (!barAppearanceIsDirty()) {
        syncBarAppearanceForm(normalizeBarAppearance(message));
      }
      return;
    }
    if (message.type === "config.saved") {
      if (pendingTwitchChannelSave) {
        pendingTwitchChannelSave = false;
        savedTwitchChannel = collectTwitchChannelFromForm();
        updateTwitchChannelSaveButton();
        setTwitchChannelSaveStatus("Twitch username saved.", "success");
        setTimeout(() => setTwitchChannelSaveStatus(""), 4000);
      } else {
        setConfigSaveStatus(message.message || "Saved successfully.", "success");
        syncSavedConfigFromState();
        setTimeout(() => setConfigSaveStatus(""), 8000);
      }
      return;
    }
    if (message.type === "session_revenue") {
      state.session_revenue = message.events || [];
      renderSessionRevenue();
      return;
    }
    if (message.type === "app.shutting_down") {
      appendLog("[app] shutting down…");
      setAppBusy("shutting_down");
      shutdownInProgress = true;
      showLoadingOverlay("Shutting down...");
      return;
    }
    if (message.type === "app.restarting") {
      appendLog("[app] restarting…");
      setAppBusy("restarting");
      restartInProgress = true;
      showLoadingOverlay("Loading...");
      return;
    }
    if (message.type === "app.shutdown.complete") {
      appendLog("[app] shutdown complete");
      finishShutdownUi();
      return;
    }
    if (message.type === "progress") {
      const prevSnapshot = lastProgressSnapshot ? { ...lastProgressSnapshot } : null;
      state.progress = {
        goal_id: message.goal_id,
        name: message.name,
        current_points: message.current_points,
        target_points: message.target_points,
        percent: message.percent,
      };
      if (message.bar_appearance && !barAppearanceIsDirty()) {
        syncBarAppearanceForm(message.bar_appearance);
      }
      if (message.progress_effects) {
        state.progress_effects = normalizeProgressEffects(message.progress_effects);
      }
      renderProgress();
      maybeTriggerProgressEffects(prevSnapshot, state.progress, message.progress_effects);
      return;
    }
    if (message.type === "subathon") {
      state.subathon = {
        remaining_seconds: message.remaining_seconds,
        running: message.running,
        display: message.display,
        show_days: message.show_days,
        points: message.points,
        seconds: message.seconds,
      };
      renderSubathon();
      return;
    }
    if (message.type === "timer_appearance.saved") {
      state.timer_appearance = message.timer_appearance || state.timer_appearance;
      syncTimerAppearanceForm(state.timer_appearance);
      appendLog("[ui] timer appearance saved");
      return;
    }
    if (message.type === "timer_appearance") {
      if (!timerAppearanceIsDirty()) {
        syncTimerAppearanceForm(normalizeTimerAppearance(message));
      }
      return;
    }
    if (message.type === "subathon.settings.saved") {
      if (subathonSettingsStatus) {
        subathonSettingsStatus.textContent = message.message || "Saved.";
        setTimeout(() => { subathonSettingsStatus.textContent = ""; }, 4000);
      }
      return;
    }
    if (message.type === "test_event.deleted") {
      appendLog(`[test] deleted ${message.count} test transaction(s)`);
    }
  }

  function resetAppControlFlags() {
    restartInProgress = false;
    restartReconnecting = false;
    dashboardReconnecting = false;
    shutdownInProgress = false;
    hideLoadingOverlay();
    setAppBusy();
  }

  function stopWsPing() {
    if (wsPingTimer) {
      clearInterval(wsPingTimer);
      wsPingTimer = null;
    }
  }

  function startWsPing() {
    stopWsPing();
    wsPingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        send({ type: "ping" });
      }
    }, WS_PING_INTERVAL_MS);
  }

  const RECONNECT_SERVER_DEAD_MS = 10000;
  const RECONNECT_POLL_MS = 500;

  async function waitForServerReachable() {
    const deadline = Date.now() + RECONNECT_SERVER_DEAD_MS;
    while (Date.now() < deadline) {
      try {
        const response = await fetch(window.location.origin + "/", { method: "GET", cache: "no-store" });
        if (response.ok) return true;
      } catch (_) { /* server not up */ }
      await new Promise((resolve) => setTimeout(resolve, RECONNECT_POLL_MS));
    }
    return false;
  }

  const UNREACHABLE_TAB_CLOSE_MS = 3000;

  function showReconnectUnreachable() {
    dashboardReconnecting = false;
    const message =
      "The application is not reachable. Restart it from your terminal or shortcut. When you relaunch the app, a new dashboard tab will open.";
    showLoadingOverlay(message);
    pushUserAlert(message, { source: "connection" });
    appendLog("[app] reconnect failed — application not reachable");
    setTimeout(() => {
      try { window.close(); } catch (_) { /* tab may not be closable */ }
    }, UNREACHABLE_TAB_CLOSE_MS);
  }

  async function reconnectDashboardWebSocket() {
    if (shutdownInProgress || restartInProgress || restartReconnecting || dashboardReconnecting) {
      return;
    }
    dashboardReconnecting = true;
    appendLog("[app] dashboard connection lost; reconnecting…");
    showLoadingOverlay("Reconnecting…");
    const reachable = await waitForServerReachable();
    if (!reachable) {
      showReconnectUnreachable();
      return;
    }
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      try { ws.close(); } catch (_) { /* already closed */ }
    }
    connectWebSocket();
  }

  function connectWebSocket() {
    stopWsPing();
    const tokenSuffix = REQUIRE_WS_TOKEN && UI_TOKEN ? `?token=${encodeURIComponent(UI_TOKEN)}` : "";
    ws = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws${tokenSuffix}`);
    ws.onopen = () => {
      resetAppControlFlags();
      startWsPing();
    };
    ws.onmessage = handleWebSocketMessage;
    ws.onclose = () => {
      stopWsPing();
      appendLog("[log stream disconnected]");
      if (shutdownInProgress) finishShutdownUi();
      else if (restartInProgress) void waitForServerAndReconnect();
      else {
        resetAppControlFlags();
        void reconnectDashboardWebSocket();
      }
    };
    ws.onerror = () => {
      appendLog("[log stream error]");
      pushUserAlert("Connection to the app failed. Try refreshing the page.");
    };
  }

  restartBtn.addEventListener("click", requestRestart);

  function requestAppShutdown() {
    if (restartInProgress || shutdownInProgress) return;
    shutdownInProgress = true;
    setAppBusy("shutting_down");
    showLoadingOverlay("Shutting down...");
    send({ type: "app.shutdown.request" });
  }

  document.getElementById("shutdown-btn").addEventListener("click", () => {
    if (!confirm("Shut down the application? Monitors and the UI will stop.")) return;
    if (!send({ type: "app.shutdown.request" })) {
      pushUserAlert("Cannot shut down: not connected to the app. Wait a moment and try again, or refresh the page.");
      return;
    }
    shutdownInProgress = true;
    setAppBusy("shutting_down");
    showLoadingOverlay("Shutting down...");
  });

  window.addEventListener("pagehide", () => requestAppShutdown());

  connectWebSocket();
})();
