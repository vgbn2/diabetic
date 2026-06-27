/* Bio-Quant TWA — recent-glucose history chart (read-only). */
BioAuth.applyTheme();
BioAuth.requireContextOrGate();

async function load() {
    var count = document.getElementById("count");
    try {
        var data = await apiJson("/api/v1/forecast");
        var pts = data.points || [];
        if (!pts.length) { count.innerText = "No recent readings yet."; return; }

        var ctx = document.getElementById("histChart").getContext("2d");
        new Chart(ctx, {
            type: "line",
            data: {
                labels: pts.map(function (_, i) { return i; }),
                datasets: [{
                    data: pts,
                    borderColor: "#38bdf8",
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: true,
                    backgroundColor: "rgba(56,189,248,0.05)"
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
        count.innerText = pts.length + " recent readings (mmol/L)";
    } catch (e) {
        count.innerText = "Could not load history.";
    }
}

load();
