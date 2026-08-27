"""Checks of everything that can be checked without sound and without a window.

Run before every release:

    .venv\\Scripts\\python.exe tests\\test_logic.py

Every check here comes in two: one case that must pass and one that must make
it complain. A check nobody ever tried to break looks exactly the same in the
report as a check that does not work at all.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "windows"))
sys.path.insert(0, str(ROOT / "tools"))

import keep_alive as K                                  # noqa: E402
import texts                                            # noqa: E402
import tune                                             # noqa: E402

# Neither the log nor the settings belong to a test run. Run from source the
# app keeps both next to the sources, so a test run wrote into the real log and
# could save the real config.json - and if the app happened to be running, that
# save would put back the settings as they were when the test started, undoing
# whatever the user had just changed in the window.
#
# Redirecting is better than switching the writing off: both paths stay
# covered, and the checks below read the redirected files back to prove it.
K.LOG_PATH = Path(tempfile.gettempdir()) / "da-keep-speakers-alive-test.log"
K.LOG_PATH.unlink(missing_ok=True)
K.CFG_PATH = Path(tempfile.gettempdir()) / "da-keep-speakers-alive-test.json"

FAILED = []


def check(name, condition, detail=""):
    print(f"  {'ok  ' if condition else 'FAIL'}  {name}"
          + (f"   {detail}" if detail and not condition else ""))
    if not condition:
        FAILED.append(name)


# ------------------------------------------------------------ the pulse

def test_pulse():
    print("pulse")
    samplerate = 48000
    wave = K.make_pulse(freq=20, amp_percent=1.0, duration=0.4, fade=0.05,
                        samplerate=samplerate)
    check("length matches the duration", len(wave) == int(0.4 * samplerate),
          f"{len(wave)}")
    check("float32 (what the stream wants)", wave.dtype == np.float32,
          str(wave.dtype))
    peak = float(np.max(np.abs(wave)))
    check("peak is the requested 1 %", abs(peak - 0.01) < 0.0005, f"{peak:.5f}")
    check("starts and ends at silence (the fade)",
          abs(float(wave[0])) < 1e-6 and abs(float(wave[-1])) < 1e-6,
          f"{wave[0]:.6f} .. {wave[-1]:.6f}")

    # The counter-case: without a fade the burst ends on a step, and that is
    # the click the fade exists to prevent. The length must NOT be a whole
    # number of periods - 0.4 s at 20 Hz ends at the zero crossing by itself
    # and would make even an unfaded pulse look harmless.
    hard = K.make_pulse(20, 1.0, 0.4125, 0.0, samplerate)
    check("without a fade the edge really is a step",
          abs(float(hard[-1])) > 1e-4, f"{hard[-1]:.6f}")

    # a fade longer than the pulse must not eat it whole
    short = K.make_pulse(20, 1.0, 0.02, 0.5, samplerate)
    check("fade is clamped to the pulse length",
          len(short) == int(0.02 * samplerate) and float(np.max(short)) > 0)

    check("8 periods at 20 Hz / 0.4 s", K.periods(20, 0.4) == 8.0)
    check("a pulse too short for the frequency is spotted",
          K.periods(10, 0.1) < 2)
    # The window warns below two periods. A warning that no combination on
    # offer can reach guards nothing at all - so check that one exists, and
    # that the default is nowhere near it.
    reachable = min(K.periods(f, d) for f in K.Settings.FREQS
                    for d in K.Settings.DURATIONS)
    check("the too-short warning is reachable from the offered options",
          reachable < 2, f"the shortest combination is {reachable:g} periods")
    check("the default setting is far from the warning",
          K.periods(K.DEFAULTS["freq_hz"], K.DEFAULTS["duration_s"]) >= 4)

    # The buffer. Left to PortAudio it came out at 22 ms on WASAPI shared mode
    # and crackled the whole way through every pulse, at any frequency and any
    # volume, while music through the same speakers was clean. Measured by ear
    # on a 4 s tone: 22 ms crackles, 60 ms and up is clean.
    check("the buffer is well clear of the size that crackled",
          K.BUFFER_S >= 0.06, f"{K.BUFFER_S} s")
    # tune.py plays through sd.play() rather than an OutputStream, so it is a
    # second copy of this number. A measuring tool quietly using a different
    # buffer than the app would report on something the app never plays.
    check("the measuring tool buffers exactly like the app",
          tune.BUFFER_S == K.BUFFER_S, f"tune {tune.BUFFER_S} vs app {K.BUFFER_S}")


# ------------------------------------------------------------ pulse bar

def test_pulse_bar():
    """The bar under the "try a pulse" button reads the engine clock. What is
    checked here is that it can never show a number the pulse does not have."""
    print("pulse bar")
    import time
    engine = K.ENGINE
    saved = (engine.playing_from, engine.playing_span)
    try:
        engine.playing_from, engine.playing_span = 0.0, 0.0
        check("nothing playing -> the bar has nothing to show",
              engine.playing() is None)

        engine.playing_from = time.monotonic() - 0.5
        engine.playing_span = 2.0
        done, span = engine.playing()
        check("halfway through a 2 s pulse", 0.4 < done < 0.7 and span == 2.0,
              f"{done:.2f} / {span}")

        # the counter-case: the engine thread can be held up (a device that
        # takes its time opening), and the bar must stop at the end, not run on
        engine.playing_from = time.monotonic() - 10
        done, span = engine.playing()
        check("a late pulse does not run past its own length", done == span,
              f"{done} / {span}")

        # no device selected -> nothing is playing, so the bar must not fill
        # (and the length must not be divided by zero anywhere)
        engine.playing_from, engine.playing_span = time.monotonic(), 0.0
        check("a burst with no device shows nothing at all",
              engine.playing() is None)
    finally:
        engine.playing_from, engine.playing_span = saved

    texts.set_language("cs")
    check("the time keeps one decimal", K.seconds_text(1.0) == "1,0",
          K.seconds_text(1.0))
    check("and it is not the same as the plain number",
          K.number(1.0) == "1", K.number(1.0))
    texts.set_language("en")
    check("English keeps the decimal point here too",
          K.seconds_text(0.4) == "0.4", K.seconds_text(0.4))
    texts.set_language(K.CFG.get("language", "cs"))


def test_pulse_failure_clears_the_bar():
    """A failed pulse must leave the bar idle - a bar stuck at half would keep
    claiming that something is still playing."""
    print("a failed pulse")
    engine = K.ENGINE
    saved_play, saved_targets = K.play, K.targets
    saved_log, saved_error = K.CFG.get("log", True), list(engine.error_items)
    try:
        K.CFG["log"] = True             # goes to the redirected file, not the app's
        K.targets = lambda devices=None: (
            [{"index": 0, "name": "Test device", "samplerate": 48000,
              "channels": 2}], [])

        def refuses(device, wave):
            raise RuntimeError("the device refused")
        K.play = refuses

        error = engine.send(" (test)")
        check("the failure is reported, not swallowed",
              error and "refused" in error, str(error))
        check("and the bar goes back to idle", engine.playing() is None,
              str(engine.playing()))
        # The failure has to survive as far as the file, not only as far as
        # the return value - the log is where anyone looks first.
        written = (K.LOG_PATH.read_text(encoding="utf-8")
                   if K.LOG_PATH.exists() else "")
        check("and it reached the log file, not just the return value",
              "refused" in written, f"{K.LOG_PATH} holds {len(written)} chars")
        check("which is NOT the app's own log",
              K.LOG_PATH != K.DATA / "keep_alive.log", str(K.LOG_PATH))
    finally:
        K.play, K.targets = saved_play, saved_targets
        K.CFG["log"] = saved_log
        engine.error_items = saved_error


# ------------------------------------------------------------ devices

FAKE = [
    {"index": 3, "name": "Reproduktory (4 - USB Advanced Audio Device)",
     "samplerate": 48000, "channels": 2},
    {"index": 7, "name": "Sluchátka (RØDE NT-USB+)",
     "samplerate": 48000, "channels": 2},
]


def test_devices():
    print("devices")
    check("exact name is found",
          K.find_output("Sluchátka (RØDE NT-USB+)", FAKE)["index"] == 7)
    check("a different USB port still matches",
          K.find_output("Reproduktory (9 - USB Advanced Audio Device)",
                        FAKE)["index"] == 3)
    check("a device that is not there is not invented",
          K.find_output("Reproduktory (Realtek(R) Audio)", FAKE) is None)
    # Windows also puts the number in FRONT of the name, not only in brackets
    check("a number in front of the name is ignored too",
          K._key("3 - XG27ACS (AMD High Definition Audio Device)")
          == K._key("7 - XG27ACS (AMD High Definition Audio Device)"))
    check("but two different devices still do not match",
          K._key("3 - XG27ACS (AMD High Definition Audio Device)")
          != K._key("3 - XG27ACS (Realtek(R) Audio)"))

    saved = dict(K.CFG)
    try:
        K.CFG["use_default_device"] = False
        K.CFG["devices"] = ["Reproduktory (9 - USB Advanced Audio Device)"]
        chosen, missing = K.targets(FAKE)
        check("the chosen device is played to",
              [d["index"] for d in chosen] == [3] and missing == [])

        K.CFG["devices"] = ["Speakers of a machine long gone"]
        chosen, missing = K.targets(FAKE)
        check("a missing device is REPORTED, not skipped in silence",
              chosen == [] and missing == ["Speakers of a machine long gone"])
    finally:
        K.CFG.clear()
        K.CFG.update(saved)


def test_what_a_missing_device_reports():
    """An unplugged device must be reported as unplugged - and as nothing else.

    Until 19.08.2026 the app said both "no device is selected" AND "device X is
    not connected" in the same breath, and the first half was simply untrue.
    The counter-case is right below it: with nothing selected the plea to pick
    a device has to stay, or the fix would have silenced a real message.

    The log line is checked as well, because it is what a bug report is built
    from and it has to read the same on every machine - English, whatever the
    window is showing.
    """
    print("what a missing device reports")
    engine = K.ENGINE
    saved_targets, saved_log, saved_play = K.targets, K.log, K.play
    saved_error, saved_partly = list(engine.error_items), engine.partly
    saved_cfg = dict(K.CFG)
    saved_language = texts.language()
    saved_pause = engine.paused_until
    written = []
    try:
        K.log = written.append          # keeps the test out of the real log
        texts.set_language("cs")
        # state() looks at the main switch and at the pause BEFORE it looks at
        # anything that went wrong, and both come from the user's own settings
        # file. With "Keep the speakers awake" off, the checks below would get
        # "off" instead of "error" and fail for a reason that has nothing to do
        # with missing devices. Third time this bites - see CFG["log"] and the
        # retry test.
        K.CFG["active"] = True
        engine.paused_until = 0.0
        gone = "Speakers of a machine long gone"

        K.CFG["use_default_device"] = False
        K.CFG["devices"] = [gone]
        K.targets = lambda devices=None: ([], [gone])
        error = engine.send(" (test)") or ""
        check("an unplugged device is reported as unplugged",
              "není připojené" in error, error)
        check("and NOT as \"nothing is selected\" as well",
              "Není vybrané" not in error, error)
        check("the log says it in English, not in the window's language",
              written and "is not connected" in written[-1]
              and "není" not in written[-1], str(written[-1:]))

        check("nothing played, so this is a real failure",
              engine.state() == "error", engine.state())
        check("and the log does not claim anything went out",
              "->" not in written[-1], written[-1])

        # The reported case: the default device DID get the pulse, one saved
        # device did not - and the window announced "the last pulse could not
        # be played", which is simply untrue.
        K.CFG["devices"] = [gone]
        K.targets = lambda devices=None: (
            [{"index": 0, "name": "Works", "samplerate": 48000,
              "channels": 2}], [gone])
        K.play = lambda device, wave: None
        error = engine.send(" (test)") or ""
        check("a pulse that reached SOME devices is not called a failure",
              engine.state() == "partial", engine.state())
        check("and the reason is still there to read",
              "není připojené" in error, error)

        # The log was the last output still calling this a total failure. In
        # the real log of 27.08.2026 it produced twenty lines that read like
        # twenty dead pulses, while the pulse was in fact going out to the
        # default device the whole time - and the log is what a bug report is
        # built from.
        check("the log names what DID play, not only what did not",
              "-> Works" in written[-1], written[-1])
        check("and names the trouble on the same line",
              "problems:" in written[-1] and "is not connected" in written[-1],
              written[-1])

        # The reason has to FOLLOW the flag, not stay in the language it was
        # built in. It used to be glued into a sentence the moment the pulse
        # failed, so after a switch the headline was English and the line
        # under it Czech - until the next pulse, and for ever while the app
        # was off or paused.
        texts.set_language("en")
        check("and it follows a language switch instead of staying behind",
              "is not connected" in (engine.error_text() or ""),
              engine.error_text())
        texts.set_language("cs")

        K.CFG["devices"] = []
        K.targets = lambda devices=None: ([], [])
        error = engine.send(" (test)") or ""
        check("with nothing selected the plea to pick a device stays",
              "Není vybrané" in error, error)
    finally:
        K.targets, K.log, K.play = saved_targets, saved_log, saved_play
        engine.error_items, engine.partly = saved_error, saved_partly
        engine.paused_until = saved_pause
        K.CFG.clear()
        K.CFG.update(saved_cfg)
        texts.set_language(saved_language)


def test_retry_after_a_failed_pulse():
    """A pulse that failed must be retried in seconds, not one interval later.

    From the real log: the machine woke at 20:02, the USB dock was not back
    yet, the pulse failed - and the next attempt was at 20:07, by which time
    the device had been ready for minutes and the speakers had been silent
    the whole while.

    The counter-cases matter as much as the case: a successful pulse has to go
    back to the user's interval (or the app would pulse every ten seconds for
    ever), and a device that never comes back must stop being retried (or it
    would fill the log at that rate).
    """
    print("retrying a pulse that went wrong")
    engine = K.ENGINE
    saved = (engine.retries, list(engine.error_items), engine.last_at,
             engine.partly)
    saved_cfg = dict(K.CFG)
    saved_pause = engine.paused_until
    saved_targets, saved_log, saved_play = K.targets, K.log, K.play
    try:
        K.CFG["interval_s"] = 300
        # Both of these decide due_in() before the gap ever gets a say, and
        # both come from the user's real settings file. With the main switch
        # off due_in() returns None and the check below would blow up on a
        # TypeError that has nothing to do with retries.
        K.CFG["active"] = True
        engine.paused_until = 0.0
        engine.last_at = K.time.monotonic()

        engine.error_items, engine.retries = [], 0
        check("a pulse that worked waits the whole interval",
              engine.gap() == 300, engine.gap())

        engine.error_items = [("err_no_device", {})]
        engine.retries = 1
        check("the first retry comes within seconds",
              engine.gap() == 10, engine.gap())
        check("and the countdown in the window says so too",
              0 < engine.due_in() <= 10, engine.due_in())
        engine.retries = 2
        check("the second waits a little longer", engine.gap() == 20,
              engine.gap())

        engine.retries = len(engine.RETRY_STEPS) + 1
        check("a device that never comes back stops being retried",
              engine.gap() == 300, engine.gap())

        # A retry must never be LONGER than the interval itself - at 30 s the
        # 60 s step would push the pulse further away than doing nothing.
        K.CFG["interval_s"] = 30
        engine.retries = 4
        check("a retry is never longer than the interval",
              engine.gap() == 30, engine.gap())

        # Everything above reads `retries`; nothing above WRITES it the way
        # the app does. Setting it by hand in a test and asking gap() about it
        # proves only that gap() can divide - with send() failing to count,
        # the retry would never happen in the first place and every check so
        # far would still pass.
        K.log = lambda line: None       # the failures below are on purpose
        engine.retries, engine.error_items = 0, []
        K.targets = lambda devices=None: ([], ["Speakers long gone"])
        engine.send(" (test)")
        check("a pulse that went wrong is counted as a retry",
              engine.retries == 1, engine.retries)
        engine.send(" (test)")
        check("and another one counts again", engine.retries == 2,
              engine.retries)
        K.targets = lambda devices=None: (
            [{"index": 0, "name": "Works", "samplerate": 48000,
              "channels": 2}], [])
        K.play = lambda device, wave: None
        engine.send(" (test)")
        check("a pulse that got through puts the count back to zero",
              engine.retries == 0, engine.retries)
    finally:
        K.targets, K.log, K.play = saved_targets, saved_log, saved_play
        engine.retries, engine.error_items, engine.last_at, engine.partly = saved
        engine.paused_until = saved_pause
        K.CFG.clear()
        K.CFG.update(saved_cfg)


def test_a_sleep_is_noticed():
    """After the machine wakes up the pulse has to go out at once.

    time.monotonic() runs on QueryPerformanceCounter here and stands still
    while the machine sleeps, so the countdown alone never notices: twelve
    hours of standby in the real log went by as "a couple of minutes" and the
    app sat out the rest of the interval with the speakers already asleep.
    Only the wall clock keeps running, so the two drifting apart is the test.

    The counter-case is the one that makes this worth anything: an ordinary
    second must NOT be mistaken for a sleep, or the app would pulse every
    second for ever.
    """
    print("noticing that the machine was asleep")
    engine = K.ENGINE
    saved = (engine.woke_up, engine.clock_gap, engine.last_at,
             engine.paused_until)
    try:
        engine.last_at = K.time.monotonic()

        engine.woke_up = False
        engine.clock_gap = K.time.time() - K.time.monotonic()
        engine.check_for_a_break()
        check("an ordinary second is not mistaken for a sleep",
              engine.woke_up is False, engine.woke_up)

        # the wall clock ran on for an hour while monotonic did not
        engine.clock_gap = K.time.time() - K.time.monotonic() - 3600
        engine.check_for_a_break()
        check("an hour the monotonic clock slept through is noticed",
              engine.woke_up is True, engine.woke_up)

        # and having noticed it, the next reading must be clean again -
        # otherwise every following second would count as another wake-up
        engine.woke_up = False
        engine.check_for_a_break()
        check("and it is not reported a second time",
              engine.woke_up is False, engine.woke_up)

        # a clock put BACK (by hand, or by a time server) is not a wake-up
        engine.clock_gap = K.time.time() - K.time.monotonic() + 3600
        engine.check_for_a_break()
        check("a clock put back is not treated as a wake-up",
              engine.woke_up is False, engine.woke_up)

        # The age of the last pulse has to survive the sleep as well. It is
        # read off the monotonic clock while the time beside it comes from the
        # wall clock, so without a correction the window said "last pulse 63 s
        # ago (22:04)" at five in the morning.
        engine.last_at = K.time.monotonic()
        engine.clock_gap = K.time.time() - K.time.monotonic() - 3600
        engine.check_for_a_break()
        age = K.time.monotonic() - engine.last_at
        check("and the last pulse is then as old as it really is",
              3590 < age < 3610, age)
    finally:
        (engine.woke_up, engine.clock_gap, engine.last_at,
         engine.paused_until) = saved


def test_a_pause_runs_in_real_time():
    """"Pause for 15 minutes" has to mean fifteen minutes of REAL time.

    The deadline used to be kept on the monotonic clock, which stands still
    while the machine sleeps - so a pause set in the evening came back from
    an overnight standby with its full fifteen minutes still to run. It is on
    the wall clock now, which needs no correcting afterwards and cannot be
    overwritten by the engine thread and the window thread in turn.

    Reading the deadline back against the wall clock is what proves which
    clock it is on: the two are billions of seconds apart, so a mismatch
    cannot pass unnoticed.
    """
    print("a pause in real time")
    engine = K.ENGINE
    saved_pause, saved_log = engine.paused_until, K.log
    try:
        K.log = lambda *a, **kw: None        # keeps the test out of the log
        engine.pause(15)
        check("a pause is measured on the clock that keeps running",
              890 < engine.paused() <= 900, engine.paused())
        check("and its deadline is wall-clock time, not time since boot",
              abs(engine.paused_until - K.time.time() - 900) < 2,
              engine.paused_until - K.time.time())
        engine.pause(0)
        check("cancelling it clears the deadline", engine.paused() == 0,
              engine.paused())
    finally:
        engine.paused_until, K.log = saved_pause, saved_log


def test_the_engine_loop_does_its_job():
    """The loop itself, not the sums it uses. Two things it has to do:

    1. Pulse the moment a wake-up is noticed, without waiting for the
       countdown. Everything else about waking up is checked one function at a
       time above - check_for_a_break() sets a flag, gap() divides - and all
       of it would still pass with the flag never wired to a pulse at all.

    2. Survive an unexpected error instead of ending the thread. That failure
       is the silent kind: with the engine gone, error_items stays empty, so
       state() answers "ok", the icon stays green and the window promises the
       speakers are being kept awake while nothing is sent ever again.

    The loop is run in THIS thread, one turn at a time - each stand-in stops
    it, so run() returns instead of looping for the length of the test.
    """
    print("the engine loop does what the pieces cannot")
    engine = K.ENGINE
    saved = (engine.woke_up, engine.last_at, engine.retries,
             list(engine.error_items), engine.paused_until, engine.pulse_now)
    saved_send, saved_check, saved_log = (engine.send, engine.check_for_a_break,
                                          K.log)
    saved_cfg = dict(K.CFG)
    written = []
    try:
        K.log = written.append
        K.CFG["active"] = True
        K.CFG["interval_s"] = 3600      # nothing is due for an hour
        engine.paused_until = 0.0
        engine.pulse_now = False
        engine.last_at = K.time.monotonic()
        engine.error_items, engine.retries = [], 0

        sent = []

        def one_turn_then_stop(reason=""):
            sent.append(reason)

        # The loop is stopped from check_for_a_break(), which runs first every
        # turn - NOT from the stand-in send(). Hanging the exit on send() being
        # called means that when the pulse is the thing that broke, this test
        # HANGS instead of failing, and a hung test looks slow rather than red.
        def one_turn_only():
            saved_check()
            engine.stop.set()
            engine.wake.set()

        engine.check_for_a_break = one_turn_only
        engine.send = one_turn_then_stop
        engine.woke_up = True
        engine.stop.clear()
        engine.run()
        engine.check_for_a_break = saved_check
        check("a wake-up pulses without waiting out the interval",
              sent == [" (after a break)"], sent)

        # and the flag has to be put down again, or it would pulse every
        # second from then on
        check("and the wake-up is not left standing", engine.woke_up is False,
              engine.woke_up)

        engine.send = saved_send

        def explode():
            engine.stop.set()           # one turn is enough
            engine.wake.set()
            raise RuntimeError("the device list exploded")

        engine.check_for_a_break = explode
        engine.error_items = []
        engine.stop.clear()
        engine.run()                    # must RETURN, not raise
        check("an unexpected error does not end the engine in silence",
              engine.state() == "error", engine.state())
        check("and it says what actually happened",
              "exploded" in (engine.error_text() or ""), engine.error_text())
        check("and the log has it in English",
              any("exploded" in line for line in written), str(written[-1:]))

        # The same fault comes back every second. Reporting it every second
        # would bury the log - roughly 43 000 lines a day - and rotation would
        # then throw away the history that explains it.
        written.clear()
        engine.stop.clear()
        engine.run()
        check("but the same error is not written to the log again",
              written == [], str(written))
    finally:
        engine.send, engine.check_for_a_break, K.log = (saved_send, saved_check,
                                                        saved_log)
        (engine.woke_up, engine.last_at, engine.retries, engine.error_items,
         engine.paused_until, engine.pulse_now) = saved
        engine.stop.clear()
        engine.wake.clear()
        K.CFG.clear()
        K.CFG.update(saved_cfg)


def test_a_speaker_plugged_in_gets_the_pulse_at_once():
    """A speaker that becomes reachable has to be pulsed, not made to wait.

    Two ways that happens, and the same problem behind both: a machine that has
    been running for a while and only now gets its speakers connected used to
    send nothing for up to a whole interval, with the speakers asleep for all
    of it - and a speaker that is muted takes the pulse and plays nothing, so
    un-muting leaves it asleep in exactly the same way.

    The device list and the mute state are both stood in for, so this never
    touches the real outputs - and the last part runs the LOOP, because a scan
    that nothing calls would pass every check made by hand and still never fire
    in the app.
    """
    print("a speaker plugged in - or un-muted - gets the pulse at once")
    engine = K.ENGINE
    saved = (engine.seen, engine.muted, engine.scanned_at, engine.last_at,
             engine.woke_up, engine.pulse_now, engine.paused_until,
             engine.retries, list(engine.error_items))
    saved_send, saved_refresh = engine.send, K.refresh_devices
    saved_targets, saved_cfg = K.targets, dict(K.CFG)
    saved_muted = K.muted_devices
    here = []                       # what the stand-in currently "sees"
    silent = []                     # ... which of those are silenced
    unsure = []                     # ... and which would not answer at all

    def fake_targets(devices=None):
        return [{"name": name, "index": 0, "samplerate": 48000, "channels": 2}
                for name in here], []

    def fake_muted():
        # None is Core Audio refusing to answer, which is NOT "nothing muted".
        # Otherwise (what is silenced, what would not say) - three answers per
        # device, and the third one is the whole reason this is a pair.
        if silent is None:
            return None
        return ({K._key(n) for n in silent}, {K._key(n) for n in unsure})

    speakers = "Speakers (4 - USB Advanced Audio Device)"
    headphones = "Headphones (RODE NT-USB+)"
    monitor = "2 - XG27ACS (AMD High Definition Audio Device)"
    try:
        K.refresh_devices = lambda: True
        K.targets = fake_targets
        K.muted_devices = fake_muted
        K.CFG["active"] = True
        K.CFG["interval_s"] = 3600          # nothing is due for an hour
        engine.paused_until = 0.0
        engine.pulse_now = False
        engine.woke_up = False
        engine.error_items, engine.retries = [], 0
        engine.last_at = K.time.monotonic()
        engine.seen, engine.muted, engine.scanned_at = None, None, 0.0

        here[:] = [headphones]
        check("the first look only takes note, it never pulses",
              engine.a_device_needs_a_pulse() is None, engine.seen)

        engine.scanned_at = 0.0             # let it look again
        check("nothing new means no pulse",
              engine.a_device_needs_a_pulse() is None, engine.seen)

        here[:] = [headphones, speakers]
        check("a scan too soon is skipped, whatever changed",
              engine.a_device_needs_a_pulse() is None, engine.scanned_at)

        engine.scanned_at = 0.0
        check("a speaker that turned up asks for a pulse",
              engine.a_device_needs_a_pulse() == " (a new device to keep awake)",
              engine.seen)

        engine.scanned_at = 0.0
        here[:] = [headphones]
        check("one going away does NOT pulse - it cannot be reached anyway",
              engine.a_device_needs_a_pulse() is None, engine.seen)

        # --- the same thing, done with the mute switch --------------------
        engine.scanned_at = 0.0
        here[:] = [headphones, speakers]
        silent = [speakers]
        check("arriving muted still counts as arriving",
              engine.a_device_needs_a_pulse() == " (a new device to keep awake)",
              engine.seen)

        engine.scanned_at = 0.0
        check("a device that stays muted does not pulse over and over",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))

        engine.scanned_at = 0.0
        silent = []
        check("un-muting one asks for a pulse",
              engine.a_device_needs_a_pulse() == " (a device is audible again)",
              sorted(engine.muted))

        engine.scanned_at = 0.0
        check("and only once - the watch was brought up to date",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))

        engine.scanned_at = 0.0
        silent = [speakers]
        check("muting one is not a reason to pulse either",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))

        # A muted device that goes AWAY drops out of the muted set as surely as
        # one that gets un-muted - the set only ever holds devices that are
        # present. Reading that as "it became audible" pulses at a speaker that
        # has just been unplugged, and writes a log line saying it is audible
        # again while send() reports it missing in the same breath.
        #
        # The check above this one cannot catch that: nothing is muted there,
        # so there is nothing to drop out. It has to be muted first.
        engine.scanned_at = 0.0
        here[:] = [headphones]
        check("a muted device being unplugged is NOT it becoming audible",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted or ()))
        here[:] = [headphones, speakers]
        silent = [speakers]
        engine.scanned_at = 0.0
        engine.a_device_needs_a_pulse()      # back to: both here, one muted

        # The trap: both things happening in the SAME scan - something arrives
        # while something else is un-muted. Only one pulse goes out, so the
        # answer that did NOT fire must still leave its watch up to date, or
        # the next scan finds the un-mute still pending and sends a second one.
        #
        # It has to be two different devices. One device arriving un-muted
        # cannot show this: a device that is not in the list cannot be in the
        # muted set either (the set is intersected with what is present), so
        # there is nothing stale left behind to fire later. A check built that
        # way passes whether the code updates the watch or not.
        engine.scanned_at = 0.0
        here[:] = [headphones, speakers]
        silent = [speakers]
        engine.a_device_needs_a_pulse()      # known: speakers here and muted
        engine.scanned_at = 0.0
        here[:] = [headphones, speakers, monitor]
        silent = []                          # monitor arrives, speakers wake up
        check("arrival wins when both happen at once",
              engine.a_device_needs_a_pulse() == " (a new device to keep awake)",
              engine.seen)
        engine.scanned_at = 0.0
        check("and the un-mute does NOT fire a second pulse afterwards",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))
        here[:] = [headphones, speakers]

        # Someone else's speakers being muted is none of our business: only
        # devices the user picked are compared, so the sets stay small and a
        # mute on an untouched output cannot pulse anything.
        engine.scanned_at = 0.0
        silent = ["Monitor (AMD High Definition Audio Device)"]
        check("a device we do not keep awake is ignored, muted or not",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))

        # Core Audio not answering must not look like "nothing is muted".
        engine.scanned_at = 0.0
        silent = [speakers]
        engine.a_device_needs_a_pulse()      # the speakers are known muted now
        engine.scanned_at = 0.0
        silent = None                        # ... and now the read fails
        check("a failed read does not pulse",
              engine.a_device_needs_a_pulse() is None, engine.muted)
        check("and it KEEPS what was known instead of emptying the watch",
              engine.muted == {K._key(speakers)}, engine.muted)
        engine.scanned_at = 0.0
        silent = [speakers]                  # working again, still muted
        check("the look after it does not pulse either, nothing changed",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))
        engine.scanned_at = 0.0
        silent = []
        check("proved: un-muting after that failure does pulse",
              engine.a_device_needs_a_pulse() == " (a device is audible again)",
              sorted(engine.muted))

        # The point of keeping the watch: an un-mute that happens WHILE the
        # reading is broken still has to be noticed once it works again.
        # Emptying the watch would make the next good look "fill it in" and
        # the pulse would never come.
        engine.scanned_at = 0.0
        silent = [speakers]
        engine.a_device_needs_a_pulse()      # muted and known to be
        engine.scanned_at = 0.0
        silent = None                        # reading breaks...
        engine.a_device_needs_a_pulse()
        engine.scanned_at = 0.0
        silent = []                          # ...and it was un-muted meanwhile
        check("an un-mute during a broken reading is caught afterwards",
              engine.a_device_needs_a_pulse() == " (a device is audible again)",
              sorted(engine.muted))

        # One endpoint refusing to answer is NOT the same as it being muted.
        # Counting it as muted meant it dropped out again on the next good
        # reading and looked like an un-mute - a pulse, and a log line, about
        # a device nobody had touched.
        engine.scanned_at = 0.0
        silent, unsure = [], []
        engine.a_device_needs_a_pulse()      # both here, neither muted
        engine.scanned_at = 0.0
        unsure = [speakers]                  # the speakers will not answer
        check("an endpoint that will not answer is not a reason to pulse",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))
        engine.scanned_at = 0.0
        unsure = []                          # and now it answers again
        check("and recovering from that is not an un-mute either",
              engine.a_device_needs_a_pulse() is None, sorted(engine.muted))

        # The other direction: a device that WAS muted and then would not
        # answer keeps its muted state, so the real un-mute still counts.
        engine.scanned_at = 0.0
        silent = [speakers]
        engine.a_device_needs_a_pulse()
        engine.scanned_at = 0.0
        silent, unsure = [], [speakers]      # muted, then goes quiet on us
        check("a muted device that stops answering stays muted in the watch",
              engine.a_device_needs_a_pulse() is None
              and engine.muted == {K._key(speakers)}, sorted(engine.muted))
        engine.scanned_at = 0.0
        unsure = []                          # answers again, and is audible
        check("so the real un-mute after it is still caught",
              engine.a_device_needs_a_pulse() == " (a device is audible again)",
              sorted(engine.muted))

        # Wired in, part one: the loop has to send it. Everything above would
        # still pass with a_device_needs_a_pulse() called from nowhere at all.
        engine.scanned_at = 0.0
        engine.seen, engine.muted = {K._key(headphones)}, set()
        here[:] = [headphones, speakers]
        sent = []

        def one_turn_then_stop(reason=""):
            sent.append(reason)

        # The loop is stopped from check_for_a_break(), which every turn runs
        # first, NOT from the stand-in send(). Hanging the exit on send() being
        # called is how this test HANGS instead of failing when the pulse is
        # the thing that broke - which is exactly the case it exists to catch.
        saved_check_break = engine.check_for_a_break

        def one_turn_only():
            saved_check_break()
            engine.stop.set()
            engine.wake.set()

        engine.check_for_a_break = one_turn_only
        engine.send = one_turn_then_stop
        engine.stop.clear()
        engine.run()
        engine.check_for_a_break = saved_check_break
        check("and the loop is the one that sends it",
              sent == [" (a new device to keep awake)"], sent)

        # The same wiring for the other reason: nothing arrives, a device is
        # merely un-muted, and the loop still has to be the one that sends it.
        engine.scanned_at = 0.0
        engine.seen = {K._key(headphones), K._key(speakers)}
        engine.muted = {K._key(speakers)}
        silent = []
        sent.clear()
        engine.check_for_a_break = one_turn_only
        engine.send = one_turn_then_stop
        engine.stop.clear()
        engine.run()
        engine.check_for_a_break = saved_check_break
        check("and the loop sends the un-mute pulse too",
              sent == [" (a device is audible again)"], sent)

        # Wired in, part two: the REAL send() re-reads the list itself, so it
        # has to leave BOTH watches up to date. Otherwise a device that arrived
        # - or was un-muted - between two scans and got this very pulse still
        # looks new at the next scan and earns a second one.
        engine.send = saved_send
        saved_play, played = K.play, []
        K.play = lambda device, wave: played.append(device["name"])
        try:
            engine.seen = {K._key(headphones)}
            engine.muted = {K._key(speakers)}
            engine.scanned_at = 0.0
            here[:] = [headphones, speakers]
            silent = []
            engine.send(" (test)")
            check("a real pulse reached both stand-in devices",
                  played == [headphones, speakers], played)
            after = set(engine.seen or ())
            check("and the watch knows about them already, so no second pulse",
                  after == {K._key(headphones), K._key(speakers)}, sorted(after))
            check("and the mute watch was brought up to date as well",
                  engine.muted == set(), engine.muted)
            engine.scanned_at = 0.0
            check("proved: the very next scan finds nothing new",
                  engine.a_device_needs_a_pulse() is None, engine.seen)
        finally:
            K.play = saved_play
        engine.error_items, engine.retries = [], 0

        # Switched off or paused: what was plugged in meanwhile is not news
        # worth a pulse the second it comes back.
        engine.stop.clear()
        K.CFG["active"] = False
        engine.send = one_turn_then_stop
        sent.clear()

        def stop_after_one():
            engine.stop.set()
            engine.wake.set()

        saved_check_break = engine.check_for_a_break
        engine.check_for_a_break = stop_after_one
        engine.run()
        engine.check_for_a_break = saved_check_break
        check("switched off, the loop sends nothing", sent == [], sent)
        check("and it forgets the list instead of hoarding it",
              engine.seen is None, engine.seen)
        check("the mute watch is forgotten too, for the same reason",
              engine.muted is None, engine.muted)
    finally:
        engine.send, K.refresh_devices = saved_send, saved_refresh
        K.targets, K.muted_devices = saved_targets, saved_muted
        (engine.seen, engine.muted, engine.scanned_at, engine.last_at,
         engine.woke_up, engine.pulse_now, engine.paused_until, engine.retries,
         engine.error_items) = saved
        engine.stop.clear()
        engine.wake.clear()
        K.CFG.clear()
        K.CFG.update(saved_cfg)


# ------------------------------------------------------------ settings file

RUNTIME_ONLY = {"window_geometry"}      # the app writes these for itself


def test_config_encoding():
    """A settings file saved by Notepad starts with a BOM. The app has to read
    it anyway - otherwise everything the user set silently falls back to the
    defaults, and nothing on screen says so."""
    print("settings file encoding")
    import tempfile
    folder = Path(tempfile.mkdtemp())
    try:
        path = folder / "config.json"
        content = json.dumps({"interval_s": 42}, ensure_ascii=False)
        path.write_text(content, encoding="utf-8-sig")     # as Notepad saves
        check("a file with a BOM is read",
              K.read_json(path)["interval_s"] == 42)
        # the counter-case: this is exactly what used to break
        try:
            json.loads(path.read_text(encoding="utf-8"))
            plain_utf8_fails = False
        except ValueError:
            plain_utf8_fails = True
        check("and it really would have failed without the fix",
              plain_utf8_fails)
        path.write_text(content, encoding="utf-8")         # and without a BOM
        check("a file without a BOM is read too",
              K.read_json(path)["interval_s"] == 42)
    finally:
        for leftover in folder.glob("*"):
            leftover.unlink()
        folder.rmdir()


def test_problems():
    """Trouble that happens where nothing can be printed.

    A packaged build has no console - sys.stdout is None and print() does
    nothing at all - so anything reported that way was invisible to everyone
    who did not run the app from the sources. A damaged config.json is the
    worst one to lose quietly: the chosen speakers live in that file, so the
    app would go on pulsing at the wrong output while the user thinks nothing
    has changed.
    """
    print("problems that have nowhere to be printed")
    import tempfile
    folder = Path(tempfile.mkdtemp())
    was_path, was_problems = K.CFG_PATH, list(K.PROBLEMS)
    was_language, was_log = K.texts.language(), K.CFG.get("log", True)
    try:
        # goes to the redirected file, not the app's - and without this the
        # check below would break the moment someone unticked "write a log
        # file" in the window, for a reason that has nothing to do with it
        K.CFG["log"] = True
        K.PROBLEMS.clear()
        K.CFG_PATH = folder / "config.json"
        K.CFG_PATH.write_text("{ this is not json", encoding="utf-8")
        cfg = K.load_cfg()
        check("a damaged settings file is noticed",
              [key for key, _ in K.PROBLEMS] == ["warn_config"], K.PROBLEMS)
        check("and the defaults are used in the meantime",
              cfg["interval_s"] == K.DEFAULTS["interval_s"])

        # Once, not once per read. Said every time, a log that cannot be
        # written would repeat itself on every single line.
        K.load_cfg()
        check("and it is said once, not on every read",
              len(K.PROBLEMS) == 1, K.PROBLEMS)

        # Kept as a key plus arguments. A finished sentence could not be shown
        # in the window's language AND written to the log in English - which
        # is the rule for every line the log carries.
        # PROBLEMS may be empty here - that is one of the failures above, and
        # a test that blows up on it would take the rest of the file with it
        # and report nothing about the checks that come after.
        key, args = K.PROBLEMS[0] if K.PROBLEMS else ("warn_config", {})
        K.texts.set_language("cs")
        czech = K.texts.t(key, **args)
        K.texts.set_language("en")
        english = K.texts.t(key, **args)
        check("the window can say it in Czech", "výchozí" in czech, czech)
        check("and the log in English, out of the same problem",
              "defaults" in english and english != czech, english)

        # ... and it really reaches the log file, in English, while the window
        # is set to Czech. The log is always English - see CLAUDE.md.
        K.texts.set_language("cs")
        K.PROBLEMS[:] = [("warn_config", {"error": "a broken file"})]
        K.log_pending_problems()
        written = K.LOG_PATH.read_text(encoding="utf-8")
        check("the log file gets it, in English even with a Czech window",
              "defaults are in use" in written, written.strip()[-90:])

        # the counter-case: a file that reads fine must leave nothing behind
        K.PROBLEMS.clear()
        K.CFG_PATH.write_text(json.dumps({"interval_s": 42}), encoding="utf-8")
        K.load_cfg()
        check("a readable file leaves nothing to report",
              K.PROBLEMS == [], K.PROBLEMS)
    finally:
        K.texts.set_language(was_language)
        K.CFG["log"] = was_log
        K.CFG_PATH = was_path
        K.PROBLEMS[:] = was_problems
        for leftover in folder.glob("*"):
            leftover.unlink()
        folder.rmdir()


def test_config_template():
    print("config.default.json")
    template = K.read_json(Path(K.HERE) / "config.default.json")
    shipped = {k: v for k, v in template.items() if not k.startswith("_")}
    expected = {k: v for k, v in K.DEFAULTS.items() if k not in RUNTIME_ONLY}
    check("the shipped file lists exactly the settings the app has",
          set(shipped) == set(expected),
          f"only in the file: {sorted(set(shipped) - set(expected))}, "
          f"only in the app: {sorted(set(expected) - set(shipped))}")
    differ = [k for k in sorted(set(shipped) & set(expected))
              if shipped[k] != expected[k]]
    check("and the same values", not differ, f"differ: {differ}")

    # the counter-case: a drifted template must not pass
    drifted = dict(shipped)
    drifted["interval_s"] = 999
    check("a drifted value would be caught",
          any(drifted[k] != expected[k] for k in expected if k in drifted))

    check("comment keys are ignored when loading",
          all(k.startswith("_") or k in expected for k in template))


# ------------------------------------------------------------ texts

def test_texts():
    print("texts")
    check("no key exists in one language only", not texts.missing(),
          str(texts.missing()))

    # A placeholder that exists in one language and not in the other blows up
    # only when that text is actually shown - usually at the customer's.
    import re
    bad = []
    for key in texts.CS:
        cs = set(re.findall(r"{(\w+)}", texts.CS[key]))
        en = set(re.findall(r"{(\w+)}", texts.EN.get(key, "")))
        if cs != en:
            bad.append(key)
    check("both languages use the same placeholders", not bad, str(bad))

    texts.set_language("cs")
    check("Czech plural: 1 minuta", K.interval_label(60) == "1 minuta",
          K.interval_label(60))
    check("Czech plural: 3 minuty", K.interval_label(180) == "3 minuty",
          K.interval_label(180))
    check("Czech plural: 10 minut", K.interval_label(600) == "10 minut",
          K.interval_label(600))
    check("seconds below a minute", K.interval_label(30) == "30 sekund")
    check("Czech decimal comma", K.number(0.4) == "0,4", K.number(0.4))
    texts.set_language("en")
    check("English needs no plural table",
          K.interval_label(60) == "1 minute", K.interval_label(60))
    check("English keeps the decimal point", K.number(0.4) == "0.4")
    texts.set_language(K.CFG.get("language", "cs"))


def test_one_endpoint_that_will_not_answer():
    """One difficult output must not throw away what all the others said.

    Asking Core Audio walks every active endpoint one by one, and any of them
    can refuse - a device being unplugged half way through the walk is
    ordinary. Letting that failure out would mean the whole answer comes back
    as "cannot tell", and the un-mute pulse would quietly never happen again
    while it lasted.

    The other half matters just as much: a device that could not be read has
    to count as SILENT. Dropping it out of the set instead would look exactly
    like it becoming audible, and would pulse at a device nobody touched.

    Talks to the real Core Audio of this machine - only _is_silent() is stood
    in for, so the walk itself is the real one. Asked through muted_devices()
    rather than _read_silenced() on purpose: that is the door the app uses, and
    a broken walk then shows up as a red check rather than as a stack trace.
    """
    print("one endpoint that will not answer")
    saved = K._is_silent
    try:
        # Counted by how many endpoints the walk really visits, NOT by how many
        # keys come back: _key() drops the port number, so two outputs of the
        # same model collapse into one key and a count taken from the set would
        # go red over working code.
        walked = []
        K._is_silent = lambda device: walked.append(device) or True
        answer = K.muted_devices()
        check("Core Audio answered at all on this machine", answer is not None,
              repr(answer))
        if answer is None:
            return                          # nothing further can be told here
        everything, unsure = answer
        endpoints = len(walked)
        check("the machine has endpoints to walk at all", endpoints > 0,
              endpoints)
        check("and none of them were unreadable to start with", unsure == set(),
              sorted(unsure))

        asked = []

        def refuses_the_first(device):
            asked.append(device)
            if len(asked) == 1:
                raise OSError("pretend this endpoint is being unplugged")
            return True

        K._is_silent = refuses_the_first
        silent_after, unsure_after = K.muted_devices()
        check("a refusing endpoint does not throw away the whole answer",
              silent_after | unsure_after == everything,
              sorted(silent_after | unsure_after))
        check("and it lands in 'could not tell', never in 'muted'",
              len(unsure_after) == 1 and not (unsure_after & silent_after),
              f"silent={sorted(silent_after)} unsure={sorted(unsure_after)}")
        check("and the walk went on past it, it did not stop there",
              len(asked) == endpoints, f"{len(asked)} of {endpoints}")

        # The counter-case: without a name there is no way to say which device
        # the trouble belongs to, so the whole reading has to admit it failed.
        saved_name = K._friendly_name
        try:
            K._friendly_name = lambda device: (_ for _ in ()).throw(
                OSError("pretend the name cannot be read"))
            check("but a nameless endpoint makes the whole reading unknown",
                  K.muted_devices() is None, K.muted_devices())
        finally:
            K._friendly_name = saved_name
    finally:
        K._is_silent = saved


def main():
    for test in (test_pulse, test_pulse_bar, test_pulse_failure_clears_the_bar,
                 test_devices, test_what_a_missing_device_reports,
                 test_retry_after_a_failed_pulse, test_a_sleep_is_noticed,
                 test_a_pause_runs_in_real_time,
                 test_the_engine_loop_does_its_job,
                 test_a_speaker_plugged_in_gets_the_pulse_at_once,
                 test_one_endpoint_that_will_not_answer,
                 test_config_encoding, test_problems, test_config_template,
                 test_texts):
        test()
    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
