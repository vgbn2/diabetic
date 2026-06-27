/* Bio-Quant TWA — Telegram WebApp auth helper.
   Builds the Authorization header the FastAPI bridge expects:
     "tma <initData>"  in Telegram, or  "dev <token>"  for browser testing. */
window.BioAuth = (function () {
    var tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;

    function initData() { return (tg && tg.initData) || ""; }
    function devToken() { try { return localStorage.getItem("bq_dev_token") || ""; } catch (e) { return ""; } }

    function authHeader() {
        var id = initData();
        if (id) return "tma " + id;
        var dev = devToken();
        if (dev) return "dev " + dev;
        return "";
    }

    function hasContext() { return !!initData() || !!devToken(); }

    function applyTheme() {
        if (!tg) return;
        try { tg.ready(); tg.expand(); } catch (e) {}
        var p = tg.themeParams || {};
        var root = document.documentElement.style;
        if (p.bg_color) root.setProperty("--bg-color", p.bg_color);
        if (p.text_color) root.setProperty("--text-primary", p.text_color);
        if (p.hint_color) root.setProperty("--text-muted", p.hint_color);
        if (p.button_color) root.setProperty("--accent-blue", p.button_color);
    }

    function requireContextOrGate() {
        if (!hasContext() && location.pathname !== "/login") {
            location.href = "/login";
        }
    }

    return {
        tg: tg,
        initData: initData,
        devToken: devToken,
        authHeader: authHeader,
        hasContext: hasContext,
        applyTheme: applyTheme,
        requireContextOrGate: requireContextOrGate
    };
})();
