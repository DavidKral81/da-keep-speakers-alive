"""All application texts in Czech and English.

Both languages sit side by side on purpose: a missing or drifted translation
is then obvious at a glance, and `missing()` turns that into a test.

Usage:
    from texts import t
    t("btn_quit")               ->  "Ukončit aplikaci" / "Quit application"
    t("opt_minutes", m=3)       ->  "3 minuty" / "3 minutes"
    en("btn_quit")              ->  "Quit application" (always, for the log)

The language is set through `set_language("cs"|"en")` - never by assigning to
the variable directly, so there is exactly one place where it changes.

Key naming follows where the text appears: card_* / lbl_* / opt_* / sw_* in
the settings window, st_* for the status card and the icon tooltip, tray_* in
the notification area, msg_* for message boxes, err_* for failures.
"""

LANGUAGES = [("cs", "Čeština"), ("en", "English")]
_language = "cs"


def set_language(code):
    global _language
    _language = code if code in dict(LANGUAGES) else "cs"


def language():
    return _language


def t(key, **kw):
    """Text in the current language.

    A missing translation falls back to Czech, so the app never shows an
    empty string or a raw key to the user.
    """
    words = EN if _language == "en" else CS
    text = words.get(key) or CS.get(key) or key
    return text.format(**kw) if kw else text


def en(key, **kw):
    """The English text, whatever language the interface is set to.

    The log file is read by whoever is looking into a problem - us, or someone
    filing a bug report - so it stays in one language on every machine. Text
    that goes there is formatted here, never through t(); the same rule that
    keeps number() away from the log keeps the wording away from it too.
    """
    text = EN.get(key) or CS.get(key) or key
    return text.format(**kw) if kw else text


def missing():
    """Keys that exist in one language but not the other - for the test."""
    return sorted(set(CS) ^ set(EN))


