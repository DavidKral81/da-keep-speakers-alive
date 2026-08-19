"""Checks of everything that can be checked without sound and without a window.

Run before every release:

    .venv\\Scripts\\python.exe tests\\test_logic.py

Every check here comes in two: one case that must pass and one that must make
it complain. A check nobody ever tried to break looks exactly the same in the
report as a check that does not work at all.
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows"))

import keep_alive as K                                  # noqa: E402
import texts                                            # noqa: E402

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
    saved_log, saved_error = K.CFG.get("log", True), engine.error
    try:
        K.CFG["log"] = False            # no test noise in the real log file
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
    finally:
        K.play, K.targets = saved_play, saved_targets
        K.CFG["log"] = saved_log
        engine.error = saved_error


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
    saved_targets, saved_log = K.targets, K.log
    saved_error, saved_cfg = engine.error, dict(K.CFG)
    saved_language = texts.language()
    written = []
    try:
        K.log = written.append          # keeps the test out of the real log
        texts.set_language("cs")
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

        K.CFG["devices"] = []
        K.targets = lambda devices=None: ([], [])
        error = engine.send(" (test)") or ""
        check("with nothing selected the plea to pick a device stays",
              "Není vybrané" in error, error)
    finally:
        K.targets, K.log = saved_targets, saved_log
        engine.error = saved_error
        K.CFG.clear()
        K.CFG.update(saved_cfg)
        texts.set_language(saved_language)


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


def main():
    for test in (test_pulse, test_pulse_bar, test_pulse_failure_clears_the_bar,
                 test_devices, test_what_a_missing_device_reports,
                 test_config_encoding, test_config_template, test_texts):
        test()
    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) FAILED: {', '.join(FAILED)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
