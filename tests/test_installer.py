"""
Test of installing and uninstalling - it goes through the WHOLE cycle.

All targets are redirected into a temp folder and into an HKCU key, so the
test needs no administrator rights and never touches the real installation.
The code under test is the same one though - copying, shortcuts, the registry
entry, the final check and the cleanup during uninstallation.

Run:  py tests/test_installer.py
      (after installer\\build_installer.ps1 - without the built program there
      is nothing to copy and the test says so instead of passing silently)
"""

import json
import os
import subprocess
import sys
import tempfile
import shutil
import time
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "installer"))
import installer as I

TEMP_DIR = Path(os.environ.get("TEMP", tempfile.gettempdir())) / "dksa-install-test"
failures = []


def check(description, expected, actual):
    ok = expected == actual
    print(f"  {'OK ' if ok else 'FAIL'}  {description}: {actual}"
          + ("" if ok else f"   (expected {expected})"))
    if not ok:
        failures.append(description)


def refuse_if_the_app_is_running():
    """Do not run while the real app is up - the test would kill it.

    Steps 3 and 6 stop whatever holds the app's lock, and that is exactly what
    a copy the user started is doing. It happened once (19.08.2026): the run
    took down a session that had been up since 16:13 and deleted the scheduled
    task with it. Restarting it afterwards is not offered on purpose - the
    test cannot know how it was started (task, start.bat, installed .exe), and
    a promise it cannot keep is worse than a clear instruction.
    """
    if I.other_instance_running():
        print("REFUSED - Da Keep Speakers Alive is running right now.")
        print("  This test stops the running app and would take yours down")
        print("  with it. Quit it (tray icon -> Quit application), run this")
        print("  test, then start it again.")
        sys.exit(2)


def block_system_changes():
    """Let the test call the real code, but never let it change THIS machine.

    install() asks the app to register or remove the logon task, and the app
    uses one task name for everyone - so a test run deleted the user's real
    task (19.08.2026). Those two commands are recorded instead of run; every
    other command still goes through, because stopping processes and listing
    tasks is what steps 3 and 6 are actually testing.
    """
    real_quiet = I.quiet

    def guarded(command):
        if "--autostart" in command or command.startswith("schtasks"):
            blocked.append(command)
            # The scheduler's ANSWER is scripted, so the checks that read it
            # can be made to go both ways. Returning a flat "it worked" would
            # make ins_prob_task a check that can never go red - and a check
            # nobody can break is worse than no check at all.
            if command.startswith("schtasks /Query"):
                return pretend_task_exists[0], ""
            # The app's OWN exit code when it is asked to add or remove the
            # task. Scripted for the same reason: the task can be registered
            # and still be disabled, so "it is there" and "it will run" are
            # two different answers and both have to be forceable.
            if "--autostart" in command:
                return pretend_autostart_works[0], ""
            return True, ""
        return real_quiet(command)

    I.quiet = guarded


blocked = []
# what schtasks /Query answers; a list so the steps below can change it
pretend_task_exists = [False]
# whether the app managed to switch the logon task on or off
pretend_autostart_works = [True]


def prepare():
    """Redirect every target so the test never touches a real installation.

    The APPDATA variable is redirected as well - the packaged application uses
    it to decide where to store its settings and log. Without that the test
    would write into the real user profile (and make a mess there).
    """
    # Leftovers from a previous run may not delete right away (Windows holds
    # the libraries for a while), so we do not rely on it and only top the
    # folder up - exist_ok, not a hard mkdir.
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    I.TARGET_DIR = TEMP_DIR / "Program Files" / I.APP_NAME
    I.STARTMENU = TEMP_DIR / "Start Menu" / f"{I.APP_NAME}.lnk"
    I.DESKTOP = TEMP_DIR / "Desktop" / f"{I.APP_NAME}.lnk"
    I.DATA = TEMP_DIR / "AppData" / I.APP_NAME
    for p in (I.STARTMENU, I.DESKTOP, I.DATA):
        p.parent.mkdir(parents=True, exist_ok=True)
    I.DATA.mkdir(exist_ok=True)
    # registry: a test key in HKCU instead of HKLM (admin only)
    I.REG_KEY = r"Software\DaKeepSpeakersAlive-test"
    os.environ["APPDATA"] = str(TEMP_DIR / "AppData-profile")
    (TEMP_DIR / "AppData-profile").mkdir(parents=True, exist_ok=True)
    I._original_registry = winreg.HKEY_LOCAL_MACHINE
    winreg.HKEY_LOCAL_MACHINE = winreg.HKEY_CURRENT_USER


