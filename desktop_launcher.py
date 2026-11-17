"""Windows entry point. The application interface remains the Flask website.

Only lifecycle status and masked local administrator setup use stdlib Tk.
The headless options are for build-machine smoke tests, not faculty workflows.
"""
import argparse
import logging
import os
from pathlib import Path
import queue
import signal
import sys
import threading

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from desktop_auth import AdministratorCredentials
from desktop_runtime import (
    DesktopServer, InstanceLock, configure_logging, create_application,
    data_directory, existing_instance, launch_browser, prepare_storage,
    resource_root, validate_resources,
)


def ask_password(parent, credentials, *, reset=False):
    from tkinter import messagebox, simpledialog
    if reset and not messagebox.askyesno(
        "Reset Administrator",
        "This replaces the local administrator password for this Windows account. "
        "Your database and templates will be kept. Continue?", parent=parent,
    ):
        return False
    while True:
        password = simpledialog.askstring(
            "Administrator setup", "Establish an administrator password (12–256 characters).\n"
            "Keep it safe; it will be needed only for official template updates.",
            show="*", parent=parent,
        )
        if password is None:
            return False
        if not 12 <= len(password) <= 256:
            messagebox.showerror("Administrator setup", "Use 12–256 characters.", parent=parent)
            continue
        confirmation = simpledialog.askstring("Confirm password", "Enter the same password again:", show="*", parent=parent)
        if confirmation is None:
            return False
        if password != confirmation:
            messagebox.showerror("Administrator setup", "The passwords do not match. Please try again.", parent=parent)
            continue
        credentials.establish(password, reset=reset)
        return True


def run_headless(root, credentials, args):
    if args.reset_admin or not credentials.exists():
        raise RuntimeError("Headless startup requires an existing administrator verifier. Use the normal launcher for setup.")
    stopped = threading.Event()
    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stopped.set())
    validate_resources(resource_root())
    server = DesktopServer(create_application(root, credentials), root)
    stop_request = root / ".stop-request"
    stop_request.unlink(missing_ok=True)
    try:
        server.start(open_browser=not args.no_browser)
        while not stopped.wait(0.2):
            if stop_request.exists():
                stop_request.unlink()
                break
            if not server.thread.is_alive():
                raise RuntimeError("The local server stopped unexpectedly.")
    finally:
        server.stop()


def run_window(root, credentials, args):
    import tkinter as tk
    from tkinter import messagebox, ttk
    window = tk.Tk()
    window.title("Module Outline Generator")
    window.geometry("560x240")
    window.minsize(500, 240)
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill="both", expand=True)
    status = tk.StringVar(value="Starting the local application…")
    address = tk.StringVar(value="")
    ttk.Label(frame, textvariable=status, wraplength=510).pack(anchor="w", pady=(0, 10))
    ttk.Label(frame, textvariable=address).pack(anchor="w")
    ttk.Label(frame, text="Keep this window open while working in your browser.\n"
              "Use Stop Application when finished. Closing this window also stops it.",
              wraplength=510).pack(anchor="w", pady=12)
    buttons = ttk.Frame(frame)
    buttons.pack(anchor="w")
    events = queue.Queue()
    server = None
    closing = False
    starting = True
    stopping = False

    def close():
        nonlocal closing, stopping
        closing = True
        status.set("Stopping… waiting for current file operations to finish.")
        open_button.configure(state="disabled")
        stop_button.configure(state="disabled")
        if starting or stopping:
            return
        stopping = True

        def stop():
            try:
                if server:
                    server.stop()
            finally:
                events.put(("stopped", None))
        threading.Thread(target=stop, name="desktop-stop", daemon=True).start()

    open_button = ttk.Button(buttons, text="Open Browser", command=lambda: launch_browser(address.get()), state="disabled")
    open_button.pack(side="left", padx=(0, 10))
    stop_button = ttk.Button(buttons, text="Stop Application", command=close)
    stop_button.pack(side="left")
    window.protocol("WM_DELETE_WINDOW", close)
    window.update()
    try:
        if args.reset_admin:
            if not ask_password(window, credentials, reset=True):
                window.destroy()
                return
        elif not credentials.exists():
            if (root / "data" / "module_outlines.db").exists():
                raise RuntimeError("Administrator credentials are missing. Close this window and open Reset Administrator to establish a new password.")
            if not ask_password(window, credentials):
                window.destroy()
                return
    except Exception as exc:
        messagebox.showerror("Cannot start Module Outline Generator", str(exc), parent=window)
        window.destroy()
        return

    def start():
        nonlocal server
        try:
            validate_resources(resource_root())
            server = DesktopServer(create_application(root, credentials), root)
            events.put(("ready", server.start(open_browser=False)))
        except Exception as exc:
            # Never include request headers, credentials or traceback locals.
            logging.error("Startup failed (%s)", type(exc).__name__)
            events.put(("error", str(exc)))

    def poll():
        nonlocal starting
        try:
            kind, value = events.get_nowait()
            if kind == "ready":
                starting = False
                if closing:
                    close()
                else:
                    address.set(value)
                    status.set("Application is running. Your browser contains the module outline interface.")
                    open_button.configure(state="normal")
                    if not args.no_browser and not launch_browser(value):
                        status.set("Application is running. Use Open Browser, or enter the local address below in your browser.")
            elif kind == "error":
                starting = False
                messagebox.showerror("Cannot start Module Outline Generator",
                                     value + "\n\nSee README-Windows.txt for help.", parent=window)
                window.destroy()
                return
            elif kind == "stopped":
                window.destroy()
                return
        except queue.Empty:
            pass
        if not starting and not closing and server and not server.thread.is_alive():
            messagebox.showerror("Local server stopped", "Close the application and launch it again. See the logs folder if the problem continues.", parent=window)
            close()
        window.after(100, poll)

    threading.Thread(target=start, name="desktop-start", daemon=True).start()
    window.after(100, poll)
    try:
        window.mainloop()
    finally:
        if server:
            server.stop()


def show_message(title, message, *, error=False):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10 if error else 0x40)
    else:
        print(f"{title}: {message}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Module Outline Generator")
    parser.add_argument("--reset-admin", action="store_true")
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    lock = None
    try:
        root = data_directory(args.data_dir)
        lock = InstanceLock(root)
        if not lock.acquire():
            url = existing_instance(root)
            if url and not args.reset_admin:
                if not args.no_browser:
                    launch_browser(url)
                return 0
            if not args.headless:
                show_message("Module Outline Generator is already open",
                             "Use the existing application window. Finish administrator setup there, "
                             "or stop that application before resetting the password.")
            return 1
        prepare_storage(root)
        configure_logging(root)
        credentials = AdministratorCredentials(root / "data" / "administrator.json")
        if args.headless:
            run_headless(root, credentials, args)
        else:
            run_window(root, credentials, args)
        return 0
    except Exception as exc:
        logging.error("Desktop startup failed (%s)", type(exc).__name__)
        if not args.headless:
            show_message("Cannot start Module Outline Generator",
                         str(exc) + "\n\nCheck that the complete ZIP was extracted and your local application data folder is writable.", error=True)
        return 1
    finally:
        if lock:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
