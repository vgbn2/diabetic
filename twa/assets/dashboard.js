/* Bio-Quant TWA — live dashboard logic. */
BioAuth.applyTheme();
BioAuth.requireContextOrGate();

var chart = null;
var _lastForecast = { horizon: [], horizon_1d: [] };
var _activeHorizon = "4h";

function initChart() {
    var ctx = document.getElementById("horizonChart").getContext("2d");
    chart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [{
                label: "Predicted Path",
                data: [],
                borderColor: "#38bdf8",
                borderWidth: 3,
                fill: true,
                backgroundColor: "rgba(56, 189, 248, 0.05)",
                tension: 0.4,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { display: false },
                y: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#64748b" } }
            }
        }
    });
}

function setHorizon(mode) {
    _activeHorizon = mode;
    document.getElementById("btn-4h").classList.toggle("active", mode === "4h");
    document.getElementById("btn-1d").classList.toggle("active", mode === "1d");
    renderHorizon();
}

function renderHorizon() {
    if (!chart) return;
    var pts = _activeHorizon === "1d" ? _lastForecast.horizon_1d : _lastForecast.horizon;
    var label = document.getElementById("horizon-label");
    if (_activeHorizon === "1d" && (!pts || !pts.length)) {
        label.innerText = "Circadian model learning (needs 24h)";
        chart.data.datasets[0].data = [];
        chart.data.labels = [];
        chart.update();
        return;
    }
    label.innerText = _activeHorizon === "1d" ? "Circadian Rhythm (24h)" : "Metabolic Horizon (4h)";
    if (pts && pts.length) {
        chart.data.datasets[0].data = pts;
        chart.data.labels = Array(pts.length).fill("");
        chart.update();
    }
}

function rangeClass(v) {
    if (v < 4.0) return "g-low";
    if (v > 10.0) return "g-high";
    return "g-in";
}

async function updateHUD() {
    try {
        var data = await apiJson("/api/v1/hud");
        var gv = document.getElementById("glucose-val");
        gv.innerText = data.glucose.toFixed(1);
        gv.className = "glucose-value " + rangeClass(data.glucose);

        var velStr = data.velocity > 0 ? "+" : "";
        document.getElementById("velocity-val").innerText =
            data.trend + " " + velStr + data.velocity.toFixed(2) + "/min";
        document.getElementById("carbs-val").innerText = data.active_carbs.toFixed(1) + "g";
        document.getElementById("insulin-val").innerText = data.active_insulin.toFixed(2) + "U";
        document.getElementById("last-update").innerText = data.last_update || "LIVE";

        // Haptic warning on dangerous excursions.
        if (BioAuth.tg && (data.glucose < 4.0 || data.glucose > 13.0)) {
            try { BioAuth.tg.HapticFeedback.notificationOccurred("warning"); } catch (e) {}
        }
    } catch (e) { console.error("HUD bridge offline", e); }
}

async function updateForecast() {
    try {
        var data = await apiJson("/api/v1/forecast");
        _lastForecast = { horizon: data.horizon || [], horizon_1d: data.horizon_1d || [] };
        renderHorizon();
    } catch (e) { /* forecast optional */ }
}

initChart();
updateHUD();
updateForecast();
setInterval(function () { updateHUD(); updateForecast(); }, 5000);