CS = {
    # --- window -------------------------------------------------------
    "window_title": "{app} — nastavení",

    # --- status card ---------------------------------------------------
    "card_status": "Stav",
    "st_running": "Udržuje reproduktory vzhůru",
    "st_off": "Vypnuto — impulzy se neposílají",
    "st_paused": "Pozastaveno, obnoví se v {time}",
    "st_error": "Poslední impulz se nepodařilo přehrát",
    "st_partial": "Impulz šel jen na část reproduktorů",
    "st_last": "Poslední impulz: před {s} s ({time})",
    "st_last_never": "Poslední impulz: zatím žádný",
    "st_next": "Další impulz: za {s} s",
    "st_next_paused": "Další impulz: až po pozastavení",
    "st_next_off": "Další impulz: nebude, dokud je aplikace vypnutá",
    "st_count": "Odesláno impulzů od spuštění: {n}",
    "btn_pulse_now": "Poslat impulz teď",

    # --- pulse bar (under both "send a pulse" buttons) ------------------
    "bar_playing": "Impulz se přehrává… {done} / {total} s",
    "bar_done": "Impulz odeslán ({total} s)",
    "bar_failed": "Impulz se nepodařilo přehrát — podrobnosti nahoře ve Stavu.",
    "bar_partial": "Impulz šel jen na část reproduktorů — podrobnosti nahoře "
                   "ve Stavu.",

    # --- devices card --------------------------------------------------
    "card_devices": "Které reproduktory udržovat",
    "card_devices_desc": "Vyber výstupy, na které se má posílat impulz. "
                         "Zařízení se hledá podle názvu, takže po přepojení "
                         "USB do jiného portu volba drží dál.",
    "sw_use_default": "Vždy výchozí zařízení systému (to, co je právě "
                      "nastavené ve Windows)",
    "dev_default_mark": "{name}   (teď výchozí)",
    "dev_none_found": "(žádný výstup se nenašel — zkus načíst seznam znovu)",
    "dev_missing": "{name}   (není připojené)",
    "link_rescan": "Načíst seznam zařízení znovu",

    # --- interval card -------------------------------------------------
    "card_interval": "Jak často posílat impulz",
    "card_interval_desc": "Reproduktory usnou po několika minutách ticha. "
                          "Interval musí být kratší než ta doba — když "
                          "reproduktory přesto usnou, zkrať ho.",
    "lbl_interval": "Interval",
    "opt_seconds": "{s} sekund",
    "opt_minute": "{m} minuta",
    "opt_minutes": "{m} minuty",
    "opt_minutes_5": "{m} minut",

    # --- signal card ---------------------------------------------------
    "card_signal": "Jaký impulz posílat",
    "card_signal_desc": "Krátký tón tak hluboký a tichý, že ho neslyšíš, ale "
                        "reproduktor ho pozná jako signál. Když ho slyšíš, "
                        "sniž hlasitost nebo frekvenci.",
    "lbl_freq": "Frekvence",
    "opt_hz": "{v} Hz",
    "lbl_duration": "Délka impulzu",
    "opt_sec": "{v} s",
    "lbl_amp": "Hlasitost (% plného rozsahu)",
    "opt_percent": "{v} %",
    "sw_amp_correction": "Dynamická korekce hlasitosti",
    "sw_amp_correction_desc": "Zesílí úroveň odesílaného signálu, pokud je "
                              "hlasitost ve Windows nastavena příliš nízko "
                              "(prevence příliš slabého signálu, který "
                              "reproduktory neprobudí).",
    "warn_short_pulse": "Pozor: {d} s při {f} Hz je jen {p} periody. Kratší "
                        "než dvě celé vlny reproduktor nezahraje jako tón — "
                        "prodluž impulz nebo zvyš frekvenci.",
    "btn_test": "Vyzkoušet impulz",

    # --- app behaviour card --------------------------------------------
    "card_app": "Chování aplikace",
    "sw_active": "Udržovat reproduktory vzhůru",
    "sw_autostart": "Spouštět po přihlášení do Windows",
    "link_log": "Otevřít log",
    # Problems that have nowhere else to be seen - a zabalená aplikace nemá
    # konzoli. Viz problem() v keep_alive.py.
    "warn_config": "Nastavení se nepodařilo přečíst, takže platí výchozí "
                   "hodnoty — včetně výběru reproduktorů. Zkontroluj "
                   "config.json. ({error})",
    "warn_log": "Do souboru s logem se nepodařilo zapsat, takže se záznam "
                "nevede. ({error})",
    "warn_log_rotate": "Log přerostl svoji velikost a nepodařilo se založit "
                       "nový soubor, takže roste dál. ({error})",
    "warn_log_open": "Log se nepodařilo otevřít. Hledej ho v {path}. ({error})",

    # --- pause card ----------------------------------------------------
    "card_pause": "Dočasně pozastavit",
    "card_pause_desc": "Když potřebuješ mít chvíli úplný klid — třeba při "
                       "nahrávání zvuku. Po uplynutí doby se to zapne samo.",
    "opt_not_paused": "Nepozastaveno",
    "opt_pause_min": "Pozastavit na {m} minut",
    "opt_pause_hour": "Pozastavit na {h} hodinu",
    "opt_pause_hours": "Pozastavit na {h} hodiny",
    "opt_pause_hours_5": "Pozastavit na {h} hodin",

    # --- links ---------------------------------------------------------
    "link_manual": "Návod",
    "link_project": "Stránka projektu",
    "link_updates": "Zkontrolovat aktualizace",
    "btn_quit": "Ukončit aplikaci",

    # --- tray ----------------------------------------------------------
    "tray_active": "Udržovat reproduktory vzhůru",
    "tray_pulse_now": "Poslat impulz teď",
    "tray_pause": "Pozastavit",
    "tray_settings": "Nastavení…",
    "tray_quit": "Ukončit aplikaci",

    # --- messages ------------------------------------------------------
    "msg_already_running": "Aplikace už běží — najdeš ji v oznamovací oblasti "
                           "u hodin.",
    "err_no_device": "Není vybrané žádné zařízení — otevři Nastavení a vyber "
                     "reproduktory.",
    "err_device_gone": "Zařízení „{name}“ není připojené. Zapoj ho, nebo ho "
                       "odškrtni v seznamu reproduktorů.",
    "err_play": "Přehrání na „{name}“ selhalo: {error}",
    "err_engine": "Aplikace narazila na neočekávanou chybu: {error}. "
                  "Zkusí to znovu za chvíli.",
    "err_autostart": "Úlohu v Plánovači úloh se nepodařilo vytvořit. "
                     "Spouštění po přihlášení zůstává vypnuté.",

    # --- installer -----------------------------------------------------
    # The installer speaks out of THIS table, not out of a copy of its own -
    # two tables would drift apart, and missing() then covers the installer
    # too.
    "ins_title_install": "{app} — instalace",
    "ins_title_uninstall": "{app} — odinstalace",
    "ins_subtitle": "Udržuje reproduktory vzhůru krátkým neslyšitelným "
                    "impulzem.",
    "ins_to_folder": "Aplikace se nainstaluje do:",
    "ins_from_folder": "Aplikace se odinstaluje z:",
    "ins_opt_startmenu": "Zástupce v nabídce Start",
    "ins_opt_desktop": "Zástupce na ploše",
    "ins_opt_autostart": "Spouštět po přihlášení do Windows",
    "ins_btn_install": "Nainstalovat",
    "ins_btn_uninstall": "Odinstalovat",
    "ins_btn_close": "Zavřít",
    "ins_btn_finish": "Dokončit",

    # progress
    "ins_stopping": "Ukončuji běžící aplikaci…",
    "ins_copying": "Kopíruji soubory…",
    "ins_startmenu": "Vytvářím zástupce v nabídce Start…",
    "ins_desktop": "Vytvářím zástupce na ploše…",
    "ins_registry": "Zapisuji do seznamu aplikací…",
    "ins_task_on": "Nastavuji spouštění po přihlášení…",
    "ins_task_off": "Ruším spouštění po přihlášení…",
    "ins_checking": "Kontroluji výsledek…",
    "ins_done": "Hotovo.",

    # what did not work — the installer must never claim success instead
    "ins_failed": "Nepodařilo se: {what}",
    "ins_error": "Chyba: {error}",
    "ins_err_copy": "Program se nepodařilo zkopírovat do cílové složky.",
    "ins_prob_language": "předání jazyka aplikaci",
    "ins_prob_startmenu": "zástupce v nabídce Start",
    "ins_prob_desktop": "zástupce na ploše",
    "ins_prob_program": "program v cílové složce",
    "ins_prob_uninstaller": "odinstalátor",
    # this one has to say what to do about it - the user cannot guess
    "ins_prob_running": "běžící aplikaci se nepodařilo ukončit (ukonči ji "
                        "u hodin a spusť instalaci znovu)",
    "ins_prob_registry": "zápis do seznamu aplikací",
    "ins_prob_task": "úloha v Plánovači",
    "ins_prob_task_hold": "vypnutí úlohy v Plánovači na dobu instalace "
                          "(Plánovač mohl aplikaci mezitím znovu spustit — "
                          "restartuj počítač)",
    "ins_prob_language_elsewhere": "předání jazyka aplikaci (nastavení má "
                                   "jiný uživatel než ten, pod kterým běží "
                                   "instalace — jazyk si přepni v okně "
                                   "aplikace)",
    "ins_prob_task_off": "zrušení spouštění po přihlášení (aplikace se bude "
                         "dál spouštět sama)",
    "ins_prob_task_disabled": "úloha pro spouštění po přihlášení sice vznikla, "
                              "ale zůstala zakázaná, takže se nespustí — zapni "
                              "ji v Plánovači úloh, nebo přepínač v okně "
                              "aplikace vypni a zase zapni",

    # result window
    "ins_head_installed": "Nainstalováno",
    "ins_head_uninstalled": "Odinstalováno",
    "ins_ok_desc": "Aplikace běží jako ikona u hodin. Klikni na ni pravým "
                   "tlačítkem, když chceš změnit nastavení.",
    "ins_opt_launch": "Spustit {app}",
    "ins_opt_manual": "Otevřít návod",
    "ins_msg_admin": "Instalaci je potřeba spustit jako správce.",
    "ins_msg_running": "Aplikace už běží — najdeš ji u hodin.",

    # uninstall
    "uni_opt_data": "Smazat i nastavení a log",
    "uni_shortcuts": "Odstraňuji zástupce…",
    "uni_registry": "Odstraňuji ze seznamu aplikací…",
    "uni_data": "Mažu nastavení a log…",
    "uni_files": "Mažu soubory programu…",
    "uni_prob_files": "složka programu",
    "uni_prob_task": "úloha v Plánovači (zkoušela by spouštět program, "
                     "který už není)",
    "uni_prob_data_elsewhere": "nastavení a log — leží v profilu "
                               "přihlášeného uživatele, ne toho, pod kterým "
                               "běží odinstalace; smaž složku "
                               "%APPDATA%\\Da Keep Speakers Alive ručně",
    "uni_partial": "Nepodařilo se odstranit: {what}",
    "uni_ok_desc": "{app} je odinstalovaná. Díky za vyzkoušení.",
    "uni_partial_desc": "{app} je odinstalovaná, ale něco na disku zůstalo. "
                        "Zkus to smazat ručně po restartu počítače.",
}