def cleanup():
    winreg.HKEY_LOCAL_MACHINE = I._original_registry
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                         r"Software\DaKeepSpeakersAlive-test")
    except OSError:
        pass          # already gone - step 5 removes it, that is the point
    # ignore_errors here and nowhere else: Windows holds the DLLs of a process
    # that has only just been killed, so the temp folder often will not delete
    # on the first try. Nothing depends on it being gone - the next run starts
    # by clearing it again - so failing the test over it would report a
    # problem that is not one. The checks above never use it.
    shutil.rmtree(TEMP_DIR, ignore_errors=True)


def report(text):
    print(f"       … {text}")


print("Test of installing and uninstalling")
print("=" * 60)
# Taken BEFORE anything runs, so step 11 can prove the real files were not
# touched. None when the file does not exist - which is also a valid "before".
_project = Path(__file__).resolve().parent.parent
_live_log = _project / "windows" / "keep_alive.log"
_live_cfg = _project / "windows" / "config.json"
production_log_stamp = _live_log.stat().st_mtime if _live_log.exists() else None
production_cfg_stamp = _live_cfg.stat().st_mtime if _live_cfg.exists() else None

refuse_if_the_app_is_running()
block_system_changes()
prepare()
try:
    if not I.program_source().exists():
        print("SKIPPED - run installer/build_installer.ps1 first")
        sys.exit(0)

    print("\n1) INSTALLATION with all options")
    # task=False: creating the scheduled task is a real change to the system,
    # and it is already covered through the switch in the application itself
    result = I.install(task=False, start_menu=True, desktop=True,
                       report=report)
    check("installation reported success", True, result)
    check("program copied", True, (I.TARGET_DIR / I.EXE_NAME).exists())
    check("default settings shipped", True,
          (I.TARGET_DIR / "config.default.json").exists())
    # The developer's own config.json holds THIS machine's device names and
    # window position - shipping it would hand them to every user. Looked for
    # anywhere under the target, not in one fixed spot: a check tied to one
    # folder would keep passing if it started being copied somewhere else.
    check("the developer's own config.json is NOT shipped", False,
          any(p.name == "config.json" for p in I.TARGET_DIR.rglob("*")))
    check("no log file shipped either", False,
          any(I.TARGET_DIR.rglob("*.log")))
    # Both manuals, not just the first one found - the result window opens the
    # one matching the language, so a missing Czech manual would only show up
    # as a button that does nothing.
    manuals = sorted(p.name for p in I.TARGET_DIR.glob("*INFO*.txt"))
    check("both manuals shipped", 2, len(manuals))
    check("the Czech one is there", True,
          any("CTI" in m for m in manuals))
    check("the English one is there", True,
          any("READ" in m for m in manuals))
    check("shortcut in the Start menu", True, I.STARTMENU.exists())
    check("shortcut on the desktop", True, I.DESKTOP.exists())
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, I.REG_KEY) as k:
            name = winreg.QueryValueEx(k, "DisplayName")[0]
            uninstall_cmd = winreg.QueryValueEx(k, "UninstallString")[0]
            size = winreg.QueryValueEx(k, "EstimatedSize")[0]
    except OSError as e:
        name, uninstall_cmd, size = f"error: {e}", "", 0
    check("entry in the list of applications", I.APP_NAME, name)
    check("uninstall command filled in", True, "--uninstall" in uninstall_cmd)
    check("size filled in (MB)", True, 10 < size / 1024 < 200)
    # The task is registered by the APP, not by the installer, so that one
    # piece of code owns it. The call is blocked here (it would change this
    # machine), but it still has to be made - and made through the installed
    # program, not some other copy.
    check("the app is the one asked to set the logon task", True,
          any("--autostart-off" in c and I.EXE_NAME in c for c in blocked))

    print("\n2) REPEATED INSTALLATION (over an existing one)")
    result = I.install(task=False, start_menu=True, desktop=True,
                       report=report)
    check("succeeds a second time as well", True, result)

    print("\n3) REINSTALL WHILE THE INSTALLED APP IS RUNNING")
    # Exactly this case fails in practice with "WinError 183: file already
    # exists" when taskkill is not waited out: it returns before the process
    # releases the files, deleting the old folder fails and the copy then does
    # not go through.
    running_exe = I.TARGET_DIR / I.EXE_NAME
    process = subprocess.Popen([str(running_exe), "--no-dialog",
                               "--quit-after", "60"])
    time.sleep(8)
    check("the app is running", None, process.poll())
    result = I.install(task=False, start_menu=True, desktop=True,
                       report=report)
    check("reinstall went through over the running app", True, result)
    check("the running app was stopped", True, process.poll() is not None)
    check("the program is in place", True, running_exe.exists())

    print("\n4) INSTALLATION WITHOUT SHORTCUTS (removes the existing ones)")
    result = I.install(task=False, start_menu=False, desktop=False,
                       report=report)
    check("succeeds", True, result)
    check("Start menu shortcut removed", False, I.STARTMENU.exists())
    check("desktop shortcut removed", False, I.DESKTOP.exists())

    print("\n5) UNINSTALL (keeping the settings)")
    (I.DATA / "config.json").write_text("{}", encoding="utf-8")
    result = I.uninstall(delete_data=False, report=report)
    check("uninstall reported success", True, result)
    check("program deleted", False, I.TARGET_DIR.exists())
    check("settings KEPT", True, (I.DATA / "config.json").exists())
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, I.REG_KEY).Close()
        entry = True
    except OSError:
        entry = False
    check("entry removed from the list of applications", False, entry)

    print("\n5b) A SHORTCUT THAT WILL NOT DELETE IS REPORTED, NOT SWALLOWED")
    # The check above only ever sees the happy path: the shortcut goes, so
    # "uninstalled" is true. Explorer or the search indexer holding a .lnk
    # open makes unlink fail, and that used to pass in silence - the user was
    # told "Uninstalled, thanks for trying it" with a Start menu entry still
    # pointing at a program that was gone.
    #
    # The failure is pushed in directly: an unlink that refuses. Deleting the
    # shortcut from outside cannot produce this - it would simply succeed.
    I.install(task=False, start_menu=True, desktop=False, report=report)
    said = []
    real_unlink = Path.unlink

    def refuses(self, missing_ok=False):
        if self == I.STARTMENU:
            raise PermissionError("something has it open")
        return real_unlink(self, missing_ok=missing_ok)

    Path.unlink = refuses
    try:
        result = I.uninstall(delete_data=False, report=said.append)
    finally:
        Path.unlink = real_unlink
    check("uninstall does NOT claim success", False, result)
    check("and it names the shortcut that stayed", True,
          any(I.STARTMENU.name in line for line in said))
    real_unlink(I.STARTMENU, missing_ok=True)       # tidy up after the test

    print("\n6) INSTALLATION WHILE THE APP RUNS FROM SOURCE")
    # taskkill by process name misses this case - the app runs as pythonw.exe.
    # This verifies the installer finds it by the command line and stops it;
    # otherwise two copies would run after the installation.
    project = Path(__file__).resolve().parent.parent
    pyw = project / ".venv" / "Scripts" / "pythonw.exe"

    def how_many_running():
        command = ("powershell -NoProfile -Command "
                   "\"(@(Get-CimInstance Win32_Process -Filter "
                   "'Name=''pythonw.exe''' | Where-Object "
                   "{ $_.CommandLine -like '*keep_alive.py*' })).Count\"")
        return I.quiet(command)[1].strip()

    if pyw.exists():
        # Run from a COPY of windows\ in the temp folder. Run from source the
        # app keeps its settings and log next to the sources (DATA = HERE in
        # keep_alive.py), so starting the real one here would write into
        # windows\keep_alive.log - the very thing this project fixed. The
        # redirected APPDATA does not help: it only applies to a packaged
        # build. The copy still matches "*keep_alive.py*", which is how the
        # installer finds it.
        sources = TEMP_DIR / "from-source"
        shutil.copytree(project / "windows", sources, dirs_exist_ok=True)
        subprocess.Popen([str(pyw), str(sources / "keep_alive.py"),
                          "--no-dialog", "--quit-after", "60"])
        time.sleep(8)
        before = how_many_running()
        I.stop_running_app()
        time.sleep(1)
        after = how_many_running()
        # more than one may be running (the user may be starting the app right
        # now); what matters is that at least one ran before and none after
        check("the app ran from source", True, int(before or 0) >= 1)
        check("the installer stopped them all", "0", after)
    else:
        print("  SKIPPED - no .venv")

    print("\n7) ROLE DETECTION (installer vs uninstaller)")
    check("setup.exe without an argument = install", False,
          I.is_uninstall([], r"C:\x\DaKeepSpeakersAlive-setup.exe"))
    check("setup.exe with an argument = uninstall", True,
          I.is_uninstall(["--uninstall"], r"C:\x\DaKeepSpeakersAlive-setup.exe"))
    check("uninstall.exe double-clicked = uninstall", True,
          I.is_uninstall([],
                         r"C:\Program Files\Da Keep Speakers Alive\uninstall.exe"))
    check("uninstall.exe from Settings = uninstall", True,
          I.is_uninstall(["--uninstall"],
                         r"C:\Program Files\Da Keep Speakers Alive\uninstall.exe"))

    print("\n8) LANGUAGE")
    # The installer is bilingual; without these checks nothing would notice a
    # broken translation or a language that fails to reach the app.
    I.texts.set_language("en")
    I.install(task=False, start_menu=False, desktop=False, report=report)
    check("the language is stored for the uninstaller", "en",
          I.stored_language())
    shipped = json.loads(
        (I.TARGET_DIR / "config.default.json").read_text(encoding="utf-8-sig"))
    check("the app inherits the chosen language", "en", shipped.get("language"))
    check("progress is reported in English", "Done.", I.tx("ins_done"))
    I.texts.set_language("cs")
    check("and in Czech after switching back", "Hotovo.", I.tx("ins_done"))

    # A REINSTALL, where the app already has settings of its own. load_cfg()
    # only ever copies the template when there is no config.json yet, and an
    # uninstall leaves that file behind by default - so writing the template
    # alone threw the chosen flag away and the app came up in the old
    # language, with the installer reporting success.
    live = I.DATA / "config.json"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(json.dumps({"language": "cs", "interval_s": 180}),
                    encoding="utf-8")
    I.texts.set_language("en")
    I.install(task=False, start_menu=False, desktop=False, report=report)
    settled = json.loads(live.read_text(encoding="utf-8-sig"))
    check("a reinstall carries the language into the existing settings", "en",
          settled.get("language"))
    check("and does not disturb the rest of them", 180,
          settled.get("interval_s"))
    I.texts.set_language("cs")

    # The failing branch: handing the language over returns False into
    # nothing if nobody checks, so the app would come up in the wrong language
    # while the installer says everything went fine. Forced here, because it
    # never runs otherwise.
    template = I.TARGET_DIR / "config.default.json"
    kept = template.read_bytes()
    template.unlink()
    check("a language that cannot be handed over is reported", False,
          I.ship_language("en")[0])
    template.write_bytes(kept)

    # ... and the installation as a whole then reports the problem instead of
    # claiming success. ship_language is replaced for this - deleting the
    # template does NOT work, because install() copies the program (template
    # included) before it gets there, so the first attempt at this check could
    # never go red. A check that cannot fail proves nothing.
    real_ship = I.ship_language
    I.ship_language = lambda code: (False, False)
    said = []
    try:
        result = I.install(task=False, start_menu=False, desktop=False,
                           report=said.append)
    finally:
        I.ship_language = real_ship
    check("and then the install does not claim success", False, result)
    check("the reason is on screen", True,
          any(I.tx("ins_prob_language") in line for line in said))

    print("\n8b) THE LOGON TASK, BOTH DIRECTIONS")
    # Neither branch runs on this machine (the commands are intercepted), so
    # without scripting the scheduler's answer none of it would be covered -
    # and a failed switch-on or switch-off is exactly the kind of fault the
    # user cannot see.
    pretend_task_exists[0] = True
    said = []
    result = I.install(task=True, start_menu=False, desktop=False,
                       report=said.append)
    check("asked for the task and got it: no complaint", True, result)
    check("the app was asked to create it", True,
          any("--autostart-on" in c for c in blocked))

    pretend_task_exists[0] = False           # the scheduler says: not there
    said = []
    result = I.install(task=True, start_menu=False, desktop=False,
                       report=said.append)
    check("asked for the task and did NOT get it: complains", False, result)
    check("and says which part failed", True,
          any(I.tx("ins_prob_task") in line for line in said))

    pretend_task_exists[0] = True            # ... and it would not go away
    said = []
    result = I.install(task=False, start_menu=False, desktop=False,
                       report=said.append)
    check("a task that would not be removed is reported too", False, result)
    check("and the message warns it will keep starting", True,
          any(I.tx("ins_prob_task_off") in line for line in said))

    # The gap that used to be here. Installing DISABLES the task on purpose
    # (so the scheduler cannot restart the old copy mid-copy), and
    # "schtasks /Query" answers just as happily for a disabled task as for a
    # live one. So when the app failed to switch it back on, the old check
    # saw a task, called it done - and the app never started again at logon.
    pretend_task_exists[0] = True
    pretend_autostart_works[0] = False
    said = []
    result = I.install(task=True, start_menu=False, desktop=False,
                       report=said.append)
    check("a task that is there but was never switched on is not success",
          False, result)
    check("and that is the part it names", True,
          any(I.tx("ins_prob_task") in line for line in said))
    pretend_autostart_works[0] = True
    pretend_task_exists[0] = False

    print("\n8c) AN UNINSTALL THAT LEAVES THE TASK BEHIND")
    pretend_task_exists[0] = True
    said = []
    result = I.uninstall(delete_data=False, report=said.append)
    check("a task left behind is not called a clean uninstall", False, result)
    check("and it says so", True,
          any(I.tx("uni_prob_task") in line for line in said))
    pretend_task_exists[0] = False
    # put the program back - the uninstall above deleted it
    I.install(task=False, start_menu=False, desktop=False, report=report)

    print("\n8d) AN APP THAT WILL NOT STOP")
    # The worst case in practice: the old copy keeps running, the new one
    # quits at startup with "already running" and the user thinks they
    # upgraded. Forced, because it never happens on a healthy machine.
    real_stop = I.stop_running_app
    I.stop_running_app = lambda: False
    said = []
    try:
        result = I.install(task=False, start_menu=False, desktop=False,
                           report=said.append)
    finally:
        I.stop_running_app = real_stop
    check("an app that would not stop is not passed over", False, result)
    check("and the message says what to do about it", True,
          any(I.tx("ins_prob_running") in line for line in said))
    check("the template is back for the steps below", True, template.exists())

    print("\n9) THE UNINSTALLER FILE")
    # install() only copies itself as the uninstaller when frozen, so this
    # branch never runs from source - a wrong file name would stay invisible
    # until a real installation. Pretending to be frozen forces it.
    fake_exe = TEMP_DIR / "DaKeepSpeakersAlive-setup.exe"
    fake_exe.write_bytes(b"stand-in for the packaged installer")
    real_source, real_executable = I.program_source(), sys.executable
    I.program_source = lambda: real_source     # _MEIPASS does not exist here
    sys.frozen, sys.executable = True, str(fake_exe)
    try:
        I.install(task=False, start_menu=False, desktop=False, report=report)
        check("the uninstaller is created", True,
              (I.TARGET_DIR / "uninstall.exe").exists())
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, I.REG_KEY) as k:
            uninstall_string = winreg.QueryValueEx(k, "UninstallString")[0]
        check("UninstallString points at that file", True,
              "uninstall.exe" in uninstall_string)
    finally:
        del sys.frozen
        sys.executable = real_executable
        I.program_source = lambda: real_source

    print("\n10) UNINSTALL (deleting the settings)")
    I.install(task=False, start_menu=False, desktop=False, report=report)
    I.uninstall(delete_data=True, report=report)
    check("settings deleted", False, I.DATA.exists())

    print("\n11) THE TEST LEFT THE REAL FILES ALONE")
    # Steps 3 and 6 start the app for real, and an app started from source
    # writes next to the sources. Checked, not assumed - this is the whole
    # reason step 6 runs from a copy.
    live_log = Path(__file__).resolve().parent.parent / "windows" / "keep_alive.log"
    check("the app's own log was not written into", production_log_stamp,
          live_log.stat().st_mtime if live_log.exists() else None)
    live_cfg = Path(__file__).resolve().parent.parent / "windows" / "config.json"
    check("nor the app's own settings", production_cfg_stamp,
          live_cfg.stat().st_mtime if live_cfg.exists() else None)
finally:
    cleanup()

print("\n" + ("ALL OK" if not failures else f"FAILURES: {failures}"))
sys.exit(1 if failures else 0)
