"""
Da Keep Speakers Alive - keeps powered speakers from falling asleep.

How it works:
  Powered speakers and AV amplifiers switch to standby after a few minutes
  without an input signal, and then swallow the first fraction of a second of
  everything that comes afterwards. The app therefore sends a short sine burst
  every 'interval_s' seconds: low enough and quiet enough that nobody hears it,
  loud enough that the speaker's signal detector notices it.

Why a short PULSE and not a permanent tone (what SoundKeeper and SpeakerAwake
do): this machine sleeps in Modern Standby (S0), where a permanently open
audio stream can keep the system out of its low power state. A 0.4 s burst
every three minutes is the smallest intervention that does the job.

Why a running process and not a scheduled task every three minutes: 480 starts
of the interpreter a day, and Task Scheduler is exactly the place where
"wake the computer to run this task" gets switched on by accident. A running
process has nothing to wake anything with - in hibernation it does not exist,
in S0 Windows freezes it.

It cannot be a Windows service: a service runs in session 0, where audio does
not physically play. A locked screen or a switched-off monitor does not end
the session, so "works while the screen is locked" is satisfied anyway.
"""

import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import numpy as np
import sounddevice as sd
from PIL import Image, ImageDraw
import pystray

import marks
import texts
from texts import t as tx
from texts import en as tx_en      # for the log, which stays English
from version import VERSION, PROJECT_URL

APP_NAME = "Da Keep Speakers Alive"

HERE = Path(__file__).resolve().parent

# Where the data belongs (settings, log):
#   - run from source    -> next to the script, so everything stays together
#   - installed copy     -> into the user profile, because the program folder
#     is not a place to write into
if getattr(sys, "frozen", False):
    DATA = Path(os.environ.get("APPDATA", HERE)) / APP_NAME
    DATA.mkdir(parents=True, exist_ok=True)
    PROGRAM = Path(sys.executable).resolve().parent
else:
    DATA = HERE
    PROGRAM = HERE

CFG_PATH = DATA / "config.json"
LOG_PATH = DATA / "keep_alive.log"

# Window icon. In the packaged build it sits next to the program, otherwise
# next to the sources.
_icon_file = ((Path(sys._MEIPASS) if getattr(sys, "frozen", False)
               else HERE / "icons") / "keep_alive.ico")
ICON_PATH = _icon_file if _icon_file.exists() else None

user32 = ctypes.windll.user32


# ---------------------------------------------------------------- settings

# The single source of truth for default settings. The shipped
# config.default.json is only a commented copy of these values - test_logic.py
# checks that the two never drift apart.
#
# The signal defaults come from the measurement written down in CLAUDE.md:
# 20 Hz at 1 % of full scale is inaudible on the Creative speakers and still
# counts as signal for them.
DEFAULTS = {
    "active": True,
    "use_default_device": True,   # follow whatever Windows plays through
    "devices": [],                # extra outputs, remembered by NAME
    "interval_s": 180,
    "freq_hz": 20,
    "amp_percent": 1.0,
    "duration_s": 0.4,
    # Not in the window on purpose: without a fade the burst starts and ends
    # with a step, and a step is broadband noise - a click you hear far better
    # than the tone itself. It is clamped to the pulse length in make_pulse().
    "fade_s": 0.05,
    "language": "cs",
    "log": True,
    "window_geometry": "",        # remembered window size and position
}


