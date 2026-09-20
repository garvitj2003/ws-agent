#!/usr/bin/env python3
"""
Friday Real-Time Terminal Telemetry & Debug Stream
Run this script on your laptop to receive live, structured traces of all requests,
Jev reflex classifications, database queries, and Groq LLM generations in real-time.

Usage:
    python scripts/laptop_monitor.py --server ws://localhost:8765
    python scripts/laptop_monitor.py --server ws://<your-server-ip>:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import sys
import uuid
from datetime import datetime

import websockets
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()


def get_default_device_id() -> str:
    hostname = socket.gethostname().lower().replace(" ", "-")
    return f"laptop:{hostname}"


def format_duration(ms: float) -> str:
    if ms < 100:
        return f"[bold green]{ms:.1f}ms[/bold green]"
    elif ms < 500:
        return f"[bold yellow]{ms:.1f}ms[/bold yellow]"
    else:
        return f"[bold red]{ms:.1f}ms[/bold red]"


def render_debug_trace(body: dict) -> None:
    trace_id = body.get("trace_id", "unknown")
    req = body.get("request", {})
    jev = body.get("jev_system1", {})
    db = body.get("database", {})
    groq = body.get("groq_system2", {})
    total_ms = body.get("total_pipeline_ms", 0.0)

    # 1. Header Banner
    header_table = Table(show_header=False, box=None, expand=True)
    header_table.add_column("Key", style="bold cyan", width=14)
    header_table.add_column("Value")

    source_device = req.get("source", "unknown")
    user_query = req.get("text", "")
    ts = body.get("timestamp", datetime.now().isoformat())

    header_table.add_row("🚀 Trace ID:", f"[bold white]{trace_id}[/bold white] (Total: {format_duration(total_ms)})")
    header_table.add_row("📱 Source:", f"[magenta]{source_device}[/magenta] at [dim]{ts}[/dim]")
    header_table.add_row("💬 User Query:", f"[bold bright_white]\"{user_query}\"[/bold bright_white]")

    # 2. Jev System 1 Reflex Panel
    op = jev.get("operation", "chat")
    entity = jev.get("entity", "none")
    urgency = jev.get("urgency", "routine")
    is_destructive = jev.get("is_destructive", False)
    jev_lat = jev.get("latency_ms", 0.0)

    op_color = {
        "create": "green",
        "search": "cyan",
        "update": "yellow",
        "delete": "red",
        "overview": "magenta",
        "device_action": "bright_blue",
    }.get(op, "white")

    jev_table = Table(show_header=False, box=None, expand=True)
    jev_table.add_column("Label", style="bold yellow", width=16)
    jev_table.add_column("Detail")

    jev_table.add_row("Operation:", f"[{op_color} bold][{op.upper()}][/{op_color} bold] -> Entity: [bold cyan]{entity}[/bold cyan]")
    jev_table.add_row("Urgency / Safety:", f"Urgency: [bold]{urgency}[/bold] | Destructive: [{'red' if is_destructive else 'green'}]{is_destructive}[/{'red' if is_destructive else 'green'}]")
    jev_table.add_row("Parameters:", f"[dim]{json.dumps(jev.get('parameters', {}), indent=2)}[/dim]")
    jev_table.add_row("Latency:", format_duration(jev_lat))

    jev_panel = Panel(
        jev_table,
        title=f"⚡ [bold yellow]Jev System 1 Reflex[/bold yellow] ({format_duration(jev_lat)})",
        border_style="yellow",
        box=box.ROUNDED,
    )

    # 3. Database Execution Panel
    db_op = db.get("operation", "none")
    db_entity = db.get("entity", entity)
    sql_text = db.get("sql_executed", "-- No SQL statement --")
    sql_params = db.get("sql_parameters", {})
    db_lat = db.get("latency_ms", 0.0)
    rows_affected = db.get("rows_affected", 0)
    db_summary = db.get("result_summary", "")

    db_table = Table(show_header=False, box=None, expand=True)
    db_table.add_column("Label", style="bold blue", width=16)
    db_table.add_column("Detail")

    db_table.add_row("Target Entity:", f"[bold cyan]{db_entity}[/bold cyan] ({db_op})")
    db_table.add_row("Result:", f"[bold green]{db_summary}[/bold green] (Rows: {rows_affected})")
    if sql_params:
        db_table.add_row("Bound Params:", f"[dim]{json.dumps(sql_params)}[/dim]")
    db_table.add_row("Latency:", format_duration(db_lat))

    syntax_sql = Syntax(sql_text, "sql", theme="monokai", line_numbers=False, word_wrap=True)

    db_content = Table(show_header=False, box=None, expand=True)
    db_content.add_column("Content")
    db_content.add_row(db_table)
    db_content.add_row(Text("Executed SQL:", style="bold blue"))
    db_content.add_row(syntax_sql)

    db_panel = Panel(
        db_content,
        title=f"🗄️ [bold blue]PostgreSQL Dynamic Execution[/bold blue] ({format_duration(db_lat)})",
        border_style="blue",
        box=box.ROUNDED,
    )

    # 4. Groq Voice Generation Panel
    groq_model = groq.get("model", "openai/gpt-oss-20b")
    speech = groq.get("speech_reply", "")
    groq_lat = groq.get("latency_ms", 0.0)

    groq_table = Table(show_header=False, box=None, expand=True)
    groq_table.add_column("Label", style="bold magenta", width=16)
    groq_table.add_column("Detail")

    groq_table.add_row("Model:", f"[bold white]{groq_model}[/bold white]")
    groq_table.add_row("Friday Voice:", f"[bold italic bright_green]\"{speech}\"[/bold italic bright_green]")
    groq_table.add_row("Latency:", format_duration(groq_lat))

    groq_panel = Panel(
        groq_table,
        title=f"🎙️ [bold magenta]Groq Voice Persona (Friday)[/bold magenta] ({format_duration(groq_lat)})",
        border_style="magenta",
        box=box.ROUNDED,
    )

    # Combine All into Master Card
    main_table = Table(show_header=False, box=None, expand=True)
    main_table.add_column("Card")
    main_table.add_row(header_table)
    main_table.add_row(jev_panel)
    main_table.add_row(db_panel)
    main_table.add_row(groq_panel)

    master_panel = Panel(
        main_table,
        title=f"[bold bright_cyan]🛰️ TELEMETRY TRACE: {trace_id}[/bold bright_cyan]",
        subtitle=f"[dim]Total Pipeline: {format_duration(total_ms)}[/dim]",
        border_style="bright_cyan",
        box=box.DOUBLE,
    )

    console.print()
    console.print(master_panel)
    console.print()


async def listen_for_traces(server_url: str, device_id: str, device_name: str) -> None:
    console.print(
        Panel(
            f"[bold green]Connected to Friday WebSocket Agent Hub[/bold green]\n"
            f"Server: [cyan]{server_url}[/cyan]\n"
            f"Device ID: [magenta]{device_id}[/magenta]\n"
            f"Device Name: [white]{device_name}[/white]\n"
            f"[dim]Waiting for live telemetry traces, Jev decisions, and SQL execution logs...[/dim]",
            title="[bold yellow]Friday Live Terminal Monitor[/bold yellow]",
            border_style="green",
            box=box.ROUNDED,
        )
    )

    while True:
        try:
            async with websockets.connect(server_url) as ws:
                # 1. Send Register Envelope
                reg_envelope = {
                    "id": str(uuid.uuid4()),
                    "type": "register",
                    "source": device_id,
                    "target": "server",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "body": {
                        "client_type": "laptop",
                        "device_name": device_name,
                        "capabilities": ["terminal", "debug_trace", "exec"],
                    },
                }
                await ws.send(json.dumps(reg_envelope))

                # 2. Stream Inbound Envelopes
                async for raw_message in ws:
                    try:
                        data = json.loads(raw_message)
                        msg_type = data.get("type")

                        if msg_type == "debug_trace":
                            render_debug_trace(data.get("body", {}))

                        elif msg_type == "ack":
                            console.print(f"[dim green]✓ [ACK] {data.get('body', {}).get('details', 'Ready')}[/dim green]")

                        elif msg_type == "action":
                            body = data.get("body", {})
                            cmd = body.get("command", "")
                            console.print(Panel(f"[bold red]Received execution command:[/bold red]\n[yellow]{cmd}[/yellow]", title="⚡ Action Received", border_style="red"))

                        elif msg_type == "msg":
                            text = data.get("body", {}).get("text", "")
                            console.print(f"[bold cyan]💬 [Message from {data.get('source')}]:[/bold cyan] {text}")

                    except json.JSONDecodeError:
                        console.print(f"[red]Could not parse message: {raw_message}[/red]")

        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError) as e:
            console.print(f"[yellow]⚠️ Connection lost to {server_url} ({e}). Reconnecting in 3 seconds...[/yellow]")
            await asyncio.sleep(3)
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}. Reconnecting in 3 seconds...[/red]")
            await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser(description="Friday Live Terminal Monitor & Telemetry Stream")
    parser.add_argument(
        "--server",
        default=os.getenv("WS_SERVER_URL", "ws://localhost:8765"),
        help="WebSocket server URL (e.g. ws://127.0.0.1:8765 or ws://remote-ip:8765)",
    )
    parser.add_argument("--id", default=get_default_device_id(), help="Laptop Device ID")
    parser.add_argument("--name", default=f"{platform.system()} Terminal Monitor", help="Device friendly name")

    args = parser.parse_args()

    try:
        asyncio.run(listen_for_traces(args.server, args.id, args.name))
    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped by user. Goodbye![/dim]")


if __name__ == "__main__":
    main()
