"""
Installer and uninstaller for Da Keep Speakers Alive.

One program for both roles:
  no arguments   -> install
  --uninstall    -> uninstall (during installation this copy is saved into
                    the program folder as uninstall.exe)

What the installation does:
  1. copies the program into  C:\\Program Files\\Da Keep Speakers Alive
  2. creates a shortcut in the Start menu and on the desktop
  3. registers itself so it shows up in Settings -> Apps
  4. optionally sets up the logon task
Settings and the log stay in the user profile (%APPDATA%), so neither an
uninstall nor a reinstall loses them.

A hand-written installer instead of a ready-made tool (Inno Setup) because
nothing has to be installed to build it and we keep full control over what
gets written into the system.

Both languages come from windows/texts.py and the flags from windows/marks.py -
the SAME modules the app uses, not copies of them. Two copies would drift
apart, and one shared `missing()` test then covers the installer too.
PyInstaller finds the modules through --paths in build_installer.ps1.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import winreg
from pathlib import Path

# Running from source the modules sit in a sibling folder; inside the packaged
# .exe PyInstaller has already put them next to this one.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows"))
import marks
import texts
from texts import t as tx
from version import VERSION, PROJECT_URL

APP_NAME = "Da Keep Speakers Alive"
EXE_NAME = "DaKeepSpeakersAlive.exe"
REG_KEY = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
           r"\DaKeepSpeakersAlive")
# The task the app registers for "start at logon". It MUST match TASK_NAME in
# windows/keep_alive.py, or the uninstaller would leave the task behind and
# something would keep starting after the app is gone.
TASK_NAME = APP_NAME

# The mutex name the application holds. It MUST match the one in
# windows/keep_alive.py - when the two drift apart, the installer stops
# noticing a running app and reinstalls over it.
MUTEX_NAME = "DaKeepSpeakersAlive_single_instance"

# The uninstaller is a copy of this program left in the program folder. The
# name is a constant because three places have to agree on it: what gets
# copied, what UninstallString points at, and what is_uninstall recognises.
UNINSTALLER_NAME = "uninstall.exe"

# The same palette the settings window uses (keep_alive.py: BG / CARD / FG /
# DIM), so the installer and the app do not look like two different programs.
BACKGROUND = "#1b1f26"
CARD = "#151920"
TEXT = "#e6ebf2"
GREY = "#a9b4c2"          # deliberately not a darker grey - it has to be read
GREEN = "#22a050"
GREEN_LIGHT = "#7fd39b"   # the app's "everything is fine" colour
AMBER = "#ffb066"         # the app's "partly" colour
RED = "#b91c1c"
RED_LIGHT = "#ff9f9f"

TARGET_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / APP_NAME
STARTMENU = (Path(os.environ.get("ProgramData", r"C:\ProgramData"))
             / r"Microsoft\Windows\Start Menu\Programs" / f"{APP_NAME}.lnk")
# The desktop of all users - the installation is shared, so the shortcut
# belongs here, not only on the desktop of whoever happens to install it.
DESKTOP = (Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
           / f"{APP_NAME}.lnk")
# The app's settings and log. %APPDATA% is the profile of whoever RUNS this
# program - and an uninstall runs elevated, so that is the administrator's
# profile, not necessarily the user's (the same reason the chosen language
# lives in the registry, see stored_language). None when the variable is not
# set at all: a bare Path("") / APP_NAME would be a RELATIVE path and the
# deletion would hit whatever folder the installer happens to run from.
_appdata = os.environ.get("APPDATA", "")
DATA = Path(_appdata) / APP_NAME if _appdata else None

# Note: there is no Startup-folder shortcut to clean up here. This app
# deliberately never creates one (see CLAUDE.md, "no fallback through the
# Startup folder") - the scheduled task is the only autostart mechanism, so
# the uninstaller has nothing else to look for. Deleting a shortcut we never
# created would mean touching a file that belongs to someone else.


# ---------------------------------------------------------------- language

def system_language():
    """"cs" when Windows itself runs in Czech, otherwise English.

    Only the primary language matters (0x05 = Czech), so cs-CZ and any other
    Czech variant both count.
    """
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "cs" if (langid & 0x3FF) == 0x05 else "en"
    except OSError:
        # A missing UI language must not stop an installation - English is
        # the safer guess for a machine that cannot answer.
        return "en"


def stored_language():
    """The language picked during installation, or None.

    Kept in the registry rather than in the user's config.json: the
    uninstaller runs elevated, so %APPDATA% points at the ADMINISTRATOR's
    profile, not at the profile of whoever uses the app. The registry key is
    the same one the uninstall entry lives in, so it disappears with it.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallerLanguage")
            return value if value in dict(texts.LANGUAGES) else None
    except OSError:
        return None