def read_json(path):
    """JSON out of a file, tolerating a byte order mark at the start.

    Notepad saves UTF-8 WITH a BOM, and so does PowerShell's
    `Set-Content -Encoding utf8`. json.loads() refuses those three bytes, so
    without "utf-8-sig" every setting the user edited by hand would fall back
    to the defaults - which is exactly what happened here on 19.08.2026.
    Writing stays plain "utf-8", so we never produce a BOM ourselves.
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_cfg():
    """Settings = defaults, overlaid with whatever the user has saved.

    Missing or damaged files must never stop the app: a fresh clone has no
    config.json at all, and a half-written file should not be fatal either.
    """
    cfg = dict(DEFAULTS)
    if not CFG_PATH.exists():
        # first run of an installed copy: start from the shipped template
        template = PROGRAM / "config.default.json"
        if template.exists():
            cfg_text = template.read_text(encoding="utf-8-sig")
            CFG_PATH.write_text(cfg_text, encoding="utf-8")
    if CFG_PATH.exists():
        try:
            saved = read_json(CFG_PATH)
            # keys starting with "_" are comments in config.default.json
            cfg.update({k: v for k, v in saved.items()
                        if not k.startswith("_")})
        except (OSError, ValueError) as error:
            # damaged settings must be visible, not silently ignored
            print(f"config.json unreadable ({error}) - using defaults")
    return cfg


def save_cfg(cfg):
    CFG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                        encoding="utf-8")


CFG = load_cfg()
texts.set_language(CFG.get("language", "cs"))

# Command line switches:
#   --show          open the settings window right at start
#   --pulse         send one pulse to the configured devices and quit
#   --quit-after N  quit on its own after N seconds (for the tests)
#   --no-dialog     never show a message box (for the tests)
SHOW_AT_START = "--show" in sys.argv
PULSE_ONLY = "--pulse" in sys.argv
NO_DIALOG = "--no-dialog" in sys.argv
QUIT_AFTER = 0.0
if "--quit-after" in sys.argv:
    QUIT_AFTER = float(sys.argv[sys.argv.index("--quit-after") + 1])


LOG_MAX = 2_000_000      # 2 MB, then a new file is started


def log(msg):
    line = f"{datetime.now():%d.%m.%Y %H:%M:%S}  {msg}"
    print(line)
    if not CFG.get("log", True):
        return
    try:
        # Rotation: once the size is exceeded the file moves aside as .1
        # (overwriting the previous .1) - so at most two files are kept.
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX:
            previous = LOG_PATH.with_suffix(".log.1")
            previous.unlink(missing_ok=True)
            LOG_PATH.rename(previous)
    except OSError:
        pass
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as error:
        print(f"  (could not write the log: {error})")


# ---------------------------------------------------------------- audio

# PortAudio offers the same speakers through several host APIs. WASAPI is the
# native one on Windows; MME and DirectSound add latency and resampling.
HOSTAPI = "Windows WASAPI"

# PortAudio reads the list of devices once, when it starts up. A device
# plugged in afterwards - or a change of the Windows default output - is
# invisible until it is restarted, hence refresh(). The lock keeps that from
# happening while a pulse is playing.
AUDIO_LOCK = threading.RLock()


def refresh_devices():
    """Re-read the device list from Windows. Returns True when it worked."""
    with AUDIO_LOCK:
        try:
            sd._terminate()
            sd._initialize()
            return True
        except Exception as error:      # PortAudio failing to restart
            log(f"Could not re-read the device list: {error}")
            return False


def _hostapi_index():
    for index, api in enumerate(sd.query_hostapis()):
        if api["name"] == HOSTAPI:
            return index
    return None


def outputs():
    """Every usable WASAPI output as a dict - what the window lists.

    Under the lock as well: the window asks for the list from the Tk thread
    while the engine may be in the middle of restarting PortAudio, and asking
    a half-restarted PortAudio is how a process dies without a message.
    """
    with AUDIO_LOCK:
        api = _hostapi_index()
        found = []
        for index, device in enumerate(sd.query_devices()):
            if device["max_output_channels"] < 1:
                continue
            if api is not None and device["hostapi"] != api:
                continue
            found.append({
                "index": index,
                "name": device["name"],
                "samplerate": int(device["default_samplerate"]),
                "channels": min(2, int(device["max_output_channels"])),
            })
        return found


def default_output():
    """Index of the output Windows currently plays through, or None.

    sd.default.device would answer for PortAudio's default host API, which is
    MME on Windows - a different numbering than the one the app works with.
    The default has to be taken from the WASAPI host API itself.
    """
    api = _hostapi_index()
    if api is None:
        return None
    index = sd.query_hostapis(api)["default_output_device"]
    return None if index is None or index < 0 else int(index)


def _key(name):
    """A device name reduced to what stays the same between reconnections.

    Windows numbers outputs in the name itself - "Speakers (4 - USB Advanced
    Audio Device)" becomes "(5 - ..." after being plugged into another port.
    The number sits either inside the brackets or right at the front
    ("3 - XG27ACS (AMD High Definition Audio Device)"); both are dropped, so
    the saved choice still matches.
    """
    without_number = re.sub(r"\(\s*\d+\s*-\s*", "(", name)
    without_number = re.sub(r"^\s*\d+\s*-\s*", "", without_number)
    return without_number.casefold().strip()


def find_output(name, devices=None):
    """The device saved under this name, or None when it is not connected."""
    devices = outputs() if devices is None else devices
    for device in devices:              # exact name first
        if device["name"] == name:
            return device
    wanted = _key(name)
    for device in devices:              # then ignoring the port number
        if _key(device["name"]) == wanted:
            return device
    return None


def targets(devices=None):
    """(list of devices to play to, list of names that are missing)."""
    devices = outputs() if devices is None else devices
    chosen, missing, seen = [], [], set()
    if CFG.get("use_default_device", True):
        index = default_output()
        for device in devices:
            if device["index"] == index:
                chosen.append(device)
                seen.add(_key(device["name"]))
    for name in CFG.get("devices", []):
        device = find_output(name, devices)
        if device is None:
            missing.append(name)
        elif _key(device["name"]) not in seen:
            chosen.append(device)
            seen.add(_key(device["name"]))
    return chosen, missing


def periods(freq, duration):
    return duration * float(freq)


def make_pulse(freq, amp_percent, duration, fade, samplerate):
    """One sine burst with raised-cosine edges, as float32 mono.

    Fewer than two periods is not a tone but a DC step for the speaker - the
    window warns about that; here the signal is generated as asked, because
    silently "fixing" the user's setting would hide the problem.
    """
    samples = max(2, int(round(duration * samplerate)))
    t = np.arange(samples) / samplerate
    wave = np.sin(2.0 * np.pi * float(freq) * t) * (float(amp_percent) / 100.0)

    fade_samples = min(int(round(fade * samplerate)), samples // 2)
    if fade_samples > 0:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_samples)
                                   / fade_samples))
        wave[:fade_samples] *= ramp
        wave[-fade_samples:] *= ramp[::-1]
    return wave.astype(np.float32)


def play(device, wave):
    """Play one pulse on one device. Raises on failure - the caller logs it."""
    channels = device["channels"]
    data = np.tile(wave.reshape(-1, 1), (1, channels))
    with AUDIO_LOCK:
        with sd.OutputStream(device=device["index"],
                             samplerate=device["samplerate"],
                             channels=channels, dtype="float32") as stream:
            stream.write(data)


# ---------------------------------------------------------------- engine

class Engine(threading.Thread):
    """Sends the pulse. Everything it knows is read from CFG when it is
    needed, so a change in the window takes effect at the next pulse and no
    second copy of a setting can go stale."""

    def __init__(self):
        super().__init__(daemon=True)
        self.wake = threading.Event()   # settings changed / pulse now / quit
        self.stop = threading.Event()
        self.last_at = 0.0              # monotonic, 0 = nothing sent yet
        self.last_wall = None           # datetime of the last pulse
        self.count = 0
        self.error = None               # text of the last failure, or None
        # Whether that failure was only partial - some devices got the pulse
        # and some did not. "The last pulse could not be played" is a lie in
        # that case, and the user has no way to tell it from a total failure.
        self.partly = False
        self.paused_until = 0.0         # monotonic
        self.pulse_now = False
        self.playing_from = 0.0         # monotonic, 0 = nothing is playing now
        self.playing_span = 0.0         # how long the burst being played takes

    # --- what the window and the tray ask about ------------------------

    def interval(self):
        return max(10, int(CFG.get("interval_s", 180)))

    def paused(self):
        return max(0.0, self.paused_until - time.monotonic())

    def due_in(self):
        """Seconds to the next pulse (None when nothing is scheduled)."""
        if not CFG.get("active", True):
            return None
        if self.paused():
            return None
        if not self.last_at:
            return 0
        return max(0.0, self.last_at + self.interval() - time.monotonic())

    def playing(self):
        """(seconds already played, whole length) of the burst going out right
        now, or None when nothing is playing.

        Both numbers are worked out from the clock at the moment they are
        asked for, so the bar in the window cannot show a value that has gone
        stale - and nobody has to remember to reset anything.
        """
        started, span = self.playing_from, self.playing_span
        if not started or span <= 0:
            return None
        return min(span, max(0.0, time.monotonic() - started)), span

    def state(self):
        if not CFG.get("active", True):
            return "off"
        if self.paused():
            return "paused"
        if self.error:
            return "partial" if self.partly else "error"
        return "ok"

    # --- the work itself ------------------------------------------------

    def send(self, reason=""):
        """One pulse to every configured device. Returns an error text or None.

        The device list is re-read first: the user can plug the speakers into
        another port or switch the Windows default output while we run, and
        PortAudio would otherwise keep handing out its start-up snapshot.
        """
        refresh_devices()
        chosen, missing = targets()
        # Kept as (key, arguments) rather than as finished sentences: the same
        # problem has to reach the window in the user's language and the log in
        # English, and rendering it twice from one list is the only way the two
        # cannot drift apart.
        problems = [("err_device_gone", {"name": name}) for name in missing]
        # "Nothing is selected" only when nothing really is. A device that is
        # merely unplugged already says so in err_device_gone, and printing
        # both at once told the user two contradictory things - the first of
        # them untrue.
        if not chosen and not missing:
            problems.insert(0, ("err_no_device", {}))
        played = []
        # How long the whole burst takes. The devices are played one after
        # another, so it is the sum - the window draws a bar for exactly this
        # long, and the pulse is inaudible on purpose, so that bar is the only
        # sign the user gets that anything happened at all.
        duration = float(CFG.get("duration_s", 0.4))
        self.playing_span = duration * len(chosen)
        self.playing_from = time.monotonic()
        try:
            for device in chosen:
                wave = make_pulse(CFG.get("freq_hz", 20),
                                  CFG.get("amp_percent", 1.0),
                                  duration,
                                  CFG.get("fade_s", 0.05),
                                  device["samplerate"])
                try:
                    play(device, wave)
                    played.append(device["name"])
                except Exception as error:      # PortAudioError and friends
                    problems.append(("err_play", {"name": device["name"],
                                                  "error": error}))
            self.last_at = time.monotonic()
            self.last_wall = datetime.now()
            self.count += 1
            self.error = ("\n".join(tx(key, **kw) for key, kw in problems)
                          if problems else None)
            self.partly = bool(played) and bool(problems)
            if problems:
                in_english = "; ".join(tx_en(key, **kw) for key, kw in problems)
                log(f"Pulse{reason}: {in_english}")
            else:
                log(f"Pulse{reason} -> {', '.join(played)} "
                    f"({CFG.get('freq_hz')} Hz, {CFG.get('amp_percent')} %, "
                    f"{duration} s)")
        finally:
            # Cleared only here, with the record of the pulse already complete:
            # the bar asks about ENGINE.error the moment it stops moving, and
            # would otherwise show the previous pulse's verdict for a frame.
            self.playing_from = 0.0
        return self.error

    def run(self):
        while not self.stop.is_set():
            due = self.due_in()
            if self.pulse_now:
                self.pulse_now = False
                self.send(" (manual)")
            elif due is None:
                pass                        # switched off or paused
            elif due <= 0:
                # Being very late means the process was frozen - the machine
                # was asleep. The speakers slept through it too, so the pulse
                # right now is exactly what is needed; it is only worth a note
                # in the log.
                late = (time.monotonic() - self.last_at - self.interval()
                        if self.last_at else 0)
                self.send(" (after a break)" if late > 60 else "")
            # Waking up at least once a second keeps the countdown in the
            # window honest and picks up a changed interval straight away.
            self.wake.wait(timeout=1.0)
            self.wake.clear()

    def request_pulse(self):
        self.pulse_now = True
        self.wake.set()

    def pause(self, minutes):
        self.paused_until = time.monotonic() + minutes * 60 if minutes else 0.0
        log(f"Paused for {minutes} min." if minutes else "Pause cancelled.")
        self.wake.set()


ENGINE = Engine()


# ------------------------------------------------------- start at logon

TASK_NAME = APP_NAME
_autostart = None        # remembered state, so schtasks is not run over and over
_autostart_at = 0.0


def _quiet(command):
    """Run a command without a console window flashing up."""
    try:
        v = subprocess.run(command, shell=True, capture_output=True, text=True,
                           creationflags=0x08000000)   # CREATE_NO_WINDOW
        return v.returncode == 0
    except Exception:
        return False


def _launch_parts():
    """Return (program, arguments) used to start the app.

    The packaged build starts directly; from source it goes through
    pythonw.exe so that no console window flashes up.
    """
    if getattr(sys, "frozen", False):
        return str(sys.executable), ""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return str(pyw if pyw.exists() else sys.executable), str(HERE / "keep_alive.py")


def _create_task():
    """Register the logon task in Task Scheduler from XML.

    Why XML and not a plain schtasks command: that one only covers the basics.
    Here we also need a restart after a crash and, most importantly, the
    REMOVAL of the limit after which Windows kills the task on its own
    (3 days by default) - that can only be set this way.

    WakeToRun stays false and there is no time trigger at all: this app must
    never be a reason for the computer to wake up.
    """
    program, arguments = _launch_parts()
    user = (os.environ.get("USERDOMAIN", "") + "\\"
            + os.environ.get("USERNAME", "")).strip("\\")
    e = xml_escape
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Keeps powered speakers from falling asleep.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{e(user)}</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{e(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{e(program)}</Command>
      <Arguments>{e('"' + arguments + '"') if arguments else ''}</Arguments>
      <WorkingDirectory>{e(str(HERE))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""
    path = DATA / "_task.xml"
    try:
        # schtasks reads the XML as UTF-16, anything else is rejected
        path.write_text(xml, encoding="utf-16")
        return _quiet(f'schtasks /Create /F /TN "{TASK_NAME}" /XML "{path}"')
    except OSError as error:
        log(f"Could not prepare the task: {error}")
        return False
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def autostart_enabled(refresh=False):
    """Does the app start at logon?"""
    global _autostart, _autostart_at
    if not refresh and _autostart is not None \
            and time.monotonic() - _autostart_at < 30:
        return _autostart
    _autostart = _quiet(f'schtasks /Query /TN "{TASK_NAME}"')
    _autostart_at = time.monotonic()
    return _autostart


def autostart_set(enable):
    """Turn start-at-logon on or off.

    Only the scheduled task is used - it can delay the start and restart the
    app after a crash. There is deliberately NO fallback into the Startup
    folder: when the task cannot be created the user has to be told, not
    quietly given a different mechanism they did not ask for.
    """
    global _autostart
    if enable:
        if _create_task():
            log("Start at logon enabled (scheduled task).")
        else:
            log("Start at logon could NOT be enabled.")
            if not NO_DIALOG:
                user32.MessageBoxW(0, tx("err_autostart"), APP_NAME, 0x30)
    else:
        _quiet(f'schtasks /Delete /F /TN "{TASK_NAME}"')
        log("Start at logon disabled.")
    _autostart = None
    return autostart_enabled(refresh=True)


# ---------------------------------------------------------------- Windows

_mutex = None
ERROR_ALREADY_EXISTS = 183


def dark_titlebar(window):
    """Ask Windows to draw the title bar dark, like the rest of the window.

    Without it a white bar sits on top of a dark window and the whole thing
    looks unfinished. Attribute 20 is DWMWA_USE_IMMERSIVE_DARK_MODE on Windows
    10 2004 and newer, 19 on the builds before it - both are tried, and a
    failure is harmless (the bar just stays light).
    """
    try:
        window.update_idletasks()
        hwnd = int(window.frame(), 16)
        value = ctypes.c_int(1)
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_int(attribute),
                ctypes.byref(value), ctypes.sizeof(value))
    except Exception as error:
        log(f"Could not set the dark title bar: {error}")


def already_running():
    """True when another instance is already running.

    A named mutex - the operating system holds it for the lifetime of the
    process, so no stale lock file is left behind after a crash. The name has
    no 'Global\\' prefix, so it applies within the logged-in user.
    """
    global _mutex
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL,
                                 wintypes.LPCWSTR]
    _mutex = k32.CreateMutexW(None, False, "DaKeepSpeakersAlive_single_instance")
    return k32.GetLastError() == ERROR_ALREADY_EXISTS


# ---------------------------------------------------------------- labels

def minutes_label(minutes, key_one, key_few, key_many):
    """Czech needs three forms (1 minuta / 3 minuty / 5 minut), English one.

    The choice lives here and not in texts.py, because a translation table
    cannot decide grammar.
    """
    if texts.language() != "cs":
        # English still has singular and plural - "1 minutes" is a bug users
        # notice immediately
        return tx(key_one if minutes == 1 else key_many, m=minutes, h=minutes)
    if minutes == 1:
        return tx(key_one, m=minutes, h=minutes)
    if 2 <= minutes <= 4:
        return tx(key_few, m=minutes, h=minutes)
    return tx(key_many, m=minutes, h=minutes)


def interval_label(seconds):
    if seconds < 60:
        return tx("opt_seconds", s=seconds)
    return minutes_label(seconds // 60, "opt_minute", "opt_minutes",
                         "opt_minutes_5")


def pause_label(minutes):
    if minutes < 60:
        return tx("opt_pause_min", m=minutes)
    return minutes_label(minutes // 60, "opt_pause_hour", "opt_pause_hours",
                         "opt_pause_hours_5")


def number(value):
    """0.4 -> "0,4" in Czech; whole numbers without the decimal point."""
    text = f"{value:g}"
    return text.replace(".", ",") if texts.language() == "cs" else text


def seconds_text(value):
    """Like number(), but always with one decimal place.

    A running count must not jump between "1" and "1,2" as it passes a whole
    second - the width of the text would change under the user's eyes.
    """
    text = f"{value:.1f}"
    return text.replace(".", ",") if texts.language() == "cs" else text


# ---------------------------------------------------------------- window

# The colours of the states, in one place: the status card and the pulse bar
# both show the same thing and must not drift apart.
#
# "partial" is amber rather than red on purpose - some speakers did get the
# pulse, so the app is doing its job for them; red would send the user hunting
# for a fault that is not there.
STATE_COLOUR = {"ok": "#7fd39b", "off": "#c3ccd8", "paused": "#f0c479",
                "partial": "#ffb066", "error": "#ff9f9f"}


class LanguageFlags(tk.Frame):
    """The language switch: one small flag per language, top right of the
    window.

    Drawn instead of loaded from image files - a bitmap would mean another
    file per language to ship, and at this size a scaled PNG goes soft.

    The current language is marked by a bar UNDER its flag, not by dimming
    the other one: a Tk canvas has no transparency, so "dimmed" would have to
    be a second set of colours for every flag, kept in step by hand.
    """

    # 3:2, as most flags are. Not smaller: at 30x20 the Union Jack turns into
    # a red smudge, and the project already had to redraw Tk's own tiny
    # checkboxes for the same reason.
    W, H = 36, 24
    UNDERLINE = 3               # the "this one is active" bar
    GAP = 10

    def __init__(self, parent, action, accent):
        super().__init__(parent, bg=parent["bg"])
        for code, name in texts.LANGUAGES:
            canvas = tk.Canvas(self, width=self.W,
                               height=self.H + 2 + self.UNDERLINE,
                               bg=parent["bg"], highlightthickness=0,
                               cursor="hand2")
            canvas.pack(side="left", padx=(self.GAP, 0))
            # the loop variable has to be captured, or every flag would
            # switch to the language of the last one built
            canvas.bind("<Button-1>", (lambda c: lambda e: action(c))(code))
            self._draw(canvas, code, code == texts.language(), accent)

    def _draw(self, canvas, code, active, accent):
        w, h = self.W, self.H
        if code == "cs":
            canvas.create_rectangle(0, 0, w, h / 2, fill="#ffffff", width=0)
            canvas.create_rectangle(0, h / 2, w, h, fill="#d7141a", width=0)
            canvas.create_polygon(0, 0, w * 0.55, h / 2, 0, h,
                                  fill="#11457e", width=0)
        else:
            canvas.create_rectangle(0, 0, w, h, fill="#012169", width=0)
            # The diagonals are POLYGONS, not thick lines: a wide line ends
            # square across its own direction, so at the corners it sticks
            # out past the flag - and a Tk canvas cannot clip it back.
            for t, colour in ((10, "#ffffff"), (3.5, "#c8102e")):
                canvas.create_polygon(0, 0, t, 0, w, h - t, w, h, w - t, h,
                                      0, t, fill=colour, width=0)
                canvas.create_polygon(w, 0, w - t, 0, 0, h - t, 0, h, t, h,
                                      w, t, fill=colour, width=0)
            canvas.create_rectangle(w / 2 - 4.5, 0, w / 2 + 4.5, h,
                                    fill="#ffffff", width=0)
            canvas.create_rectangle(0, h / 2 - 4.5, w, h / 2 + 4.5,
                                    fill="#ffffff", width=0)
            canvas.create_rectangle(w / 2 - 2.5, 0, w / 2 + 2.5, h,
                                    fill="#c8102e", width=0)
            canvas.create_rectangle(0, h / 2 - 2.5, w, h / 2 + 2.5,
                                    fill="#c8102e", width=0)
        # a thin edge, or the white half of a flag bleeds into the dark window
        canvas.create_rectangle(0, 0, w - 1, h - 1, outline="#55606f")
        if active:
            canvas.create_rectangle(0, h + 2, w, h + 2 + self.UNDERLINE,
                                    fill=accent, width=0)


class Scroller(tk.Canvas):
    """A vertical scrollbar drawn by hand.

    The Tk scrollbar on Windows ignores colour settings (the system draws it),
    so a light grey bar would stay in the dark window where it does not belong.
    """
    WIDTH = 11
    MIN_THUMB = 34              # so that a small thumb can still be grabbed

    def __init__(self, parent, view):
        super().__init__(parent, width=self.WIDTH, bg="#151920",
                         highlightthickness=0, cursor="hand2")
        self.view = view                # yview of the area being scrolled
        self.first, self.last = 0.0, 1.0
        self.grab = None                # cursor offset from the top edge
        self.hovered = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "grab", None))
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def set_view(self, first, last):
        self.first, self.last = float(first), float(last)
        self._draw()

    def _hover(self, hovering):
        self.hovered = hovering
        self._draw()

    def _thumb(self):
        """Returns (from, to) in pixels."""
        v = self.winfo_height()
        start, end = self.first * v, self.last * v
        if end - start < self.MIN_THUMB:    # a short thumb cannot be hit
            mid = (start + end) / 2
            start = max(0, min(v - self.MIN_THUMB, mid - self.MIN_THUMB / 2))
            end = start + self.MIN_THUMB
        return start, end

    def _draw(self):
        self.delete("all")
        start, end = self._thumb()
        s = self.WIDTH
        self.create_rectangle(2, start + 1, s - 2, end - 1, width=0,
                              fill="#4d5866" if self.hovered else "#3a4350")

    def _press(self, event):
        start, end = self._thumb()
        if start <= event.y <= end:
            self.grab = event.y - start
        else:                            # click beside the thumb = page jump
            self.view("scroll", 1 if event.y > end else -1, "pages")

    def _drag(self, event):
        if self.grab is None:
            return
        v = max(1, self.winfo_height())
        self.view("moveto", max(0.0, min(1.0, (event.y - self.grab) / v)))


class PulseBar(tk.Frame):
    """A bar that fills over the length of the pulse, with the time under it.

    Why it exists: the pulse is inaudible on purpose, so pressing "Try a pulse"
    would otherwise do nothing a user can see, and a working app would look
    exactly like a broken one.

    It draws what the window's animation loop hands it and decides nothing on
    its own; the last values are kept only so the bar can repaint itself when
    the window is resized.
    """

    HEIGHT = 10

    def __init__(self, parent, caption_colour):
        super().__init__(parent, bg=parent["bg"])
        self.track = "#232b36"          # same shade as a button
        self.canvas = tk.Canvas(self, height=self.HEIGHT, bg=parent["bg"],
                                highlightthickness=0)
        self.canvas.pack(fill="x")
        self.caption = tk.Label(self, text="", bg=parent["bg"],
                                fg=caption_colour, font=("Segoe UI", 9),
                                height=1, anchor="w", justify="left")
        # A fixed height of one line: the caption comes and goes, and the card
        # must not change size under the user's hand while it does.
        self.caption.pack(fill="x", pady=(3, 0))
        self.shown = (0.0, "", STATE_COLOUR["ok"])
        self.canvas.bind("<Configure>", lambda e: self._draw())

    def show(self, done, span, error=None, partly=False):
        """`done` and `span` in seconds; span of 0 means nothing is playing.

        `partly` marks a pulse that reached some devices and not others - the
        bar has to say the same thing as the status card, or the window
        contradicts itself in two places at once.
        """
        fraction = 0.0 if span <= 0 else min(1.0, max(0.0, done / span))
        state = ("partial" if partly else "error") if error else "ok"
        colour = STATE_COLOUR[state]
        if span <= 0:
            caption = ""
        elif error:
            caption = tx("bar_partial" if partly else "bar_failed")
        elif fraction >= 1.0:
            caption = tx("bar_done", total=seconds_text(span))
        else:
            caption = tx("bar_playing", done=seconds_text(done),
                         total=seconds_text(span))
        if (fraction, caption, colour) == self.shown:
            return                      # nothing changed, nothing to repaint
        self.shown = (fraction, caption, colour)
        self.caption.configure(text=caption)
        self._draw()

    def _draw(self):
        fraction, _, colour = self.shown
        width = self.canvas.winfo_width()
        self.canvas.delete("all")
        self._pill(0, width, self.track)
        filled = width * fraction
        if filled >= 1:
            self._pill(0, filled, colour)

    def _pill(self, start, end, colour):
        """A rectangle with round ends - Tk cannot draw one in a single call."""
        c, h = self.canvas, self.HEIGHT
        r = min(h / 2, (end - start) / 2)
        if r <= 0:
            return
        c.create_oval(start, 0, start + 2 * r, h, fill=colour, width=0)
        c.create_oval(end - 2 * r, 0, end, h, fill=colour, width=0)
        if end - start > 2 * r:
            c.create_rectangle(start + r, 0, end - r, h, fill=colour, width=0)


class Settings:
    """The settings window. The app has no main window - this one is created
    on demand from the tray icon and destroyed when it is closed."""

    CARD_WIDTH = 620        # width of one column; wider reads badly
    BG = "#1b1f26"          # window background
    CARD = "#151920"        # card background
    FG = "#e6ebf2"          # normal text
    DIM = "#a9b4c2"         # secondary text - deliberately not darker grey
    LABEL = "#9aa4b2"       # label above a drop-down

    INTERVALS = [30, 60, 120, 180, 300, 600, 900]
    # The lists reach far enough that a nonsensical combination is REACHABLE
    # (5 Hz in a 0.1 s pulse is a fifth of a wave) - otherwise the warning
    # below the controls could never appear and would be guarding nothing.
    FREQS = [5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100]
    AMPS = [0.1, 0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
    DURATIONS = [0.1, 0.2, 0.3, 0.4, 0.6, 1.0, 2.0]
    PAUSES = [15, 30, 60, 120, 240, 480]

    def __init__(self, root, tray=None):
        self.root = root
        self.tray = tray
        self.win = None
        self.ticker = None
        self.anim = None
        self.bars = []
        self.bar_full_until = 0.0
        self.bar_wait_until = 0.0

    # --- open / close ---------------------------------------------------

    def toggle(self):
        if self.win is not None and self.win.winfo_exists():
            self.close()
        else:
            self.open()

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return
        self._create()

    def close(self):
        if self.win is None:
            return
        self._remember_window()
        for handle in (self.ticker, self.anim):
            if handle is None:
                continue
            try:
                self.win.after_cancel(handle)
            except tk.TclError:
                pass        # window already gone - the callback went with it
        self.ticker = self.anim = None
        self.win.destroy()
        self.win = None

    def _remember_window(self):
        """Size and position are read from the window itself, never kept in a
        second variable that could go stale."""
        try:
            geometry = self.win.geometry()
            if geometry != CFG.get("window_geometry"):
                CFG["window_geometry"] = geometry
                save_cfg(CFG)
        except tk.TclError:
            pass        # window already gone - nothing worth remembering

    def _create(self):
        w = tk.Toplevel(self.root)
        self.win = w
        w.title(tx("window_title", app=APP_NAME))
        w.configure(bg=self.BG)
        w.geometry(CFG.get("window_geometry") or "700x760")
        if ICON_PATH:
            try:
                w.iconbitmap(default=str(ICON_PATH))
            except tk.TclError:
                pass        # a damaged icon must not stop the window
        dark_titlebar(w)
        # The app has no main window, so Windows will not hand it focus on its
        # own - it has to ask.
        w.deiconify()
        w.lift()
        w.attributes("-topmost", True)
        w.after(300, lambda: w.attributes("-topmost", False))
        w.focus_force()
        w.protocol("WM_DELETE_WINDOW", self.close)

        # The language switch sits OUTSIDE the scrolled area, so it stays in
        # the corner instead of sliding away with the content. Packed before
        # the canvas and the scrollbar, which then share what is left.
        header = tk.Frame(w, bg=self.BG)
        header.pack(side="top", fill="x")
        LanguageFlags(header, self._change_language, self.FG).pack(
            side="right", padx=(0, 20), pady=(10, 0))

        # The content lives in a scrollable area: on a short screen the window
        # would otherwise cut off the bottom with no way to reach it.
        self.canvas = tk.Canvas(w, bg=self.BG, highlightthickness=0)
        self.scroller = Scroller(w, self.canvas.yview)
        self.scroller_shown = False
        self.canvas.configure(yscrollcommand=self._scroller_state)
        self.canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(self.canvas, bg=self.BG)
        self.inner_window = self.canvas.create_window((0, 0), window=inner,
                                                      anchor="nw")
        self.grid_frame = tk.Frame(inner, bg=self.BG)
        self.grid_frame.pack(anchor="n", pady=(14, 10))

        def measured(_=None):
            content = self.canvas.bbox("all")
            if not content:
                return
            # The scrolled region must be at least as tall as the area itself.
            # When it is smaller, Tk CENTRES it while scrolling - the content
            # then jumps to the middle of the window on a wheel turn.
            height = max(content[3], self.canvas.winfo_height())
            self.canvas.configure(scrollregion=(0, 0, content[2], height))
            self.canvas.itemconfigure(self.inner_window,
                                      width=self.canvas.winfo_width())

        inner.bind("<Configure>", measured)
        self.canvas.bind("<Configure>", lambda e: (measured(), self._relayout()))
        # Bound to the WINDOW, not with bind_all: a bind_all binding outlives
        # the window it was made for, so opening the settings a second time
        # would scroll two lines per notch, a third time three.
        w.bind("<MouseWheel>", self._wheel)

        self.cards = []
        self.bars = []
        self.anim = None
        self.bar_full_until = 0.0   # a finished bar stays visible this long
        self.bar_wait_until = 0.0   # a pulse was asked for and has yet to start
        self.columns = 0
        self._build()
        self._relayout()
        self._set_minimum()
        self._tick()

    # --- layout helpers --------------------------------------------------

    def _card(self, title, description):
        """One settings section - heading, short explanation, content.

        The card is not packed - _relayout places it according to the window
        width, so every card in a column comes out the same width.
        """
        outer = tk.Frame(self.grid_frame, bg=self.BG)
        self.cards.append(outer)
        tk.Label(outer, text=title, bg=self.BG, fg=self.FG,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 1))
        if description:
            tk.Label(outer, text=description, bg=self.BG, fg=self.DIM,
                     justify="left", wraplength=self.CARD_WIDTH - 20,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 5))
        inner = tk.Frame(outer, bg=self.CARD, padx=16, pady=12)
        inner.pack(fill="both", expand=True)
        return inner

    def _relayout(self, event=None):
        """One or two columns, depending on how wide the window is."""
        width = self.canvas.winfo_width()
        wanted = 2 if width >= 2 * self.CARD_WIDTH + 100 else 1
        if wanted == self.columns:
            return
        self.columns = wanted

        # All columns equally wide and fixed - otherwise every card sets its
        # width by its own content and the blocks come out uneven.
        for i in range(2):
            self.grid_frame.grid_columnconfigure(
                i, minsize=(self.CARD_WIDTH + 10) if i < wanted else 0,
                weight=1 if i < wanted else 0,
                uniform="cards" if i < wanted else "")

        per_column = -(-len(self.cards) // wanted)     # round up
        for index, card in enumerate(self.cards):
            column = index // per_column
            row = index % per_column
            # the padding has to be the same on BOTH columns, otherwise one
            # column ends up narrower by that gap
            gap = 10 if wanted == 2 else 0
            card.grid(row=row, column=column, sticky="new",
                      padx=(0, gap) if column == 0 else (gap, 0),
                      pady=(0, 14))
        self.links_frame.grid(row=per_column, column=0, columnspan=wanted,
                              sticky="ew", pady=(2, 22))
        self._set_minimum()

    def _set_minimum(self):
        """The CONTENT decides the smallest window size, not a guess.

        Width comes from one column; the height is capped by the screen,
        because the content scrolls anyway.
        """
        if self.win is None or not self.win.winfo_exists():
            return
        self.win.update_idletasks()
        width = min(self.CARD_WIDTH + 70, self.win.winfo_screenwidth() - 80)
        height = min(520, self.win.winfo_screenheight() - 160)
        self.win.minsize(width, height)

    def _scroller_state(self, first, last):
        """Show the scrollbar only when the content does not fit.

        We keep our own record of whether it is shown - winfo_ismapped() only
        tells the truth after a redraw, so with two changes in quick
        succession it answers according to the old state.
        """
        self.scroller.set_view(first, last)
        fits = float(first) <= 0.0 and float(last) >= 1.0
        if fits and self.scroller_shown:
            self.scroller.pack_forget()
            self.scroller_shown = False
        elif not fits and not self.scroller_shown:
            self.scroller.pack(side="right", fill="y")
            self.scroller_shown = True

    def _wheel(self, event):
        if self.win is None or not self.win.winfo_exists():
            return
        if not self.scroller_shown:
            return
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # --- controls --------------------------------------------------------

    def _link(self, parent, text, action):
        """Clickable text - not a button. Underlined only on hover."""
        t = tk.Label(parent, text=text, bg=parent["bg"], fg="#7cc0ff",
                     font=("Segoe UI", 10), cursor="hand2")
        t.bind("<Button-1>", lambda e=None: action())
        t.bind("<Enter>", lambda e=None: t.configure(
            font=("Segoe UI", 10, "underline")))
        t.bind("<Leave>", lambda e=None: t.configure(font=("Segoe UI", 10)))
        return t

    def _button(self, parent, text, action):
        t = tk.Label(parent, text=f"  {text}  ", bg="#232b36", fg=self.FG,
                     padx=12, pady=7, font=("Segoe UI", 10), cursor="hand2")
        t.bind("<Button-1>", lambda e=None: action())
        t.bind("<Enter>", lambda e=None: t.configure(bg="#2f3743"))
        t.bind("<Leave>", lambda e=None: t.configure(bg="#232b36"))
        return t

    def _pulse_bar(self, parent):
        """The progress bar under a button that sends a pulse.

        Both such buttons get one, and both are fed from the engine by the same
        animation loop - so they cannot end up showing different things.
        """
        bar = PulseBar(parent, self.LABEL)
        bar.pack(fill="x", pady=(10, 0))
        self.bars.append(bar)
        return bar

    # The drawing lives in marks.py so that everything that draws a checkbox
    # draws the same one.
    def _option(self, parent, text, on, action, round_mark=False):
        """A row with a mark and a label - the whole row is clickable."""
        row = tk.Frame(parent, bg=parent["bg"], cursor="hand2")
        row.pack(anchor="w", pady=2, fill="x")
        c = tk.Canvas(row, width=marks.SIZE, height=marks.SIZE,
                      bg=parent["bg"], highlightthickness=0, cursor="hand2")
        c.pack(side="left", padx=(0, 9))
        p = tk.Label(row, text=text, bg=parent["bg"], fg="#d7dde5",
                     font=("Segoe UI", 10), cursor="hand2", justify="left",
                     wraplength=self.CARD_WIDTH - 70)
        p.pack(side="left")
        row.on, row.hovered = on, False

        def redraw():
            marks.draw(c, row.on, round_mark, row.hovered)

        def hover(hovering):
            row.hovered = hovering
            redraw()

        # the handlers tolerate being called without an event (e=None): while
        # a row is being destroyed an event can still reach a widget that is
        # going away
        for widget in (row, c, p):
            widget.bind("<Button-1>", lambda e=None: action())
            widget.bind("<Enter>", lambda e=None: hover(True))
            widget.bind("<Leave>", lambda e=None: hover(False))
        row.redraw = redraw
        redraw()
        return row

    def _switch(self, parent, text, key, read=None, write=None):
        """A checkbox bound either to a settings key, or to a pair of
        functions (start at logon, which lives in Task Scheduler)."""
        state = {"on": read() if read else bool(CFG.get(key, False))}

        def changed():
            state["on"] = not state["on"]
            if write:
                state["on"] = bool(write(state["on"]))
            else:
                CFG[key] = state["on"]
                save_cfg(CFG)
                log(f"Setting '{key}' = {CFG[key]}")
                ENGINE.wake.set()
            row.on = state["on"]
            row.redraw()
            self._refresh_status()
            if self.tray:
                self.tray.refresh()

        row = self._option(parent, text, state["on"], changed)
        row.key = key
        return row

    def _select(self, parent, label, pairs, current, action):
        """A drop-down list. Every setting in the window is one of these, so
        the controls all look and behave the same."""
        if label:
            tk.Label(parent, text=label, bg=parent["bg"], fg=self.LABEL,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
        labels = [text for text, _ in pairs]
        selected = next((text for text, value in pairs if value == current),
                        labels[0])
        var = tk.StringVar(value=selected)

        def changed(*_):
            for text, value in pairs:
                if text == var.get():
                    action(value)
                    break

        m = tk.OptionMenu(parent, var, *labels, command=changed)
        # indicatoron=0 hides the default Tk rectangle, which refuses to be
        # styled; an arrow is placed on the right instead
        m.configure(bg="#232b36", fg=self.FG, activebackground="#2f3743",
                    activeforeground="#fff", highlightthickness=0,
                    borderwidth=0, font=("Segoe UI", 10), anchor="w",
                    pady=6, padx=10, indicatoron=0)
        m["menu"].configure(bg="#232b36", fg=self.FG, borderwidth=0,
                            activebackground="#2f3743", activeforeground="#fff",
                            font=("Segoe UI", 10))
        m.pack(anchor="w", fill="x", pady=(1, 4))
        arrow = tk.Label(m, text="▾", bg="#232b36", fg="#c3ccd8",
                         font=("Segoe UI", 14))
        arrow.place(relx=1.0, rely=0.5, anchor="e", x=-12)
        # clicking the arrow opens the menu directly - more reliable than
        # sending a synthetic event to the menubutton
        arrow.bind("<Button-1>", lambda e: m["menu"].post(
            m.winfo_rootx(), m.winfo_rooty() + m.winfo_height()))
        return var

    # --- the cards -------------------------------------------------------

    def _build(self):
        # --- 1. status -------------------------------------------------
        card = self._card(tx("card_status"), None)
        self.status_line = tk.Label(card, text="", bg=self.CARD, fg=self.FG,
                                    font=("Segoe UI", 11, "bold"),
                                    justify="left",
                                    wraplength=self.CARD_WIDTH - 40)
        self.status_line.pack(anchor="w")
        # The reason sits right under the headline, in the headline's colour
        # and not in the dim grey of the rest: buried among "last pulse",
        # "next pulse" and "pulses sent" it went unread, which is the whole
        # point of a message that explains the red line above it.
        # Packed and unpacked as it comes and goes, so there is no empty gap
        # in the card while nothing is wrong.
        self.status_problem = tk.Label(card, text="", bg=self.CARD,
                                       fg=STATE_COLOUR["error"],
                                       font=("Segoe UI", 9), justify="left",
                                       wraplength=self.CARD_WIDTH - 40)
        self.status_detail = tk.Label(card, text="", bg=self.CARD, fg=self.DIM,
                                      font=("Segoe UI", 9), justify="left",
                                      wraplength=self.CARD_WIDTH - 40)
        self.status_detail.pack(anchor="w", pady=(4, 8))
        self._button(card, tx("btn_pulse_now"),
                     self._pulse_now).pack(anchor="w")
        self._pulse_bar(card)

        # --- 2. devices ------------------------------------------------
        card = self._card(tx("card_devices"), tx("card_devices_desc"))
        self._switch(card, tx("sw_use_default"), "use_default_device")
        self.devices_frame = tk.Frame(card, bg=self.CARD)
        self.devices_frame.pack(fill="x", pady=(2, 0))
        self._link(card, tx("link_rescan"),
                   self._rescan).pack(anchor="w", pady=(8, 0))
        self._fill_devices()

        # --- 3. interval -----------------------------------------------
        card = self._card(tx("card_interval"), tx("card_interval_desc"))
        self._select(card, tx("lbl_interval"),
                     [(interval_label(s), s) for s in self.INTERVALS],
                     int(CFG.get("interval_s", 180)),
                     lambda v: self._set("interval_s", v))

        # --- 4. signal -------------------------------------------------
        card = self._card(tx("card_signal"), tx("card_signal_desc"))
        self._select(card, tx("lbl_freq"),
                     [(tx("opt_hz", v=number(v)), v) for v in self.FREQS],
                     CFG.get("freq_hz", 20),
                     lambda v: self._set("freq_hz", v, warn=True))
        self._select(card, tx("lbl_amp"),
                     [(tx("opt_percent", v=number(v)), v) for v in self.AMPS],
                     CFG.get("amp_percent", 1.0),
                     lambda v: self._set("amp_percent", v))
        self._select(card, tx("lbl_duration"),
                     [(tx("opt_sec", v=number(v)), v) for v in self.DURATIONS],
                     CFG.get("duration_s", 0.4),
                     lambda v: self._set("duration_s", v, warn=True))
        self.warn_label = tk.Label(card, text="", bg=self.CARD, fg="#ffcf8a",
                                   font=("Segoe UI", 9), justify="left",
                                   wraplength=self.CARD_WIDTH - 40)
        self.warn_label.pack(anchor="w", pady=(2, 6))
        self._button(card, tx("btn_test"), self._pulse_now).pack(anchor="w")
        self._pulse_bar(card)
        self._refresh_warning()

        # --- 5. application --------------------------------------------
        card = self._card(tx("card_app"), None)
        self.sw_active = self._switch(card, tx("sw_active"), "active")
        self.sw_autostart = self._switch(card, tx("sw_autostart"), None,
                                         autostart_enabled, autostart_set)
        self._switch(card, tx("sw_log"), "log")
        # No language drop-down here: the flags in the top right corner are
        # the one place it is switched. Two controls for one setting is two
        # truths waiting to disagree.

        # --- 6. pause --------------------------------------------------
        card = self._card(tx("card_pause"), tx("card_pause_desc"))
        self.pause_var = self._select(
            card, None,
            [(tx("opt_not_paused"), 0)]
            + [(pause_label(m), m) for m in self.PAUSES],
            0, self._pause)

        # --- links ------------------------------------------------------
        self.links_frame = tk.Frame(self.grid_frame, bg=self.BG)
        row = tk.Frame(self.links_frame, bg=self.BG)
        row.pack(anchor="w", pady=(0, 14))
        self._link(row, tx("link_project"),
                   self._open_project).pack(side="left")
        tk.Label(row, text="   ·   ", bg=self.BG, fg=self.DIM,
                 font=("Segoe UI", 10)).pack(side="left")
        # The version belongs somewhere a user can find it when reporting a
        # problem. Same constant the file properties use, so the two can never
        # disagree.
        tk.Label(row, text=f"v{VERSION}", bg=self.BG, fg=self.DIM,
                 font=("Segoe UI", 10)).pack(side="left")
        self._button(self.links_frame, tx("btn_quit"),
                     self._quit).pack(anchor="w")

    def _fill_devices(self):
        """The list of outputs. Rebuilt whenever it can have changed - the
        widgets are destroyed with it, so no row can survive with a stale
        device index."""
        for child in self.devices_frame.winfo_children():
            child.destroy()
        devices = outputs()
        default = default_output()
        chosen = list(CFG.get("devices", []))
        listed = set()

        for device in devices:
            name = device["name"]
            listed.add(_key(name))
            label = (tx("dev_default_mark", name=name)
                     if device["index"] == default else name)
            self._option(self.devices_frame, label,
                         find_output_chosen(name, chosen),
                         lambda n=name: self._toggle_device(n))

        # a device that is configured but not plugged in must stay visible,
        # otherwise it could not be unticked
        for name in chosen:
            if _key(name) not in listed:
                self._option(self.devices_frame,
                             tx("dev_missing", name=name), True,
                             lambda n=name: self._toggle_device(n))

        if not devices and not chosen:
            tk.Label(self.devices_frame, text=tx("dev_none_found"),
                     bg=self.CARD, fg=self.DIM,
                     font=("Segoe UI", 9)).pack(anchor="w")

    # --- actions ---------------------------------------------------------

    def _set(self, key, value, warn=False):
        CFG[key] = value
        save_cfg(CFG)
        log(f"Setting '{key}' = {value}")
        ENGINE.wake.set()
        if warn:
            self._refresh_warning()
        self._refresh_status()

    def _toggle_device(self, name):
        chosen = list(CFG.get("devices", []))
        wanted = _key(name)
        kept = [n for n in chosen if _key(n) != wanted]
        if len(kept) == len(chosen):
            kept.append(name)
        CFG["devices"] = kept
        save_cfg(CFG)
        log(f"Devices: {kept}")
        self._fill_devices()
        self._refresh_status()

    def _rescan(self):
        refresh_devices()
        self._fill_devices()

    def _pulse_now(self):
        ENGINE.request_pulse()
        # The engine has to re-read the devices and open the output first, so
        # the bar is given a few seconds to wait for the sound to start -
        # otherwise a click on the button would look like nothing happened.
        self._start_bar(3.0)
        # the status refreshes on its own a moment later, once the pulse has
        # actually been played
        self._refresh_status()

    def _pause(self, minutes):
        ENGINE.pause(minutes)
        self._refresh_status()
        if self.tray:
            self.tray.refresh()

    def _change_language(self, code):
        if code == texts.language():
            return
        CFG["language"] = code
        save_cfg(CFG)
        texts.set_language(code)
        log(f"Language = {code}")
        # The whole window is rebuilt - every label is a finished string, so
        # there is nothing to re-translate in place.
        geometry = self.win.geometry()
        self.close()
        CFG["window_geometry"] = geometry
        self.open()
        if self.tray:
            self.tray.refresh()

    def _open_project(self):
        os.startfile(PROJECT_URL)

    def _quit(self):
        log("Quit by the user.")
        self.root.quit()

    # --- live status ------------------------------------------------------

    def _refresh_warning(self):
        p = periods(CFG.get("freq_hz", 20), CFG.get("duration_s", 0.4))
        if p >= 2:
            self.warn_label.configure(text="")
        else:
            self.warn_label.configure(text=tx(
                "warn_short_pulse", d=number(CFG.get("duration_s", 0.4)),
                f=number(CFG.get("freq_hz", 20)), p=number(round(p, 2))))

    def _refresh_status(self):
        if self.win is None or not self.win.winfo_exists():
            return
        state = ENGINE.state()
        if state == "paused":
            resumes = datetime.fromtimestamp(
                time.time() + ENGINE.paused()).strftime("%H:%M")
            headline = tx("st_paused", time=resumes)
        else:
            headline = tx({"ok": "st_running", "off": "st_off",
                           "partial": "st_partial",
                           "error": "st_error"}[state])
        self.status_line.configure(text=headline, fg=STATE_COLOUR[state])

        # Coloured by what the failure actually was, not by the current state:
        # switched off or paused, the app is grey, but the reason the last
        # pulse went wrong is still amber or red.
        problem = ENGINE.error or ""
        if problem != self.status_problem.cget("text"):
            self.status_problem.configure(text=problem)
            if problem:
                self.status_problem.pack(anchor="w", pady=(4, 0),
                                         after=self.status_line)
            else:
                self.status_problem.pack_forget()
        if problem:
            self.status_problem.configure(
                fg=STATE_COLOUR["partial" if ENGINE.partly else "error"])

        lines = []
        if ENGINE.last_wall is None:
            lines.append(tx("st_last_never"))
        else:
            lines.append(tx("st_last",
                            s=int(time.monotonic() - ENGINE.last_at),
                            time=ENGINE.last_wall.strftime("%H:%M:%S")))
        due = ENGINE.due_in()
        if due is None:
            lines.append(tx("st_next_paused") if state == "paused"
                         else tx("st_next_off"))
        else:
            lines.append(tx("st_next", s=int(due)))
        lines.append(tx("st_count", n=ENGINE.count))
        self.status_detail.configure(text="\n".join(lines))

        # The pause runs out on its own. The drop-down would go on claiming
        # "paused for 15 minutes" long after the app resumed - a label is not
        # allowed to be the state, it only shows it.
        if not ENGINE.paused() and self.pause_var.get() != tx("opt_not_paused"):
            self.pause_var.set(tx("opt_not_paused"))

    # --- the pulse bar ----------------------------------------------------

    def _start_bar(self, grace):
        """Set the animation loop going, unless it already is, and give the
        pulse `grace` seconds to begin."""
        self.bar_wait_until = max(self.bar_wait_until,
                                  time.monotonic() + grace)
        if self.anim is None:
            self._animate()

    def _animate(self):
        """Redraws the pulse bar 25 times a second - but only while there is
        anything to show. A loop running all day would cost power in an app
        that does something once every three minutes.
        """
        self.anim = None
        if self.win is None or not self.win.winfo_exists():
            return
        now = time.monotonic()
        error, partly = None, False
        playing = ENGINE.playing()
        if playing is not None:
            done, span = playing
            # a 0.4 s pulse would otherwise be over before the eye caught it
            self.bar_full_until = now + 0.9
        elif now < self.bar_full_until:
            done = span = ENGINE.playing_span    # played, held full a moment
            error, partly = ENGINE.error, ENGINE.partly
        elif now < self.bar_wait_until:
            done = span = 0.0                    # asked for, not started yet
        else:
            for bar in self.bars:
                bar.show(0.0, 0.0)               # back to an empty track
            return
        for bar in self.bars:
            bar.show(done, span, error, partly)
        self.anim = self.win.after(40, self._animate)

    def _tick(self):
        """Once a second: the countdown and the age of the last pulse have to
        carry their real age, not a number that looks current."""
        if self.win is None or not self.win.winfo_exists():
            return
        self._refresh_status()
        # A pulse the app sends by itself deserves the bar just as much as one
        # the user asked for - the loop is started a moment before it is due.
        due = ENGINE.due_in()
        if ENGINE.playing() is not None or (due is not None and due <= 1.0):
            self._start_bar(2.0)
        # the "start at logon" switch can be changed outside the app
        if self.sw_autostart.on != autostart_enabled():
            self.sw_autostart.on = autostart_enabled()
            self.sw_autostart.redraw()
        self.ticker = self.win.after(1000, self._tick)


def find_output_chosen(name, chosen):
    """Is this device among the ones the user ticked?"""
    wanted = _key(name)
    return any(_key(n) == wanted for n in chosen)


# ---------------------------------------------------------------- tray icon

def icon_image(color):
    """A speaker with two sound waves - readable down to 16 px."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=color)
    white = (255, 255, 255, 255)
    d.rectangle((17, 26, 25, 38), fill=white)                 # the box
    d.polygon([(25, 26), (36, 16), (36, 48), (25, 38)], fill=white)  # the cone
    d.arc((34, 20, 48, 44), 300, 60, fill=white, width=3)     # near wave
    d.arc((34, 13, 55, 51), 305, 55, fill=white, width=3)     # far wave
    return img


COLORS = {"ok": (34, 160, 80), "paused": (214, 158, 46),
          "off": (120, 120, 120), "error": (198, 60, 60)}


class TrayIcon:
    def __init__(self, root, settings):
        self.root = root
        self.settings = settings
        self.state = None
        self._signature = None
        self.icon = pystray.Icon("keep_alive", icon_image(COLORS["ok"]),
                                 APP_NAME, menu=self._menu())

    def _menu(self):
        # The item texts are functions, not finished strings: pystray calls
        # them when the menu is opened, so a language switch takes effect on
        # its own and half the menu cannot stay in the original language.
        def toggle_active(icon, item):
            CFG["active"] = not CFG.get("active", True)
            save_cfg(CFG)
            log(f"Setting 'active' = {CFG['active']}")
            ENGINE.wake.set()
            self.root.after(0, self._after_change)

        def pulse_now(icon, item):
            ENGINE.request_pulse()
            # If the window happens to be open, its bar has to show this pulse
            # as well - a pulse from the menu is the same pulse. Through
            # root.after, because the tray runs in its own thread and Tk may
            # only be touched from the thread its loop runs in.
            self.root.after(0, self._after_pulse)

        def pause_for(minutes):
            def action(icon, item):
                ENGINE.pause(minutes)
                self.root.after(0, self._after_change)
            return action

        def open_settings(icon, item):
            # Tk may only be touched from the thread its loop runs in - the
            # tray runs in its own.
            self.root.after(0, self.settings.open)

        def quit_app(icon, item):
            log("Quit from the tray icon.")
            self.root.after(0, self.root.quit)

        pause_menu = pystray.Menu(
            pystray.MenuItem(lambda item: tx("opt_not_paused"), pause_for(0)),
            *[pystray.MenuItem((lambda m: lambda item: pause_label(m))(m),
                               pause_for(m)) for m in Settings.PAUSES])

        return pystray.Menu(
            pystray.MenuItem(lambda item: tx("tray_active"), toggle_active,
                             checked=lambda item: bool(CFG.get("active", True))),
            pystray.MenuItem(lambda item: tx("tray_pulse_now"), pulse_now),
            pystray.MenuItem(lambda item: tx("tray_pause"), pause_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: tx("tray_settings"), open_settings,
                             default=True),
            pystray.MenuItem(lambda item: tx("tray_quit"), quit_app))

    def _after_change(self):
        self.refresh()
        if self.settings.win:
            self.settings._refresh_status()

    def _after_pulse(self):
        if self.settings.win:
            self.settings._start_bar(3.0)
            self.settings._refresh_status()

    def refresh(self):
        """Repaint the icon and the tooltip - but only when something really
        changed. Rebuilding the menu every couple of seconds makes it flicker
        while it is open, and there is nothing to see anyway."""
        state = ENGINE.state()
        signature = (state, texts.language(), bool(CFG.get("active", True)),
                     int(ENGINE.paused() // 60))
        if signature == self._signature:
            return
        icon_changed = state != self.state
        self._signature, self.state = signature, state
        label = {"ok": tx("st_running"), "off": tx("st_off"),
                 "error": tx("st_error"),
                 "paused": tx("st_paused", time=datetime.fromtimestamp(
                     time.time() + ENGINE.paused()).strftime("%H:%M"))}[state]
        try:
            if icon_changed:
                self.icon.icon = icon_image(COLORS[state])
            self.icon.title = f"{APP_NAME} — {label}"
            self.icon.update_menu()
        except Exception as error:
            log(f"Could not refresh the tray icon: {error}")

    def start(self):
        threading.Thread(target=self.icon.run, daemon=True).start()


# ---------------------------------------------------------------- main

def watch(root, tray):
    """Keeps the tray icon in step with what the engine is doing."""
    tray.refresh()
    root.after(2000, watch, root, tray)


def main():
    # This is how the installer will ask for the task to be created - so that
    # ONE piece of code registers it and the two cannot drift apart.
    if "--autostart-on" in sys.argv or "--autostart-off" in sys.argv:
        ok = autostart_set("--autostart-on" in sys.argv)
        return 0 if ok == ("--autostart-on" in sys.argv) else 1

    if PULSE_ONLY:
        # one pulse, no window, no tray - for a quick check that the sound
        # really comes out of the right speakers
        error = ENGINE.send(" (--pulse)")
        return 1 if error else 0

    if already_running():
        log("The app is already running - not starting a second instance.")
        if not NO_DIALOG:
            user32.MessageBoxW(0, tx("msg_already_running"), APP_NAME, 0x40)
        return 0

    log("=" * 50)
    log(f"Start. Every {CFG['interval_s']} s: {CFG['freq_hz']} Hz, "
        f"{CFG['amp_percent']} %, {CFG['duration_s']} s.")

    root = tk.Tk()
    root.withdraw()
    settings = Settings(root)
    tray = TrayIcon(root, settings)
    settings.tray = tray
    tray.start()
    ENGINE.start()
    root.after(500, watch, root, tray)
    if SHOW_AT_START:
        root.after(200, settings.open)
    if QUIT_AFTER:
        root.after(int(QUIT_AFTER * 1000), root.quit)
    root.mainloop()

    ENGINE.stop.set()
    ENGINE.wake.set()
    try:
        tray.icon.stop()
    except Exception:
        pass
    log("Ended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
