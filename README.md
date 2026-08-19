# Da Keep Speakers Alive

Powered speakers switch themselves off after a few minutes of silence, and then
swallow the first second or two of whatever you play next — the start of a
video, the first word of a call, the beginning of a notification sound.

Da Keep Speakers Alive keeps them awake by sending them a **short tone so low
and so quiet that you cannot hear it**, once every few minutes.

Windows · Czech and English interface · Apache 2.0

---

## What makes it different

There are other programs for this, and the best of them is
[vrubleg/SoundKeeper](https://github.com/vrubleg/soundkeeper) — mature, tiny,
written in C++, and it also handles analog outputs. If it does what you need,
use it. This project exists because of two things it does not do:

| | SoundKeeper | Da Keep Speakers Alive |
|---|---|---|
| Settings | by renaming the .exe | a normal window |
| Which output the pulse goes to | the default one | **any outputs you pick**, one or several |
| The signal | a continuous tone | a **0.4 s burst** every few minutes |
| Language | — | Czech / English |

The **burst instead of a continuous tone** is the deliberate part. Modern
Standby (the sleep mode of every current Windows laptop) keeps the machine
partly awake while an audio stream is open, so a program that holds one open
all day is not free. Here the stream exists for 0.4 seconds out of every 180 —
the smallest thing that still does the job.

**Picking the output matters** as soon as a machine has more than one — and a
laptop on a dock, with a monitor and a USB audio interface attached, easily has
four. Usually only one of them falls asleep, and there is no reason to send
anything to the rest. You can also tick several at once, or follow the system
default and pick extra outputs on top of it.

---

## What the pulse actually is

A sine burst with soft edges — **20 Hz, 1 % of full scale (−40 dBFS), 0.4 s,
every 3 minutes** by default.

Those numbers are measured, not guessed. On the speakers this was built for
(Creative, mains-powered, on a USB dock), 20 Hz at 1 % was inaudible in a quiet
room, and a burst at **half** that level, repeated every 3 minutes for 20
minutes, kept them awake the whole time. The default is the louder of the two,
because the headroom costs nothing you can hear.

Everything is adjustable in the window: 5–100 Hz, 0.1–10 %, 0.1–2 s, every 30 s
to 15 minutes. Two details are worth knowing before you turn the knobs:

- **The edges are faded in and out.** Without that, the burst starts and ends
  on a step, and a step is broadband noise — a click you hear far better than
  the tone itself.
- **A burst shorter than two full waves is not a tone**, it is a DC step that
  the speaker's coupling capacitor eats. The window warns you when your
  combination of frequency and length falls under that line.

**If you hear crackling**, lower the volume first: a small speaker asked for
20–60 Hz at 10 % is being asked for more excursion than it has. The signal
itself has been checked — no clipping, no discontinuity, no buffer underrun —
so what is left is the analog end.

---

## How it runs

An icon next to the clock, and a settings window behind it.

- **Which speakers to keep awake** — the system default output, or outputs you
  pick by hand, or both. A device is remembered **by name**, not by index, so
  the choice survives replugging the USB into another port. One that is not
  currently connected stays in the list, marked as such.
- **How often** — 30 s to 15 minutes.
- **What the pulse sounds like** — frequency, volume, length, plus a
  **Try a pulse** button with a progress bar. The bar exists because the pulse
  is inaudible on purpose: without it, a working app and a broken one look
  exactly the same.
- **Start when I log in to Windows** — registers a task in Task Scheduler.
- **Pause for a while** — for when you need real silence, recording audio, say.
  It switches itself back on afterwards.
- **Czech / English**, switched live.

It **cannot be a Windows service.** Services run in session 0, where audio does
not physically play. It has to be a normal user process — which also means a
locked screen or a blanked monitor changes nothing, because neither ends your
session.

It does not keep the computer awake, and it cannot wake it up. A running
process has nothing to wake anything with: in hibernation it does not exist,
and under Modern Standby Windows freezes it. After the machine wakes up, the
overdue pulse goes out straight away.

---

## Running it

No installer is published yet — for now it runs from source:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
start.bat            # the icon appears next to the clock
start.bat --show     # and open the window right away
```

Needs Python 3.14 and Windows. The dependencies are `sounddevice` (PortAudio,
WASAPI), `numpy`, `pystray` and `Pillow`; `tkinter` comes with Python.

Run from source, the settings and the log sit next to the sources. An installed
copy will put them in `%APPDATA%\Da Keep Speakers Alive` instead.

Other switches: `--pulse` sends one pulse and quits, `--autostart-on` /
`--autostart-off` are for the installer.

Full instructions: [English manual](docs/___INFO-READ.txt) ·
[česky](docs/___INFO-CTI.txt)

---

## Development

```text
windows\keep_alive.py    the whole app: engine, tray icon, settings window
windows\texts.py         every text, Czech and English side by side
windows\marks.py         hand-drawn checkboxes (the Tk ones are tiny)
tools\tune.py            measuring: --list, --tone, --keepalive, --check
tests\                   see below
```

Before any release:

```powershell
.venv\Scripts\python.exe tests\test_logic.py     the pulse, devices, texts, settings file
.venv\Scripts\python.exe tests\test_window.py    branches normal use never reaches
.venv\Scripts\python.exe tests\preview.py        renders the window to PNG - then look at it
```

Both test files carry their own counter-cases: every check comes with a case
that must make it complain, because a check nobody ever tried to break reads
exactly like a check that does not work. `test_window.py --break-it` puts two
real, previously-shipped bugs back in and the run has to fail.

`tools\tune.py` is the measuring rig the defaults came out of — it lists the
outputs, plays a single tone so you can tell whether you hear it, runs a
keep-alive cycle for as long as you like, and plays a series of audible beeps
to check whether the speakers dropped any.

---

## Limitations

- **Windows only.** WASAPI, Task Scheduler and the tray icon are all
  Windows-specific.
- **Inaudible is not guaranteed.** It depends on your speakers and your room.
  If you can hear it, lower the volume or the frequency — that is what the
  settings are for.
- **No installer yet**, and when there is one it will be unsigned: SmartScreen
  will warn on first run.
- **Three minutes is known to be enough, not known to be the maximum.** Longer
  intervals were never tested.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