def ship_language(code):
    """Hand the chosen language over to the application itself.

    The app builds its config.json out of config.default.json on first run
    (see load_cfg in keep_alive.py), so writing it there is what makes the app
    come up in the language picked here - no second mechanism needed.

    Returns False when it did not work, so the caller can report it instead
    of pretending everything went fine.
    """
    template = TARGET_DIR / "config.default.json"
    if not template.exists():
        return False
    try:
        # utf-8-sig on the way in for the same reason load_cfg() uses it: a
        # byte order mark would otherwise make json.loads refuse the file.
        # Written back WITHOUT one.
        settings = json.loads(template.read_text(encoding="utf-8-sig"))
        settings["language"] = code
        template.write_text(json.dumps(settings, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        return True
    except (OSError, ValueError):
        return False


def icon_source():
    """Path to the icon - inside the packaged program, or next to the sources."""
    if getattr(sys, "frozen", False):
        candidates = [Path(sys._MEIPASS) / "keep_alive.ico"]
    else:
        root = Path(__file__).resolve().parent.parent
        candidates = [root / "windows" / "icons" / "keep_alive.ico"]
    return next((c for c in candidates if c.exists()), None)


def set_icon(window):
    """Without this the window gets the default Tk icon (a feather)."""
    icon = icon_source()
    if icon:
        try:
            window.iconbitmap(default=str(icon))
        except tk.TclError:
            pass


def dark_titlebar(window):
    """A dark title bar, the same way the app does it.

    Without this a white title bar sits on top of a dark window. Attribute 20
    is DWMWA_USE_IMMERSIVE_DARK_MODE; on builds before 19041 it was 19.
    """
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        on = ctypes.c_int(1)
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(on), ctypes.sizeof(on))
    except Exception:
        pass        # cosmetic only - never worth failing an installation over


def centre(window):
    """Place the window in the middle of the screen - otherwise Windows puts
    it in the top left corner."""
    window.update_idletasks()
    width, height = window.winfo_width(), window.winfo_height()
    x = (window.winfo_screenwidth() - width) // 2
    y = (window.winfo_screenheight() - height) // 2
    window.geometry(f"+{x}+{y}")


def program_source():
    """The folder with the program - inside the installer, or next to it while
    debugging."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "program"
    return (Path(__file__).resolve().parent / "_build" / "dist"
            / "DaKeepSpeakersAlive")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def quiet(command):
    """Run a command without a console window and return (success, output)."""
    try:
        v = subprocess.run(command, shell=True, capture_output=True, text=True,
                           creationflags=0x08000000)   # CREATE_NO_WINDOW
        return v.returncode == 0, (v.stdout + v.stderr).strip()
    except OSError as e:
        return False, str(e)


def task_exists():
    """Is the logon task registered? Asked of the scheduler, never remembered."""
    ok, _ = quiet(f'schtasks /Query /TN "{TASK_NAME}"')
    return ok


def set_task_enabled(enabled):
    """Switch the logon task on or off without deleting it.

    Used to hold the scheduler off during an installation: the task is
    registered with "restart on failure" (3 attempts, one minute apart - see
    autostart_set in keep_alive.py), and taskkill counts as a failure. Left
    alone, the scheduler starts the OLD copy again a minute later, out of the
    very folder being overwritten. Measured on this machine on 19.08.2026: a
    killed instance came back on its own.
    """
    switch = "ENABLE" if enabled else "DISABLE"
    quiet(f'schtasks /Change /TN "{TASK_NAME}" /{switch}')


def data_belongs_to_someone_else():
    """True when %APPDATA% is NOT the profile of the person at the keyboard.

    Happens when the installation is elevated with a different administrator
    account: the settings then live in the user's profile, while this process
    only sees the administrator's. Deleting "the settings" in that state
    silently deletes nothing - so the uninstaller has to say so instead of
    reporting success.
    """
    ok, output = quiet('powershell -NoProfile -Command '
                       '"(Get-CimInstance Win32_ComputerSystem).UserName"')
    if not ok or not output:
        return False        # cannot tell - do not invent a problem
    interactive = output.strip().split("\\")[-1].lower()
    return interactive != os.environ.get("USERNAME", "").lower()


def other_instance_running():
    """Is the app running from somewhere else (from source through pythonw)?

    taskkill will not stop such an instance (it is called pythonw.exe), so
    after the installation two would run and the new one would quit right
    away with "already running". It is recognised by the lock the app holds.
    """
    k32 = ctypes.windll.kernel32
    k32.OpenMutexW.restype = ctypes.c_void_p
    h = k32.OpenMutexW(0x00100000, False, MUTEX_NAME)
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
        return True
    return False


def stop_running_app():
    """Stop the running application and WAIT until it really ends.

    taskkill returns immediately, but the process holds the files for a while
    longer. Without waiting, deleting the old folder fails - and an ignored
    failure like that only surfaces a step later, while copying.

    Returns False when something is STILL running afterwards. That really
    happens: a copy started from source can have an empty command line in
    Win32_Process (measured on 19.08.2026 - a process started hours earlier
    showed no command line at all), and the search below then misses it.
    Killing every pythonw.exe instead is not an option - other people's Python
    programs run on the same machine. So the honest answer is to say it did
    not work and let the caller report it.
    """
    quiet(f'taskkill /F /IM {EXE_NAME}')

    # The app can also run from source - the process is then called
    # pythonw.exe and taskkill by name misses it. So it is looked up by the
    # command line, to hit only our script and no other Python.
    quiet('powershell -NoProfile -Command "Get-CimInstance Win32_Process '
          '-Filter \'Name=\'\'pythonw.exe\'\' or Name=\'\'python.exe\'\'\' | '
          'Where-Object { $_.CommandLine -like \'*keep_alive.py*\' } | '
          'ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"')

    # The mutex is what decides, not the process list: it is held by whatever
    # instance is running, whether or not its command line can be read.
    for _ in range(20):                      # at most 5 seconds
        _, output = quiet(f'tasklist /FI "IMAGENAME eq {EXE_NAME}" /NH')
        if EXE_NAME not in output and not other_instance_running():
            return True
        time.sleep(0.25)
    return False


def delete_folder(path):
    """Delete a folder including files marked read-only.

    onexc, not the older onerror: onerror has been deprecated since Python
    3.12 and using it raises a DeprecationWarning, which this project does not
    silence. (Checked on 3.14.4 - onerror is still there, so this is about not
    building on something already on its way out.)
    """
    def on_error(function, name, _exception):
        try:
            os.chmod(name, 0o700)
            function(name)
        except OSError:
            pass          # reported by the caller, which checks the result
    shutil.rmtree(path, onexc=on_error)


def create_shortcut(where, target, icon):
    """Create a shortcut (.lnk).

    Paths go into PowerShell in SINGLE quotes - the whole command is already
    inside double ones, so another double quote would end it early and the
    shortcut would silently not be created.
    """
    ps = (f"$w=New-Object -ComObject WScript.Shell;"
          f"$s=$w.CreateShortcut('{where}');"
          f"$s.TargetPath='{target}';"
          f"$s.WorkingDirectory='{Path(target).parent}';"
          f"$s.IconLocation='{icon}';"
          f"$s.Description='Keeps the speakers awake with a short inaudible "
          f"pulse';"
          f"$s.Save()")
    ok, output = quiet(f'powershell -NoProfile -ExecutionPolicy Bypass '
                       f'-Command "{ps}"')
    return ok and Path(where).exists()    # verify the file really appeared


def relaunch_from_temp():
    """Copy the uninstaller into a temp folder and run it from there.

    Without this the uninstaller runs FROM the folder it is supposed to
    delete, so it cannot delete it and would have to do it through a deferred
    command after it ends - which is unreliable (in the sister project it once
    left 977 files behind). This way it deletes a folder it is not running
    from, right away, and can VERIFY the result.

    Returns True when it has moved (the caller should end).
    """
    if not getattr(sys, "frozen", False) or "--from-temp" in sys.argv:
        return False
    exe = Path(sys.executable)
    if TARGET_DIR not in exe.parents:  # not running from the program folder
        return False
    try:
        copy = Path(tempfile.gettempdir()) / "DaKeepSpeakersAlive-uninstall.exe"
        shutil.copy2(exe, copy)
        subprocess.Popen([str(copy), "--uninstall", "--from-temp"])
        return True
    except OSError:
        return False        # better to try uninstalling from here than not at all


# ---------------------------------------------------------------- install

def install(task, start_menu, desktop, report):
    """Install, with the scheduler held off for the duration.

    The task has to be disabled BEFORE the running app is killed, or it starts
    the old copy again a minute later, out of the folder being overwritten.
    _install() ends by registering or removing the task according to the
    user's choice, which clears the disabled state either way; this wrapper is
    only here so a failure halfway through cannot leave a disabled task behind
    - a task that exists but never runs is the kind of fault nobody finds.
    """
    had_task = task_exists()
    if had_task:
        set_task_enabled(False)
    try:
        return _install(task, start_menu, desktop, report)
    except BaseException:
        if had_task and task_exists():
            set_task_enabled(True)
        raise


def _install(task, start_menu, desktop, report):
    report(tx("ins_stopping"))
    # The result is NOT ignored: when the old copy keeps running, the new one
    # quits at startup with "already running" and the user is left with the
    # old version believing they upgraded. The installation still goes on -
    # the files usually do get copied - but it says so at the end.
    stopped = stop_running_app()

    report(tx("ins_copying"))
    if TARGET_DIR.exists():
        try:
            delete_folder(TARGET_DIR)
        except OSError:
            pass          # leftovers get overwritten by the copy below
    # dirs_exist_ok: should anything survive from an old installation (a
    # locked file, say), it is overwritten instead of failing the whole
    # installation
    shutil.copytree(program_source(), TARGET_DIR, dirs_exist_ok=True)

    # the uninstaller = a copy of this program
    if getattr(sys, "frozen", False):
        shutil.copy2(sys.executable, TARGET_DIR / UNINSTALLER_NAME)

    exe = TARGET_DIR / EXE_NAME
    problems = []
    if not stopped:
        problems.append(tx("ins_prob_running"))
    if not exe.exists():
        raise RuntimeError(tx("ins_err_copy"))

    # The app should come up in the language picked here, not in the one the
    # template happens to carry. When that fails the install is still usable,
    # so it goes on the list instead of stopping anything - but it must not
    # pass in silence, or the app comes up in the wrong language and the
    # installer claims everything went fine.
    if not ship_language(texts.language()):
        problems.append(tx("ins_prob_language"))

    if start_menu:
        report(tx("ins_startmenu"))
        if not create_shortcut(STARTMENU, exe, exe):
            problems.append(tx("ins_prob_startmenu"))
    else:
        try:
            STARTMENU.unlink(missing_ok=True)
        except OSError:
            pass

    if desktop:
        report(tx("ins_desktop"))
        if not create_shortcut(DESKTOP, exe, exe):
            problems.append(tx("ins_prob_desktop"))
    else:
        try:
            DESKTOP.unlink(missing_ok=True)
        except OSError:
            pass

    report(tx("ins_registry"))
    size = sum(f.stat().st_size for f in TARGET_DIR.rglob("*") if f.is_file())
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY) as k:
        for name, value in [
                ("DisplayName", APP_NAME),
                ("DisplayVersion", VERSION),
                ("Publisher", "David Kral"),
                ("DisplayIcon", str(exe)),
                ("InstallLocation", str(TARGET_DIR)),
                ("UninstallString",
                 f'"{TARGET_DIR / UNINSTALLER_NAME}" --uninstall'),
                ("URLInfoAbout", PROJECT_URL),
                # not a Windows value - it is how the uninstaller knows which
                # language to speak when it runs a year from now
                ("InstallerLanguage", texts.language())]:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, size // 1024)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)

    # The task is created by the application itself (the --autostart-on
    # switch). Why: its window and tray menu can do the same, and if these
    # were two pieces of code they would drift apart sooner or later.
    report(tx("ins_task_on") if task else tx("ins_task_off"))
    quiet(f'"{exe}" ' + ("--autostart-on" if task else "--autostart-off"))
    # The return code is not what decides - the scheduler is asked below,
    # in the final check. Reporting a failure here would be pointless anyway:
    # the next report() overwrites the line before anyone can read it.

    # The final check - the REAL result is verified, not that the commands
    # finished. The installer must not report success when something is
    # missing.
    report(tx("ins_checking"))
    if not exe.exists():
        problems.append(tx("ins_prob_program"))
    if not (TARGET_DIR / UNINSTALLER_NAME).exists() \
            and getattr(sys, "frozen", False):
        problems.append(tx("ins_prob_uninstaller"))
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY) as k:
            winreg.QueryValueEx(k, "DisplayName")
    except OSError:
        problems.append(tx("ins_prob_registry"))
    # BOTH directions are checked. Only "on" used to be: a failed switch-off
    # left the app starting at every logon while the installer said it had
    # been turned off - and the user has no way of noticing until it starts.
    if task_exists() != bool(task):
        problems.append(tx("ins_prob_task" if task else "ins_prob_task_off"))

    if problems:
        report(tx("ins_failed", what=", ".join(problems)))
        return False
    report(tx("ins_done"))
    return True


# ---------------------------------------------------------------- uninstall

def uninstall(delete_data, report):
    # Deleting the program folder needs no deferred command: relaunch_from_temp
    # has already moved this program out of the folder, so it can delete it
    # right here and CHECK the result. If that move ever fails, the deletion
    # below fails honestly and is reported - it is not papered over.
    #
    # MIND the order: the task goes BEFORE the app is stopped. The task is
    # registered with "restart on failure", so if the app were killed first,
    # the scheduler would start it again a minute later - and it would
    # recreate the data folder being deleted right now.
    report(tx("ins_task_off"))
    quiet(f'schtasks /Delete /F /TN "{TASK_NAME}"')
    # Asked, not assumed. A task left behind keeps trying to start a program
    # that no longer exists, at every logon, for ever - and "Uninstalled,
    # thanks for trying it" would be the last thing the user was told.
    task_left = task_exists()

    report(tx("ins_stopping"))
    # Same reason as in install(): an app that keeps running holds its files,
    # so the folder below will not delete. Saying "the program folder is left
    # over" without saying why would send the user looking in the wrong place.
    stopped = stop_running_app()

    report(tx("uni_shortcuts"))
    for lnk in (STARTMENU, DESKTOP):
        try:
            lnk.unlink(missing_ok=True)
        except OSError:
            pass

    report(tx("uni_registry"))
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY)
    except FileNotFoundError:
        pass

    left = []
    if task_left:
        left.append(tx("uni_prob_task"))
    if delete_data:
        report(tx("uni_data"))
        if DATA is None or data_belongs_to_someone_else():
            # Deleting nothing and calling it done is the worst outcome: the
            # user asked for their settings to go and would never learn they
            # are still there.
            left.append(tx("uni_prob_data_elsewhere"))
        else:
            for attempt in range(3):
                try:
                    delete_folder(DATA)
                except OSError:
                    pass
                if not DATA.exists():
                    break
                time.sleep(1)
            if DATA.exists():
                # must not fail silently - show what stayed and why
                left += [f.name for f in DATA.iterdir()]

    report(tx("uni_files"))
    for attempt in range(6):
        try:
            delete_folder(TARGET_DIR)
        except OSError:
            pass
        if not TARGET_DIR.exists():
            break
        time.sleep(1)
    if TARGET_DIR.exists():
        left.append(tx("uni_prob_files"))
        if not stopped:
            left.append(tx("ins_prob_running"))
    if left:
        report(tx("uni_partial", what=", ".join(left[:4])))
        return False
    report(tx("ins_done"))
    return True


# ---------------------------------------------------------------- window

def switch_row(parent, text, variable):
    """A checkbox row - the mark is DRAWN, not left to Tk.

    Tk's own checkbox is a few pixels of white and looks sloppy next to the
    app, which draws its marks by hand. Both now use the same drawing
    (marks.py), so the installer and the app cannot end up looking different.

    The whole row is clickable, not just the little square.
    """
    row = tk.Frame(parent, bg=BACKGROUND, cursor="hand2")
    row.pack(anchor="w", pady=2, fill="x")
    canvas = tk.Canvas(row, width=marks.SIZE, height=marks.SIZE,
                       bg=BACKGROUND, highlightthickness=0, cursor="hand2")
    canvas.pack(side="left", padx=(0, 9))
    label = tk.Label(row, text=text, bg=BACKGROUND, fg=TEXT,
                     font=("Segoe UI", 10), cursor="hand2", justify="left")
    label.pack(side="left")

    # kept on the row, so it dies with the row - a language switch throws
    # these widgets away and rebuilds them
    row.hovered = False

    def redraw():
        marks.draw(canvas, variable.get(), False, row.hovered)

    def toggle(_=None):
        variable.set(not variable.get())
        redraw()

    def hover(state):
        row.hovered = state
        redraw()

    for widget in (row, canvas, label):
        widget.bind("<Button-1>", toggle)
        widget.bind("<Enter>", lambda e=None: hover(True))
        widget.bind("<Leave>", lambda e=None: hover(False))
    redraw()
    return row


class Window:
    def __init__(self, uninstalling):
        self.uninstalling = uninstalling
        self.result = None        # None = the user closed it without acting
        self.clean = True
        # The last line reported - it is what says WHAT was left behind. This
        # window closes before the result window opens, so without carrying it
        # over the user would be told to look at a window that is gone.
        self.last_message = ""
        # True while installing or uninstalling - everything that could
        # interrupt the work is refused for that time
        self.busy = False
        self.r = tk.Tk()
        self.r.configure(bg=BACKGROUND)
        self.r.resizable(False, False)
        set_icon(self.r)

        # These live on the window, NOT inside _build: the contents are
        # thrown away on a language switch, and a choice made before it must
        # not be thrown away with them.
        self.start_menu = tk.BooleanVar(value=True)
        self.desktop = tk.BooleanVar(value=True)
        self.option = tk.BooleanVar(value=not uninstalling)

        self._build()
        dark_titlebar(self.r)

    def _build(self):
        """Build the contents - and build them AGAIN after a language switch.

        Rebuilding beats relabelling for the same reason the app does it
        (keep_alive.py): relabelling means keeping a reference to every
        widget, and sooner or later one is forgotten and stays in the old
        language.
        """
        for child in self.r.winfo_children():
            child.destroy()
        self.r.title(tx("ins_title_uninstall" if self.uninstalling
                        else "ins_title_install", app=APP_NAME))

        frame = tk.Frame(self.r, bg=BACKGROUND, padx=26, pady=22)
        frame.pack()

        header = tk.Frame(frame, bg=BACKGROUND)
        header.pack(fill="x")
        tk.Label(header, text=APP_NAME, bg=BACKGROUND, fg=TEXT,
                 font=("Segoe UI", 17, "bold")).pack(side="left")
        # the same flags as the app, out of marks.py - see LanguageFlags
        marks.LanguageFlags(header, self._change_language, TEXT).pack(
            side="right")

        self._text(frame, tx("ins_subtitle"), 10, GREY, pady=(2, 14))

        card = tk.Frame(frame, bg=CARD, padx=16, pady=14)
        card.pack(fill="x")
        self._text(card, tx("ins_from_folder" if self.uninstalling
                            else "ins_to_folder"), 10, TEXT)
        self._text(card, f"   {TARGET_DIR}", 10, GREEN_LIGHT, pady=(2, 0))

        self.options_frame = tk.Frame(frame, bg=BACKGROUND)
        self.options_frame.pack(fill="x")

        tk.Frame(self.options_frame, bg=BACKGROUND, height=4).pack()
        if self.uninstalling:
            self._switch(tx("uni_opt_data"), self.option)
        else:
            self._switch(tx("ins_opt_startmenu"), self.start_menu)
            self._switch(tx("ins_opt_desktop"), self.desktop)
            self._switch(tx("ins_opt_autostart"), self.option)

        # wraplength: a long error message wraps instead of being cut off by
        # the window (WinError messages tend to be long)
        self.status = tk.Label(frame, text="", bg=BACKGROUND, fg=GREY,
                               font=("Segoe UI", 9), justify="left",
                               wraplength=440, anchor="w")
        self.status.pack(anchor="w", pady=(8, 10))

        row = tk.Frame(frame, bg=BACKGROUND)
        row.pack(fill="x")
        self.button = tk.Button(
            row, text=tx("ins_btn_uninstall") if self.uninstalling
            else tx("ins_btn_install"),
            command=self.run, bg=RED if self.uninstalling else GREEN,
            fg="white", font=("Segoe UI", 11), relief="flat",
            padx=22, pady=8, cursor="hand2")
        self.button.pack(side="left")
        # kept on self: it has to be disabled while the work runs. Closing the
        # window mid-copy destroys it, the next report() then dies on a
        # TclError, and a --windowed build shows nothing at all - leaving half
        # an installation in Program Files and no registry entry.
        self.close_button = tk.Button(
            row, text=tx("ins_btn_close"), command=self.r.destroy,
            bg=CARD, fg=TEXT, font=("Segoe UI", 11), relief="flat",
            padx=18, pady=8, cursor="hand2")
        self.close_button.pack(side="right")
        centre(self.r)

    def _switch(self, text, variable):
        return switch_row(self.options_frame, text, variable)

    def _change_language(self, code):
        # Not while it runs: _build() throws the widgets away and puts back an
        # ENABLED install button, so the whole thing could be started a second
        # time on top of itself.
        if self.busy or code == texts.language():
            return
        texts.set_language(code)
        self._build()

    def _text(self, parent, s, size, color, bold=False, pady=(0, 0),
              anchor="w"):
        label = tk.Label(parent, text=s, bg=parent["bg"], fg=color,
                         justify="left", wraplength=430,
                         font=("Segoe UI", size,
                               "bold" if bold else "normal"))
        label.pack(anchor=anchor, pady=pady)
        return label

    def report(self, text):
        self.last_message = text
        self.status.config(text=text)
        self.r.update()

    def run(self):
        # Every way out is closed for the duration: the button, the Close
        # button and the window's own X. report() calls update(), so clicks
        # ARE delivered while the work runs - this is not theoretical.
        self.busy = True
        self.button.config(state="disabled")
        self.close_button.config(state="disabled")
        self.r.protocol("WM_DELETE_WINDOW", lambda: None)
        try:
            if self.uninstalling:
                self.clean = uninstall(self.option.get(), self.report)
            else:
                ok = install(self.option.get(), self.start_menu.get(),
                             self.desktop.get(), self.report)
                if not ok:
                    self.status.config(fg=RED_LIGHT)
                    return
            self.result = True
            self.r.destroy()
        except (OSError, RuntimeError, shutil.Error, tk.TclError) as e:
            self.status.config(text=tx("ins_error", error=e), fg=RED_LIGHT)
        finally:
            # ... and opened again, whatever happened - otherwise a failed run
            # leaves a window that cannot even be closed. On the successful
            # path the window is already destroyed, and Tk answers even
            # winfo_exists with an error once that has happened - hence the
            # catch rather than a check.
            self.busy = False
            try:
                self.button.config(state="normal")
                self.close_button.config(state="normal")
                self.r.protocol("WM_DELETE_WINDOW", self.r.destroy)
            except tk.TclError:
                pass          # the window is gone, there is nothing to re-enable


def is_uninstall(argv, file_name):
    """Should the program behave as the uninstaller?

    Either the argument OR the file name decides. The name is here because
    uninstalling from Windows Settings does pass the argument, but when the
    user runs uninstall.exe by double-clicking it, no argument arrives - and
    without this check the INSTALLATION would start (and fail, because it runs
    from the very folder it would be overwriting).
    """
    name = Path(file_name).name.lower()
    return "--uninstall" in argv or name.startswith("uninstall")


# ------------------------------------------------------- result window

class ResultWindow:
    """A second, SEPARATE window with the result and the next steps.

    A new window is opened on purpose instead of swapping the contents of the
    first one: a new window flashes in the taskbar, so the user notices it
    even while doing something else in the meantime.
    """

    def __init__(self, uninstalling, all_ok, detail=""):
        self.uninstalling = uninstalling
        self.r = tk.Tk()
        self.r.title(tx("ins_title_uninstall" if uninstalling
                        else "ins_title_install", app=APP_NAME))
        self.r.configure(bg=BACKGROUND)
        self.r.resizable(False, False)

        frame = tk.Frame(self.r, bg=BACKGROUND, padx=26, pady=22)
        frame.pack()

        # No language chooser here on purpose - by this point the work is
        # done and the language was settled in the first window.
        heading = tx("ins_head_uninstalled" if uninstalling
                     else "ins_head_installed")
        tk.Label(frame, text=heading, bg=BACKGROUND,
                 fg=GREEN_LIGHT if all_ok else AMBER,
                 font=("Segoe UI", 17, "bold")).pack(anchor="w")

        if uninstalling:
            description = tx("uni_ok_desc" if all_ok else "uni_partial_desc",
                             app=APP_NAME)
        else:
            description = tx("ins_ok_desc")
        tk.Label(frame, text=description, bg=BACKGROUND, fg=GREY,
                 justify="left", wraplength=430,
                 font=("Segoe UI", 10)).pack(anchor="w",
                                             pady=(6, 4 if detail else 14))

        # WHAT was left behind, in the colour of the heading it explains -
        # not as another grey line nobody reads. Only when there is something
        # to say, so a clean run has no empty gap here.
        if detail:
            tk.Label(frame, text=detail, bg=BACKGROUND, fg=AMBER,
                     justify="left", wraplength=430,
                     font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))

        self.launch = tk.BooleanVar(value=not uninstalling)
        self.manual = tk.BooleanVar(value=False)
        if not uninstalling:
            for text, variable in [(tx("ins_opt_launch", app=APP_NAME),
                                    self.launch),
                                   (tx("ins_opt_manual"), self.manual)]:
                switch_row(frame, text, variable)

        tk.Button(frame, text=tx("ins_btn_finish"), command=self.finish,
                  bg=GREEN, fg="white", font=("Segoe UI", 11), relief="flat",
                  padx=22, pady=8, cursor="hand2").pack(anchor="e",
                                                        pady=(16, 0))

        set_icon(self.r)
        centre(self.r)
        dark_titlebar(self.r)
        self.flash()

    def flash(self):
        """Flash the taskbar button when the window does not get focus."""
        try:
            hwnd = (ctypes.windll.user32.GetParent(self.r.winfo_id())
                    or self.r.winfo_id())
            struct = ctypes.c_uint * 5    # FLASHWINFO
            info = struct(ctypes.sizeof(struct), hwnd, 0x0000000C, 5, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass

    def finish(self):
        if not self.uninstalling:
            if self.manual.get():
                # Both manuals are shipped, so the language decides which one
                # opens. A bare *INFO*.txt would be a coin toss between the two.
                patterns = (["*INFO-READ*.txt", "*INFO*.txt"]
                            if texts.language() == "en"
                            else ["*INFO-CTI*.txt", "*INFO*.txt"])
                manual = next((m for p in patterns
                               for m in TARGET_DIR.glob(p)), None)
                if manual:
                    os.startfile(manual)
            if self.launch.get():
                if other_instance_running():
                    ctypes.windll.user32.MessageBoxW(
                        0, tx("ins_msg_running"), APP_NAME, 0x40)
                else:
                    subprocess.Popen([str(TARGET_DIR / EXE_NAME)])
        self.r.destroy()


def main():
    uninstalling = is_uninstall(sys.argv, sys.executable)

    # What language to open in: the one chosen when installing (the
    # uninstaller runs long after and nobody picks it again), otherwise the
    # language of Windows itself. Either way the flags in the window win.
    texts.set_language(stored_language() or system_language())

    if not is_admin():
        ctypes.windll.user32.MessageBoxW(
            0, tx("ins_msg_admin"), APP_NAME, 0x10)
        return 1
    if uninstalling and relaunch_from_temp():
        return 0            # the copy in the temp folder took over

    first = Window(uninstalling)
    first.r.mainloop()          # the first window closes once the work is done
    if first.result:
        # the detail travels only when something went wrong - on a clean run
        # the last message is just "Done."
        ResultWindow(uninstalling, first.clean,
                     "" if first.clean else first.last_message).r.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
