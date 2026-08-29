"""Drives the settings window through the branches a normal run never hits.

Switching the language, ticking a device, a pause that expires, closing the
window twice - all of it works or breaks in front of the user, and none of it
is covered by test_logic.py. The window is really created here (a Tk window
does flash up), only nothing is clicked by hand.

Run before every release:

    .venv\\Scripts\\python.exe tests\\test_window.py

    ... --break-it     deliberately re-introduces five bugs the app really
                       shipped with, to prove the checks for them can fail:
                       a pulse bar that never moves, a tray missing the
                       "partial" state, a tray label written out by hand
                       instead of translated, a card with a hole under it,
                       and a mouse wheel binding that piles up. The run has
                       to end with several FAILs and a non-zero exit code.

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
        # the tray as it was before 20.08.2026: four states out of five, so
        # "partial" threw a KeyError and the icon froze for good
        K.COLORS.pop("partial", None)
        # one tray label written out by hand instead of looked up - the menu
        # still builds, still has functions for labels, and still opens; only
        # that one item is stuck in Czech for ever
        _tx = K.tx
        K.tx = lambda key, **kw: ("Ukončit aplikaci" if key == "tray_quit"
                                  else _tx(key, **kw))
        # a card with a hole under it - what the grid layout did before
        # 22.08.2026, when a short card left the height of the taller one
        # beside it as empty space
        _relayout = K.Settings._relayout

        def gappy(self, event=None):
            _relayout(self, event)
            if self.cards:
                self.cards[0].pack_configure(pady=(0, 200))
        K.Settings._relayout = gappy
    saved_config = json.dumps(dict(K.CFG))
    # Every check that asks the engine for its state would otherwise depend on
    # the user's own main switch: state() answers "off" before it looks at
    # anything else, so with "Keep the speakers awake" unticked the pause step
    # below fails for a reason that has nothing to do with the window.
    K.CFG["active"] = True
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

        def bar_speaks_up_when_nothing_played():
            """A pulse with nowhere to go must still be visible.

            With no device ticked - or every ticked device unplugged - the
            pulse takes zero seconds, so the bar had nothing to draw and said
            nothing at all: three seconds of blank and then an empty track.
            The pulse is inaudible by design, so that is a button which does
            nothing whatsoever as far as the user can tell, and both manuals
            promise this bar turns red instead.
            """
            saved_items, saved_partly = list(K.ENGINE.error_items), K.ENGINE.partly
            saved_count = K.ENGINE.count
            try:
                settings._start_bar(3.0)            # asked for, not begun yet
                # what a pulse with nothing to play on leaves behind
                K.ENGINE.playing_from = K.ENGINE.playing_span = 0.0
                K.ENGINE.error_items = [("err_no_device", {})]
                K.ENGINE.partly = False
                K.ENGINE.count = saved_count + 1
                settings._animate()
                root.update()
                for bar in settings.bars:
                    fraction, caption, colour = bar.shown
                    assert caption, "the bar says nothing about a failed pulse"
                    assert colour == K.STATE_COLOUR["error"], colour
            finally:
                K.ENGINE.error_items, K.ENGINE.partly = saved_items, saved_partly
                K.ENGINE.count = saved_count
                settings.bar_full_until = settings.bar_wait_until = 0.0
                if settings.anim is not None:
                    settings.win.after_cancel(settings.anim)
                    settings.anim = None
        step("a pulse that played nothing still shows on the bar",
             bar_speaks_up_when_nothing_played)

        def tray_pulse():
            # a pulse asked for from the tray menu is the same pulse, so the
            # window's bar has to show it as well
            tray._after_pulse()
            assert settings.anim is not None, "a tray pulse never reaches the bar"
            settings.win.after_cancel(settings.anim)    # leave nothing running
            settings.anim = None
        step("a pulse from the tray shows on the bar too", tray_pulse)

        def tray_menu_follows_the_language():
            """The menu is built ONCE - it has to follow a language switch.

            Its labels are functions so that pystray asks for them each time
            the menu is opened. But "is the label a function?" tests nothing:
            pystray wraps a hard-coded string into a function just the same
            (measured 20.08.2026 - callable() on the raw attribute of an item
            made from a plain string is True as well). The only question worth
            asking is the behaviour: does the SAME menu say something else
            afterwards?

            Nothing else covers this. The menu is a pile of lambdas that is
            only visible on a right click, so a half-translated one would sit
            there unnoticed.
            """
            def labels():
                out = []
                for item in tray.icon.menu:
                    if item is K.pystray.Menu.SEPARATOR:
                        continue        # '- - - -' in every language
                    out.append(item.text)
                    out += [sub.text for sub in (item.submenu or [])]
                return out

            was = K.texts.language()
            try:
                K.texts.set_language("cs")
                czech = labels()
                K.texts.set_language("en")
                english = labels()
                assert czech, "the menu has no labels at all"
                assert len(czech) == len(english), \
                    f"{len(czech)} items in Czech, {len(english)} in English"
                # every one of them, not just the first: a menu where one item
                # stayed behind is exactly what this exists to catch
                stuck = [c for c, e in zip(czech, english) if c == e]
                assert not stuck, f"stayed in the old language: {stuck}"
            finally:
                K.texts.set_language(was)
        step("the tray menu follows a language switch",
             tray_menu_follows_the_language)
        step("the tray survives having no running icon", tray.refresh)

        def tray_every_state():
            """Every state ENGINE.state() can return, through the tray.

            The engine thread never runs in this test, so on its own the tray
            only ever sees "ok" - which is how a missing "partial" entry got
            past both test files and froze the icon for good in exactly the
            case reported from real use (the default output played, while
            another picked output was unplugged).
            """
            was = (list(K.ENGINE.error_items), K.ENGINE.partly, dict(K.CFG))
            try:
                # Mechanical, so a SIXTH state added one day cannot be put in
                # one table and forgotten in the other. A hand-written list
                # only ever covers what somebody remembered to write down.
                assert set(K.COLORS) == set(K.STATE_COLOUR), (
                    "the two colour tables disagree: "
                    f"{set(K.COLORS) ^ set(K.STATE_COLOUR)}")
                for want, error, partly, active in [
                        ("ok", [], False, True),
                        ("partial", [("err_play", {"name": "S", "error": "x"})],
                         True, True),
                        ("error", [("err_play", {"name": "S", "error": "x"})],
                         False, True),
                        ("off", [], False, False)]:
                    K.ENGINE.error_items, K.ENGINE.partly = error, partly
                    K.CFG["active"] = active
                    assert K.ENGINE.state() == want, K.ENGINE.state()
                    tray._signature = None          # force a real repaint
                    tray.refresh()
                    # refresh() only records the state once the repaint really
                    # went through, so this covers the tooltip AND the icon:
                    # a key missing from either table leaves it unchanged.
                    assert tray.state == want, f"{want} never reached the tray"

                # "paused" is not an error state, so it needs its own lever -
                # and it was the state the loop above could never produce.
                K.ENGINE.error_items, K.ENGINE.partly = [], False
                K.CFG["active"] = True
                K.ENGINE.pause(15)
                assert K.ENGINE.state() == "paused", K.ENGINE.state()
                tray._signature = None
                tray.refresh()
                assert tray.state == "paused", "paused never reached the tray"
            finally:
                K.ENGINE.pause(0)
                K.ENGINE.error_items, K.ENGINE.partly = was[0], was[1]
                K.CFG["active"] = was[2].get("active", True)
        step("the tray copes with every state, not just 'ok'", tray_every_state)
        step("the device list can be reloaded", settings._rescan)

        def texts_in_the_window():
            """Every label the window really carries, with its position."""
            found = []

            def walk(widget):
                for child in widget.winfo_children():
                    try:
                        text = child.cget("text")
                    except (tk.TclError, TypeError):
                        text = ""
                    if text:
                        found.append((child.winfo_rooty(), str(text)))
                    walk(child)
            walk(settings.win)
            return found

        def signal_card_in_order():
            """Frequency, length, volume - and the switch under the volume.

            The order is a decision, not a coincidence: the correction switch
            explains what the volume above it does, and a checkbox sitting
            under a drop-down it has nothing to do with reads as if it
            belonged to that one. Read off the built window rather than the
            source, so moving a line without meaning to shows up here.
            """
            wanted = [K.tx("lbl_freq"), K.tx("lbl_duration"), K.tx("lbl_amp"),
                      K.tx("sw_amp_correction")]
            placed = [(y, text) for y, text in texts_in_the_window()
                      if text in wanted]
            order = [text for _, text in sorted(placed)]
            assert order == wanted, order
            # and the explanation under it, or the switch is a riddle
            assert any(K.tx("sw_amp_correction_desc") in text
                       for _, text in texts_in_the_window()), \
                "the correction switch has no explanation under it"
        step("the signal card reads frequency, length, volume",
             signal_card_in_order)

        def the_log_can_be_opened():
            """The link under "write a log file" - both ways it can go.

            A link that quietly does nothing is the worst outcome here, and it
            is the likely one: a --windowed build has no console, so an
            exception from os.startfile would vanish without trace. Windows is
            stood in for, so no editor opens during a test run.
            """
            saved_start = K.os.startfile
            saved_problems = list(K.PROBLEMS)
            try:
                asked = []
                K.os.startfile = lambda path: asked.append(path)
                settings._open_log()
                assert asked == [K.LOG_PATH], asked

                def refuses(path):
                    raise OSError("pretend the log is not there yet")
                K.os.startfile = refuses
                settings._open_log()
                root.update()
                assert any(key == "warn_log_open" for key, _ in K.PROBLEMS), \
                    K.PROBLEMS
                assert K.tx("warn_log_open", path="x", error="y")[:20] and \
                    settings.problem_label["text"], \
                    "a log that will not open is never mentioned to the user"
            finally:
                K.os.startfile = saved_start
                K.PROBLEMS[:] = saved_problems
                settings._refresh_status()
        step("the log opens, and says so when it cannot",
             the_log_can_be_opened)

        def two_columns_without_gaps():
            """Wide window: the cards must sit right under one another.

            Until 22.08.2026 the cards were placed in a grid, and a grid row
            is as tall as the TALLER of its two cards - a short card left
            some two hundred pixels of empty space under itself while the
            tall one beside it filled the row. Measured, not eyeballed:
            preview.py is for looking, this is for catching a return of it.
            """
            was = settings.win.geometry()
            try:
                settings.win.geometry(f"{2 * K.Settings.CARD_WIDTH + 140}x900")
                # update(), not update_idletasks(): the canvas only learns its
                # new width once the resize has actually been handled, and
                # _relayout reads that width to decide on the second column
                settings.win.update()
                settings._relayout()
                settings.win.update()
                assert settings.columns == 2, f"{settings.columns} column(s)"
                for column in settings.column_frames:
                    inside = [c for c in settings.cards if c.master is column]
                    assert inside, "a column with no cards in it"
                    for above, below in zip(inside, inside[1:]):
                        gap = below.winfo_y() - (above.winfo_y()
                                                 + above.winfo_height())
                        assert gap <= 20, f"{gap} px of empty space under a card"
            finally:
                settings.win.geometry(was)
                settings.win.update_idletasks()
                settings._relayout()
        step("the cards stack tight in two columns", two_columns_without_gaps)

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
