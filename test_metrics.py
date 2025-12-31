"""Quick test to view collected metrics from a running REX session."""

from rex_main.metrics import metrics
import time

print("=== REX Metrics Summary ===\n")

while True:
    stats = metrics.get_session_stats()
    commands = metrics.get_command_frequency()
    recent = metrics.get_recent_transcriptions(limit=5)

    print("\033[2J\033[H")  # Clear screen
    print("=== REX Metrics Dashboard (Console Mode) ===\n")

    print(f"Session Duration: {stats['session_duration_s']:.1f}s")
    print(f"Total Commands:   {stats['total_matched'] + stats['total_unmatched']}")
    print(f"Match Rate:       {stats['match_rate_percent']}%")
    print(f"Avg E2E Latency:  {stats['avg_e2e_ms'] or 0:.0f}ms")
    print()

    print("Latency Breakdown:")
    print(f"  VAD:     {stats['avg_vad_ms'] or 0:.0f}ms")
    print(f"  Whisper: {stats['avg_whisper_ms'] or 0:.0f}ms")
    print(f"  Execute: {stats['avg_execute_ms'] or 0:.0f}ms")
    print()

    print("Top Commands:")
    for cmd in commands[:5]:
        print(f"  {cmd['command']:20s} {cmd['count']:3d} uses  (avg: {cmd['avg_execute_ms']:.0f}ms)")

    print("\nRecent Activity:")
    for item in recent[:5]:
        matched = "✓" if item['matched'] else "✗"
        print(f"  {matched} {item['time']} | {item['text'][:40]:40s} | {item['e2e_ms'] or 0:.0f}ms")

    print("\nPress Ctrl+C to exit")
    time.sleep(1)
