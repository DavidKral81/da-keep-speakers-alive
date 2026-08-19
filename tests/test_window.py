"""Drives the settings window through the branches a normal run never hits.

Switching the language, ticking a device, a pause that expires, closing the
window twice - all of it works or breaks in front of the user, and none of it
is covered by test_logic.py. The window is really created here (a Tk window
does flash up), only nothing is clicked by hand.

Run before every release:

    .venv\\Scripts\\python.exe tests\\test_window.py

    ... --break-it     deliberately re-introduces two bugs - the mouse wheel
                       one and a pulse bar that never moves - to prove the
                       checks for them can actually fail

The settings file is saved and put back at the end, so a test run cannot
change what the app does afterwards.
"""

import json
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows"))

import keep_alive as K                                  # noqa: E402

# Same as in test_logic.py. Driving the window turns every knob there is, and
# each turn is both a log line and a saved config.json - neither of which
# belongs to the app the user is running. The settings file matters most here:
# this test SAVES at the end, and with the app running that save would put its
# own starting snapshot back over whatever the user changed meanwhile.
#
# Redirected rather than switched off, so the writing path is still exercised -
# the last step reads both files back.
K.LOG_PATH = Path(tempfile.gettempdir()) / "da-keep-speakers-alive-test.log"
K.LOG_PATH.unlink(missing_ok=True)
K.CFG_PATH = Path(tempfile.gettempdir()) / "da-keep-speakers-alive-test.json"

BREAK_IT = "--break-it" in sys.argv
FAILED = []


def step(name, action):
    try:
        action()
        print(f"  ok    {name}")
    except Exception as error:
        FAILED.append(f"{name}: {error}")
        print(f"  FAIL  {name}: {error}")


