#!/usr/bin/env python
"""Find the quietest inaudible signal that still keeps powered speakers awake.

Many powered speakers and AV amplifiers switch to standby after a few minutes
without an input signal. A keep-alive tool has to send a pulse that is strong
enough for the speaker's signal detector, yet quiet enough that nobody hears it.
That threshold differs per model and cannot be guessed, so measure it here
before wiring any values into the application.

Run it with the project venv:

    .venv\\Scripts\\python.exe tools\\tune.py --list

Typical session:

  1. --list                       find the output your speakers hang on
  2. --check --device N           baseline: leave the speakers idle for ~10 min
                                  first, then count how many beeps you miss
  3. --tone --device N --freq 20 --amp 1.0
                                  one pulse. Lower --amp until you hear nothing
                                  (mind the subwoofer, not the satellites)
  4. --keepalive --device N --freq 20 --amp 1.0 --interval 180 --minutes 20
     then --check again           if you now hear every beep, the setting works
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import sounddevice as sd

# --list prints device names, and a Czech console is cp1250: "Sluchátka (RØDE
# NT-USB+)" cannot be encoded there and print() raises instead of printing.
# Unprintable characters become "?" rather than ending the run. The same is
# done in keep_alive.py, which this tool deliberately does not import.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, OSError, ValueError):
        pass        # not a real stream - only prettier console text is lost

# PortAudio exposes the same speakers through several host APIs. WASAPI is the
# native one on Windows; MME/DirectSound add latency and resampling we do not want.
PREFERRED_HOSTAPI = "Windows WASAPI"


def hostapi_name(index: int) -> str:
    return sd.query_hostapis(index)["name"]


def output_devices(show_all: bool = False):
    """Yield (index, device_info) for every usable output."""
    for index, device in enumerate(sd.query_devices()):
        if device["max_output_channels"] < 1:
            continue
        if not show_all and hostapi_name(device["hostapi"]) != PREFERRED_HOSTAPI:
            continue
        yield index, device


def cmd_list(args) -> int:
    default_output = sd.default.device[1]
    found = False
    for index, device in output_devices(args.all):
        found = True
        mark = " <- system default" if index == default_output else ""
        print(
            f"[{index:3d}] {device['name']}\n"
            f"       {hostapi_name(device['hostapi'])}, "
            f"{int(device['max_output_channels'])} ch, "
            f"{int(device['default_samplerate'])} Hz{mark}"
        )
    if not found:
        print(
            f"No output device found for host API {PREFERRED_HOSTAPI!r}. "
            "Retry with --all to see every host API.",
            file=sys.stderr,
        )
        return 1
    return 0


def resolve_device(spec: str | None) -> int:
    """Accept a device index or a case-insensitive part of its name."""
    if spec is None:
        default_output = sd.default.device[1]
        if default_output is None or default_output < 0:
            raise SystemExit("No system default output. Pass --device explicitly.")
        return int(default_output)

    if spec.strip().lstrip("-").isdigit():
        index = int(spec)
        device = sd.query_devices(index)
        if device["max_output_channels"] < 1:
            raise SystemExit(f"Device {index} ({device['name']}) has no output channels.")
        return index

    needle = spec.casefold()
    matches = [
        (index, device)
        for index, device in output_devices(show_all=True)
        if needle in device["name"].casefold()
    ]
    # Prefer WASAPI when the same speakers show up under several host APIs.
    wasapi = [m for m in matches if hostapi_name(m[1]["hostapi"]) == PREFERRED_HOSTAPI]
    if wasapi:
        matches = wasapi
    if not matches:
        raise SystemExit(f"No output device matches {spec!r}. Run --list.")
    if len(matches) > 1:
        listing = "\n".join(f"  [{i}] {d['name']}" for i, d in matches)
        raise SystemExit(f"{spec!r} matches several devices:\n{listing}\nUse the index.")
    return matches[0][0]


def make_pulse(freq: float, amp_percent: float, duration: float,
               fade: float, samplerate: int) -> np.ndarray:
    """One sine burst with raised-cosine edges.

    Without the fade the burst starts and ends with a step, and a step is
    broadband noise - a click you hear far better than the tone itself.
    """
    samples = int(round(duration * samplerate))
    if samples < 2:
        raise SystemExit(f"--dur {duration} is too short at {samplerate} Hz.")

    periods = duration * freq
    if periods < 2:
        needed = 2.0 / freq
        print(
            f"WARNING: {duration:.3f} s at {freq:g} Hz is only {periods:.2f} periods. "
            f"A speaker cannot reproduce less than a full wave - it sees a DC step, "
            f"not a tone. Use --dur {needed:.2f} or higher, or raise --freq.",
            file=sys.stderr,
        )

    t = np.arange(samples) / samplerate
    wave = np.sin(2.0 * np.pi * freq * t) * (amp_percent / 100.0)

    fade_samples = int(round(fade * samplerate))
    if fade_samples > samples // 2:
        fade_samples = samples // 2
        print(
            f"WARNING: fade shortened to {fade_samples / samplerate:.3f} s "
            f"so that two ramps fit inside the pulse.",
            file=sys.stderr,
        )
    if fade_samples > 0:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_samples) / fade_samples))
        wave[:fade_samples] *= ramp
        wave[-fade_samples:] *= ramp[::-1]

    return wave.astype(np.float32)


# Must stay the same as keep_alive.BUFFER_S, or this tool measures something
# the app never plays - test_logic.py compares the two. WASAPI's own default
# came out at 22 ms on the machine this was written for, and that crackled all
# the way through the tone; 60 ms and up was clean. See keep_alive.py for the
# full measurement.
BUFFER_S = 0.1


def play(mono: np.ndarray, samplerate: int, device: int, channels: int) -> None:
    data = np.column_stack([mono] * channels) if channels > 1 else mono
    try:
        sd.play(data, samplerate=samplerate, device=device, blocking=True,
                latency=BUFFER_S)
    except sd.PortAudioError as exc:
        raise SystemExit(f"Playback on device {device} failed: {exc}")


def device_output_setup(index: int) -> tuple[int, int, str]:
    device = sd.query_devices(index)
    samplerate = int(device["default_samplerate"])
    channels = min(2, int(device["max_output_channels"]))
    return samplerate, channels, device["name"]


def cmd_tone(args) -> int:
    index = resolve_device(args.device)
    samplerate, channels, name = device_output_setup(index)
    pulse = make_pulse(args.freq, args.amp, args.dur, args.fade, samplerate)
    peak_dbfs = 20 * np.log10(args.amp / 100.0) if args.amp > 0 else float("-inf")
    print(
        f"{name}\n"
        f"  {args.freq:g} Hz, {args.amp:g} % full scale ({peak_dbfs:.1f} dBFS), "
        f"{args.dur:g} s, fade {args.fade:g} s, {samplerate} Hz / {channels} ch"
    )
    for n in range(args.repeat):
        if args.repeat > 1:
            print(f"  pulse {n + 1}/{args.repeat}")
        play(pulse, samplerate, index, channels)
        if n + 1 < args.repeat:
            time.sleep(args.gap)
    print("Heard anything? Then lower --amp, or move --freq further down.")
    return 0


def cmd_keepalive(args) -> int:
    index = resolve_device(args.device)
    samplerate, channels, name = device_output_setup(index)
    pulse = make_pulse(args.freq, args.amp, args.dur, args.fade, samplerate)
    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    print(
        f"{name}\n"
        f"  {args.freq:g} Hz, {args.amp:g} %, {args.dur:g} s, every {args.interval:g} s"
        + (f", for {args.minutes:g} min" if args.minutes else ", until Ctrl+C")
    )
    sent = 0
    try:
        while True:
            play(pulse, samplerate, index, channels)
            sent += 1
            print(f"  {time.strftime('%H:%M:%S')}  pulse {sent}")
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
    print(f"{sent} pulses sent. Now run --check on the same device.")
    return 0


def cmd_check(args) -> int:
    """Beeps you can count - the only reliable way to tell the speakers slept.

    A sleeping speaker swallows the first fraction of a second while its relay
    clicks and the amplifier settles, so you simply hear fewer beeps than were
    played. That is a number, not an impression.
    """
    index = resolve_device(args.device)
    samplerate, channels, name = device_output_setup(index)
    beep = make_pulse(args.check_freq, args.check_amp, 0.15, 0.01, samplerate)
    print(
        f"{name}\n"
        f"  playing {args.beeps} beeps at {args.check_freq:g} Hz, "
        f"{args.check_amp:g} % - count how many you actually hear"
    )
    for n in range(args.beeps):
        play(beep, samplerate, index, channels)
        print(f"  beep {n + 1}/{args.beeps}")
        if n + 1 < args.beeps:
            time.sleep(args.check_gap)
    print(
        f"\nHeard all {args.beeps}? The speakers were awake.\n"
        "Missed the first one or two? They were asleep and had to wake up."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="list output devices")
    mode.add_argument("--tone", action="store_true", help="play one keep-alive pulse")
    mode.add_argument("--keepalive", action="store_true", help="pulse on an interval")
    mode.add_argument("--check", action="store_true", help="countable beeps: were they asleep?")

    parser.add_argument("--all", action="store_true",
                        help="with --list: show every host API, not just WASAPI")
    parser.add_argument("--device", help="output index or part of its name (default: system default)")

    parser.add_argument("--freq", type=float, default=20.0, help="pulse frequency in Hz (default 20)")
    parser.add_argument("--amp", type=float, default=1.0,
                        help="amplitude in %% of full scale (default 1.0 = -40 dBFS)")
    parser.add_argument("--dur", type=float, default=0.4, help="pulse length in seconds (default 0.4)")
    parser.add_argument("--fade", type=float, default=0.05,
                        help="fade in/out in seconds (default 0.05, prevents clicks)")

    parser.add_argument("--repeat", type=int, default=1, help="with --tone: number of pulses")
    parser.add_argument("--gap", type=float, default=1.0, help="with --tone --repeat: seconds between pulses")

    parser.add_argument("--interval", type=float, default=180.0,
                        help="with --keepalive: seconds between pulses (default 180)")
    parser.add_argument("--minutes", type=float, default=0.0,
                        help="with --keepalive: stop after N minutes (default: run until Ctrl+C)")

    parser.add_argument("--beeps", type=int, default=6, help="with --check: how many beeps (default 6)")
    parser.add_argument("--check-freq", type=float, default=1000.0,
                        help="with --check: beep frequency in Hz (default 1000)")
    parser.add_argument("--check-amp", type=float, default=10.0,
                        help="with --check: beep amplitude in %% of full scale (default 10)")
    parser.add_argument("--check-gap", type=float, default=0.35,
                        help="with --check: seconds between beeps (default 0.35)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        return cmd_list(args)
    if args.tone:
        return cmd_tone(args)
    if args.keepalive:
        return cmd_keepalive(args)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
