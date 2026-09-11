import asyncio
import logging
from bleak import BleakScanner
from rich.console import Console
from rich.table import Table

async def scan():
    console = Console()
    console.print("[bold cyan]Bio-Quant Hardware Discovery[/bold cyan]")
    console.print("Scanning for metabolic sensors (Heart Rate, Glucose BLE)...")
    
    scanner = BleakScanner()
    devices = await scanner.discover(timeout=10.0)
    
    if not devices:
        console.print("[bold red]No BLE devices found nearby.[/bold red]")
        return

    table = Table(title="Nearby BLE Devices")
    table.add_column("Address (MAC)", style="cyan", no_wrap=True)
    table.add_column("Name", style="magenta")
    table.add_column("RSSI", justify="right", style="green")

    for d in devices:
        table.add_row(d.address, d.name or "Unknown", str(d.rssi))

    console.print(table)
    console.print("\n[yellow]Tip:[/yellow] Set [bold]HEART_RATE_SENSOR_ADDRESS[/bold] in your .env to the correct MAC.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(scan())
    except KeyboardInterrupt:
        pass