def main():
    if BREAK_IT:
        # a bar that is told nothing and therefore never moves - exactly the
        # regression the check below exists for
        K.PulseBar.show = lambda self, done, span, error=None, partly=False: None
    saved_config = json.dumps(dict(K.CFG))
    root = tk.Tk()
    root.withdraw()
    settings = K.Settings(root)
    tray = K.TrayIcon(root, settings)      # built, but never run()
    settings.tray = tray

    def run():
        print("window")
        step("opens", settings.open)

        name = "Reproduktory (Realtek(R) Audio)"

        def tick_device():
            settings._toggle_device(name)
            assert name in K.CFG["devices"], K.CFG["devices"]
            settings._toggle_device(name)
            assert name not in K.CFG["devices"], K.CFG["devices"]
        step("a device can be ticked and unticked", tick_device)

        def pause():
            settings._pause(15)
            assert K.ENGINE.state() == "paused", K.ENGINE.state()
            root.update()
            assert "ozastav" in settings.status_line["text"] \
                or "aused" in settings.status_line["text"], \
                settings.status_line["text"]
            assert K.ENGINE.due_in() is None
        step("a pause stops the countdown and shows itself", pause)

        def pause_expires():
            # the label must not go on claiming a pause that has run out
            K.ENGINE.paused_until = 0.0
            root.update()
            settings._refresh_status()
            assert settings.pause_var.get() == K.tx("opt_not_paused"), \
                settings.pause_var.get()
        step("an expired pause resets the drop-down", pause_expires)

        def warn():
            settings._set("freq_hz", 5)
            settings._set("duration_s", 0.2, warn=True)
            assert settings.warn_label["text"], "no warning about a short pulse"
            settings._set("freq_hz", 20)
            settings._set("duration_s", 0.4, warn=True)
            assert not settings.warn_label["text"], settings.warn_label["text"]
        step("a pulse shorter than two periods is called out", warn)

        def language():
            settings._change_language("en")
            root.update()
            time.sleep(0.3)
            assert settings.win is not None and settings.win.winfo_exists(), \
                "the window did not survive the switch"
            assert "peakers" in settings.status_line["text"], \
                settings.status_line["text"]
            settings._change_language("cs")
            root.update()
            assert "eproduktory" in settings.status_line["text"], \
                settings.status_line["text"]
        step("the language can be switched with the window open", language)

        def one_notch():
            settings.win.geometry("700x420")
            root.update()
            time.sleep(0.4)
            settings.canvas.yview_moveto(0.0)
            root.update()
            before = settings.canvas.yview()[0]
            settings.win.event_generate("<MouseWheel>", delta=-120, x=200, y=200)
            root.update()
            return settings.canvas.yview()[0] - before

        def wheel():
            # The bug this guards against: a bind_all binding outlives the
            # window it was made for, so every reopening adds another handler
            # and one notch scrolls two lines, then three. Compared as a ratio,
            # so it does not depend on how tall one line is.
            first = one_notch()
            for _ in range(2):
                settings.close()
                settings.open()
                if BREAK_IT:
                    settings.canvas.bind_all("<MouseWheel>", settings._wheel,
                                             add="+")
            third = one_notch()
            assert first > 0, "the wheel does not scroll at all"
            assert abs(third - first) <= 0.2 * first, \
                f"one notch grew from {first:.4f} to {third:.4f}"
        step("the wheel scrolls the same after reopening", wheel)

        step("a pulse can be requested", settings._pulse_now)

        def pulse_bar():
            # The pulse is inaudible on purpose, so this bar is the only sign
            # the button gives that anything happened. The playing is faked
            # here - the engine thread is not running in the test, so nothing
            # makes a sound and the numbers are exact.
            settings._pulse_now()
            assert settings.anim is not None, "the bar is not being animated"
            assert len(settings.bars) == 2, f"{len(settings.bars)} bars"
            K.ENGINE.playing_from = time.monotonic() - 1.0
            K.ENGINE.playing_span = 2.0
            settings._animate()
            root.update()
            for bar in settings.bars:
                fraction, caption, _ = bar.shown
                assert 0.3 < fraction < 0.7, fraction
                assert "2,0" in caption or "2.0" in caption, caption

            # and once the pulse is over the loop has to stop by itself,
            # otherwise it would redraw 25 times a second all day
            K.ENGINE.playing_from = K.ENGINE.playing_span = 0.0
            settings.bar_full_until = settings.bar_wait_until = 0.0
            settings._animate()
            root.update()
            for bar in settings.bars:
                assert bar.shown[0] == 0.0 and bar.shown[1] == "", bar.shown
            assert settings.anim is None, "the animation runs on for nothing"
        step("the pulse bar fills and then stops on its own", pulse_bar)

        def tray_pulse():
            # a pulse asked for from the tray menu is the same pulse, so the
            # window's bar has to show it as well
            tray._after_pulse()
            assert settings.anim is not None, "a tray pulse never reaches the bar"
            settings.win.after_cancel(settings.anim)    # leave nothing running
            settings.anim = None
        step("a pulse from the tray shows on the bar too", tray_pulse)

        step("the tray menu builds", lambda: tray._menu())
        step("the tray survives having no running icon", tray.refresh)
        step("the device list can be reloaded", settings._rescan)

        def closes():
            settings._pulse_now()               # with the animation running
            assert settings.anim is not None
            settings.close()
            assert settings.anim is None, "a callback outlived the window"
        step("closes, and the animation with it", closes)
        step("closing twice is harmless", settings.close)

        def wrote_elsewhere():
            # Both halves matter for each file: it really was written (so the
            # writing path is covered) and it is not the file belonging to the
            # app the user has running.
            written = (K.LOG_PATH.read_text(encoding="utf-8")
                       if K.LOG_PATH.exists() else "")
            assert "Setting" in written, f"nothing logged to {K.LOG_PATH}"
            assert K.LOG_PATH != K.DATA / "keep_alive.log", str(K.LOG_PATH)
            assert K.CFG_PATH.exists(), f"nothing saved to {K.CFG_PATH}"
            assert K.CFG_PATH != K.DATA / "config.json", str(K.CFG_PATH)
        step("the run wrote its log and settings into its own files",
             wrote_elsewhere)
        root.destroy()

    root.after(600, run)
    root.mainloop()

    # put the settings back exactly as they were
    K.CFG.clear()
    K.CFG.update(json.loads(saved_config))
    K.save_cfg(K.CFG)
    K.texts.set_language(K.CFG.get("language", "cs"))

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) FAILED:")
        for problem in FAILED:
            print(f"  {problem}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
