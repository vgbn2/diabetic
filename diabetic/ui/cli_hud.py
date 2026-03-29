import asyncio
from datetime import datetime, timezone
from typing import Optional
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Console
from rich.text import Text

from diabetic.config import config
from diabetic.registry import MetabolicSnapshot

class RealTimeHUD:
    """
    Premium CLI Dashboard for Bio-Quant.
    Displays metabolic state, forecasts, and alert status in real-time.
    """
    def __init__(self):
        self.console = Console()
        self.layout = Layout()
        self._setup_layout()

    def _setup_layout(self):
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3),
        )
        self.layout["main"].split_row(
            Layout(name="metrics", ratio=1),
            Layout(name="status", ratio=1),
        )

    def _get_header(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right", ratio=1)
        grid.add_row(
            Text("DIABETES-1-predictor", style="bold cyan"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        return Panel(grid, style="white on blue")

    def _get_metrics_table(self, snapshot: Optional[MetabolicSnapshot], prediction: float) -> Table:
        table = Table(title="Live Metabolic Signal", expand=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_column("Unit", style="dim")

        if snapshot:
            unit = "mmol/L" if config.PREFER_MMOL else "mg/dL"
            table.add_row("Glucose", f"{snapshot.filtered_value:.1f}", unit)
            table.add_row("Velocity", f"{snapshot.velocity:+.2f}", f"{unit}/min")
            table.add_row("Acceleration", f"{snapshot.acceleration:+.3f}", f"{unit}/min²")
            
            # Cardiac Metrics
            bpm = snapshot.bpm if snapshot.bpm else "MOCK"
            hrv = f"{snapshot.hrv:.1f}" if snapshot.hrv else "---"
            table.add_row("Heart Rate", f"{bpm}", "bpm")
            table.add_row("HRV (RMSSD)", hrv, "ms")
            
            table.add_row("30m Forecast", f"{prediction:.1f}", style="bold yellow")
        else:
            table.add_row("Glucose", "WAITING...", "")

        return table

    def _get_status_panel(self, alert_status: str = "IDLE") -> Panel:
        color = "green" if alert_status == "IDLE" else "red"
        return Panel(
            Text(alert_status, justify="center", style=f"bold {color}"),
            title="System Status",
            border_style=color
        )

    def generate_display(self, snapshot: Optional[MetabolicSnapshot] = None, prediction: float = 0.0, alert_status: str = "IDLE") -> Layout:
        self.layout["header"].update(self._get_header())
        self.layout["metrics"].update(self._get_metrics_table(snapshot, prediction))
        self.layout["status"].update(self._get_status_panel(alert_status))
        self.layout["footer"].update(Panel(Text(f"Polling Nightscout every {config.DATA_POLLING_INTERVAL}s...", justify="center", style="dim")))
        return self.layout

    async def run_live(self, coordinator):
        """Connects to the coordinator and runs the live display."""
        with Live(self.generate_display(), refresh_per_second=1, screen=True) as live:
            while coordinator.is_running:
                latest_snap = coordinator.snapshots[-1] if coordinator.snapshots else None
                # Fetch prediction from forecaster for HUD
                pred = coordinator.forecaster.predict_30m(coordinator.snapshots) if latest_snap else 0.0
                
                # Simple logic to show last alert status
                status = "IDLE"
                # This could be improved to show the actual last alert type
                
                live.update(self.generate_display(latest_snap, pred, status))
                await asyncio.sleep(1)

if __name__ == "__main__":
    # Test HUD standalone
    hud = RealTimeHUD()
    from rich.console import Console
    Console().print(hud.generate_display())
