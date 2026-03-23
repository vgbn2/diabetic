"""
dashboard.py - High-fidelity Metabolic Dashboard for Bio-Quant.
Inspired by the Quant-Arb Bot UI.
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bio-Quant | Metabolic Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;500;600;700&display=swap');
        body { font-family: 'Inter', sans-serif; background-color: #0b0e11; color: #cbd5e1; }
        .font-mono { font-family: 'JetBrains+Mono', monospace; }
        .bg-panel { background-color: #131722; border: 1px solid #1e222d; }
        .text-cyan-glow { color: #22d3ee; text-shadow: 0 0 10px rgba(34,211,238,0.3); }
        .text-rose-glow { color: #fb7185; text-shadow: 0 0 10px rgba(251,113,133,0.3); }
        .status-badge { padding: 4px 12px; border-radius: 9999px; font-weight: 700; font-size: 0.75rem; border: 1px solid currentColor; }
        .STABLE { color: #22c55e; background: rgba(34,197,94,0.1); }
        .CRITICAL_HYPO, .FAINT_RISK { color: #f43f5e; background: rgba(244,63,94,0.1); }
        .WARNING_HYPER, .CAUTION, .STRESS_DEVIATION { color: #fbbf24; background: rgba(251,191,36,0.1); }
        .log-container::-webkit-scrollbar { width: 4px; }
        .log-container::-webkit-scrollbar-thumb { background: #1e222d; border-radius: 4px; }
    </style>
</head>
<body class="p-4 md:p-8">
    <!-- Header / Status Bar -->
    <div class="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
        <div class="flex items-center gap-4">
            <h1 class="text-2xl font-bold tracking-tighter text-white">BIO-QUANT <span class="text-cyan-400">AI</span></h1>
            <div id="status" class="status-badge STABLE">SYSTEM ONLINE</div>
        </div>
        <div class="flex gap-8 text-sm font-mono">
            <div><span class="text-slate-500 uppercase">UPTIME:</span> <span id="uptime" class="text-slate-300">00:00:00</span></div>
            <div><span class="text-slate-500 uppercase">MODE:</span> <span class="text-cyan-400">INFERENCE_LIVE</span></div>
        </div>
    </div>

    <!-- Main Grid -->
    <div class="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        <!-- Left Column: Charts -->
        <div class="lg:col-span-8 space-y-6">
            <!-- Glucose Chart -->
            <div class="bg-panel rounded-xl p-6">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-sm font-bold text-slate-400 uppercase tracking-widest">Metabolic Trend (SGV)</h2>
                    <div id="current-sgv" class="text-2xl font-mono font-bold text-cyan-400">-- mg/dL</div>
                </div>
                <div id="glucose-chart" class="w-full h-[350px]"></div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- HRV Chart -->
                <div class="bg-panel rounded-xl p-6">
                    <h2 class="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4">HRV (RMSSD)</h2>
                    <div id="hrv-chart" class="w-full h-[200px]"></div>
                </div>
                <!-- Pulse Chart -->
                <div class="bg-panel rounded-xl p-6">
                    <h2 class="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4">Pulse (BPM)</h2>
                    <div id="pulse-chart" class="w-full h-[200px]"></div>
                </div>
            </div>
        </div>

        <!-- Right Column: Metrics & Logs -->
        <div class="lg:col-span-4 space-y-6">
            <!-- Stress Gauge -->
            <div class="bg-panel rounded-xl p-6 text-center">
                <h2 class="text-sm font-bold text-slate-400 uppercase tracking-widest mb-6">Dynamic Stress Index</h2>
                <div id="dsi-value" class="text-6xl font-mono font-bold text-white mb-2">1.00</div>
                <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden flex">
                    <div id="dsi-bar" class="bg-cyan-400 h-full transition-all duration-500" style="width: 33%"></div>
                </div>
                <div class="flex justify-between text-[10px] font-mono mt-2 text-slate-500">
                    <span>RELAXED</span>
                    <span>NOMINAL</span>
                    <span>EXTREME</span>
                </div>
            </div>

            <!-- Live Alert Log -->
            <div class="bg-panel rounded-xl p-6">
                <h2 class="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4">Safety Audit Log</h2>
                <div id="log" class="log-container h-[430px] overflow-y-auto font-mono text-[11px] space-y-2">
                    <div class="text-slate-600">[SYSTEM] Initialization complete...</div>
                    <div class="text-slate-600">[SYSTEM] Inference workers online...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const $ = (id) => document.getElementById(id);
        const startTime = Date.now();

        const chartOptions = {
            layout: { background: { color: 'transparent' }, textColor: '#64748b', fontSize: 10 },
            grid: { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
            timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#1e222d' },
            rightPriceScale: { borderColor: '#1e222d' },
        };

        const glucoseChart = LightweightCharts.createChart($('glucose-chart'), chartOptions);
        const glucoseSeries = glucoseChart.addAreaSeries({ 
            lineColor: '#22d3ee', topColor: 'rgba(34, 211, 238, 0.4)', bottomColor: 'rgba(34, 211, 238, 0)',
            lineWidth: 2, priceFormat: { type: 'price', precision: 0, minMove: 1 }
        });

        const hrvChart = LightweightCharts.createChart($('hrv-chart'), chartOptions);
        const hrvSeries = hrvChart.addLineSeries({ color: '#818cf8', lineWidth: 2 });

        const pulseChart = LightweightCharts.createChart($('pulse-chart'), chartOptions);
        const pulseSeries = pulseChart.addLineSeries({ color: '#fb7185', lineWidth: 2 });

        async function poll() {
            try {
                const res = await fetch('/api/state');
                const data = await res.json();
                
                if (data.error) return;

                // Update Status & DSI
                $('status').innerText = `SYSTEM ${data.status.replace('_', ' ')}`;
                $('status').className = `status-badge ${data.status}`;
                $('dsi-value').innerText = data.dsi.toFixed(2);
                $('dsi-bar').style.width = `${Math.min(100, (data.dsi / 3.0) * 100)}%`;
                $('dsi-bar').style.backgroundColor = data.dsi > 1.8 ? '#f43f5e' : '#22d3ee';

                // Update Uptime
                const diff = Math.floor((Date.now() - startTime) / 1000);
                $('uptime').innerText = new Date(diff * 1000).toISOString().substr(11, 8);

                // Update Charts
                const sort = (arr) => arr.sort((a,b) => a.time - b.time);
                if (data.glucose.length) {
                    const sortedG = sort(data.glucose);
                    glucoseSeries.setData(sortedG);
                    $('current-sgv').innerText = `${sortedG[sortedG.length-1].value} mg/dL`;
                }
                if (data.hrv.length) hrvSeries.setData(sort(data.hrv));
                if (data.pulse.length) pulseSeries.setData(sort(data.pulse));

                // Add to Log if status changed
                if (data.status !== "STABLE") {
                    const time = new Date().toLocaleTimeString();
                    const logLine = document.createElement('div');
                    logLine.className = 'text-rose-400';
                    logLine.innerHTML = `<span class="text-slate-600">[${time}]</span> <span class="font-bold">${data.status}</span> detected. Check alerts.`;
                    $('log').prepend(logLine);
                    if ($('log').children.length > 50) $('log').lastChild.remove();
                }

            } catch (e) { console.error(e); }
        }

        setInterval(poll, 2000);
        poll();
    </script>
</body>
</html>
"""