EN = {
    # --- window -------------------------------------------------------
    "window_title": "{app} — settings",

    # --- status card ---------------------------------------------------
    "card_status": "Status",
    "st_running": "Keeping the speakers awake",
    "st_off": "Switched off — no pulses are sent",
    "st_paused": "Paused, resumes at {time}",
    "st_error": "The last pulse could not be played",
    "st_partial": "The pulse reached only some of the speakers",
    "st_last": "Last pulse: {s} s ago ({time})",
    "st_last_never": "Last pulse: none yet",
    "st_next": "Next pulse: in {s} s",
    "st_next_paused": "Next pulse: after the pause ends",
    "st_next_off": "Next pulse: none while the app is switched off",
    "st_count": "Pulses sent since start: {n}",
    "btn_pulse_now": "Send a pulse now",

    # --- pulse bar (under both "send a pulse" buttons) ------------------
    "bar_playing": "Pulse playing… {done} / {total} s",
    "bar_done": "Pulse sent ({total} s)",
    "bar_failed": "The pulse could not be played — see Status above.",
    "bar_partial": "The pulse reached only some of the speakers — see Status "
                   "above.",

    # --- devices card --------------------------------------------------
    "card_devices": "Which speakers to keep awake",
    "card_devices_desc": "Pick the outputs the pulse is sent to. A device is "
                         "matched by its name, so the choice survives "
                         "plugging the USB into another port.",
    "sw_use_default": "Always the system default device (whatever Windows is "
                      "set to right now)",
    "dev_default_mark": "{name}   (default now)",
    "dev_none_found": "(no output found — try reloading the list)",
    "dev_missing": "{name}   (not connected)",
    "link_rescan": "Reload the list of devices",

    # --- interval card -------------------------------------------------
    "card_interval": "How often to send a pulse",
    "card_interval_desc": "Speakers fall asleep after a few minutes of "
                          "silence. The interval has to be shorter than that "
                          "— if they still fall asleep, shorten it.",
    "lbl_interval": "Interval",
    "opt_seconds": "{s} seconds",
    "opt_minute": "{m} minute",
    "opt_minutes": "{m} minutes",
    "opt_minutes_5": "{m} minutes",

    # --- signal card ---------------------------------------------------
    "card_signal": "What the pulse sounds like",
    "card_signal_desc": "A tone so low and so quiet that you cannot hear it, "
                        "yet the speaker recognises it as a signal. If you do "
                        "hear it, lower the volume or the frequency.",
    "lbl_freq": "Frequency",
    "opt_hz": "{v} Hz",
    "lbl_duration": "Pulse length",
    "opt_sec": "{v} s",
    "lbl_amp": "Volume (% of full scale)",
    "opt_percent": "{v} %",
    "sw_amp_correction": "Dynamic volume correction",
    "sw_amp_correction_desc": "Raises the level of the signal sent when the "
                              "Windows volume is set too low (so the signal "
                              "cannot end up too weak to wake the speakers).",
    "warn_short_pulse": "Careful: {d} s at {f} Hz is only {p} periods. Less "
                        "than two full waves is not a tone to a speaker — "
                        "make the pulse longer or raise the frequency.",
    "btn_test": "Try a pulse",

    # --- app behaviour card --------------------------------------------
    "card_app": "Application behaviour",
    "sw_active": "Keep the speakers awake",
    "sw_autostart": "Start when I log in to Windows",
    "link_log": "Open the log",
    # Problems with nowhere else to show - a packaged app has no console.
    # See problem() in keep_alive.py. These are also what the LOG says, so
    # they have to read sensibly on their own line in a text file.
    "warn_config": "The settings could not be read, so the defaults are in "
                   "use - including which speakers are picked. Have a look at "
                   "config.json. ({error})",
    "warn_log": "The log file could not be written, so nothing is being "
                "recorded. ({error})",
    "warn_log_rotate": "The log outgrew its size and a new file could not be "
                       "started, so it keeps growing. ({error})",
    "warn_log_open": "The log could not be opened. It lives in {path}. "
                     "({error})",

    # --- pause card ----------------------------------------------------
    "card_pause": "Pause for a while",
    "card_pause_desc": "For when you need complete silence — recording audio, "
                       "say. It switches itself back on afterwards.",
    "opt_not_paused": "Not paused",
    "opt_pause_min": "Pause for {m} minutes",
    "opt_pause_hour": "Pause for {h} hour",
    "opt_pause_hours": "Pause for {h} hours",
    "opt_pause_hours_5": "Pause for {h} hours",

    # --- links ---------------------------------------------------------
    "link_manual": "Manual",
    "link_project": "Project page",
    "link_updates": "Check for updates",
    "btn_quit": "Quit application",

    # --- tray ----------------------------------------------------------
    "tray_active": "Keep the speakers awake",
    "tray_pulse_now": "Send a pulse now",
    "tray_pause": "Pause",
    "tray_settings": "Settings…",
    "tray_quit": "Quit application",

    # --- messages ------------------------------------------------------
    "msg_already_running": "The app is already running — look for it in the "
                           "notification area next to the clock.",
    "err_no_device": "No device is selected — open Settings and pick your "
                     "speakers.",
    "err_device_gone": "Device “{name}” is not connected. Plug it in, or "
                       "untick it in the list of speakers.",
    "err_play": "Playback on “{name}” failed: {error}",
    "err_engine": "The app hit an unexpected error: {error}. It will try "
                  "again shortly.",
    "err_autostart": "The task could not be created in Task Scheduler. "
                     "Starting at logon stays switched off.",

    # --- installer -----------------------------------------------------
    "ins_title_install": "{app} — setup",
    "ins_title_uninstall": "{app} — uninstall",
    "ins_subtitle": "Keeps speakers awake with a short inaudible pulse.",
    "ins_to_folder": "The app will be installed into:",
    "ins_from_folder": "The app will be removed from:",
    "ins_opt_startmenu": "Shortcut in the Start menu",
    "ins_opt_desktop": "Shortcut on the desktop",
    "ins_opt_autostart": "Start when I log in to Windows",
    "ins_btn_install": "Install",
    "ins_btn_uninstall": "Uninstall",
    "ins_btn_close": "Close",
    "ins_btn_finish": "Finish",

    # progress
    "ins_stopping": "Stopping the running app…",
    "ins_copying": "Copying files…",
    "ins_startmenu": "Creating the Start menu shortcut…",
    "ins_desktop": "Creating the desktop shortcut…",
    "ins_registry": "Adding to the list of applications…",
    "ins_task_on": "Setting up start at logon…",
    "ins_task_off": "Removing start at logon…",
    "ins_checking": "Checking the result…",
    "ins_done": "Done.",

    # what did not work — the installer must never claim success instead
    "ins_failed": "Did not work: {what}",
    "ins_error": "Error: {error}",
    "ins_err_copy": "The program could not be copied into the target folder.",
    "ins_prob_language": "handing the language to the app",
    "ins_prob_startmenu": "the Start menu shortcut",
    "ins_prob_desktop": "the desktop shortcut",
    "ins_prob_program": "the program in the target folder",
    "ins_prob_uninstaller": "the uninstaller",
    # this one has to say what to do about it - the user cannot guess
    "ins_prob_running": "the running app could not be stopped (quit it from "
                        "the clock area and run setup again)",
    "ins_prob_registry": "the entry in the list of applications",
    "ins_prob_task": "the task in Task Scheduler",
    "ins_prob_task_hold": "holding the scheduled task off during the install "
                          "(it may have started the app again meanwhile - "
                          "restart the computer)",
    "ins_prob_language_elsewhere": "handing the language to the app (the "
                                   "settings belong to a different user than "
                                   "the one running setup - switch the "
                                   "language in the app's window)",
    "ins_prob_task_off": "removing start at logon (the app will keep starting "
                         "on its own)",
    "ins_prob_task_disabled": "the start-at-logon task was created but left "
                              "disabled, so it will not run - enable it in "
                              "Task Scheduler, or switch the option in the "
                              "app's window off and on again",

    # result window
    "ins_head_installed": "Installed",
    "ins_head_uninstalled": "Uninstalled",
    "ins_ok_desc": "The app runs as an icon next to the clock. Right-click it "
                   "whenever you want to change the settings.",
    "ins_opt_launch": "Start {app}",
    "ins_opt_manual": "Open the manual",
    "ins_msg_admin": "Setup has to be run as an administrator.",
    "ins_msg_running": "The app is already running — look for it next to the "
                       "clock.",

    # uninstall
    "uni_opt_data": "Delete the settings and the log as well",
    "uni_shortcuts": "Removing the shortcuts…",
    "uni_registry": "Removing from the list of applications…",
    "uni_data": "Deleting the settings and the log…",
    "uni_files": "Deleting the program files…",
    "uni_prob_files": "the program folder",
    "uni_prob_task": "the task in Task Scheduler (it would keep trying to "
                     "start a program that is gone)",
    "uni_prob_data_elsewhere": "the settings and the log — they are in the "
                               "profile of the logged-in user, not of the "
                               "account running this uninstall; delete "
                               "%APPDATA%\\Da Keep Speakers Alive by hand",
    "uni_partial": "Could not remove: {what}",
    "uni_ok_desc": "{app} has been uninstalled. Thanks for trying it.",
    "uni_partial_desc": "{app} has been uninstalled, but something was left "
                        "on disk. Try deleting it by hand after a restart.",
}
