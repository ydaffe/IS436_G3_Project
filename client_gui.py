"""
IS436 Group 3 - Tkinter (GUI) chat client.

Usage:
    python client_gui.py <port> [--host HOST] [--name NAME]

If --name is left out, a small dialog asks for a username.

THE ONE THREADING RULE FOR TKINTER
----------------------------------
Tkinter is NOT thread-safe: only the main thread (the one running
root.mainloop()) may touch widgets. So:

    RECEIVER THREAD (daemon)  loops on recv(), decodes messages and puts them
                              on a queue.Queue. It NEVER touches a widget.
    MAIN THREAD               runs the Tkinter mainloop. Every 100 ms,
                              root.after() calls poll_queue(), which takes the
                              waiting messages off the queue and updates the
                              chat window.

queue.Queue does its own locking, so it is safe to put() from one thread
and get() from another.
"""
import argparse
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog

from common import config, protocol
from common.protocol import SERVER_NAME

POLL_MS = 100               # how often the GUI checks the queue for new messages
TYPING_IDLE_MS = 2000       # stop showing "typing..." after 2 s without a keystroke

# Special item the receiver thread puts on the queue when the connection ends.
DISCONNECTED = {"type": "_disconnected"}


class ChatWindow:
    def __init__(self, root, sock, host, port):
        self.root = root
        self.sock = sock
        self.incoming = queue.Queue()   # receiver thread -> GUI thread
        self.chat_id = None             # our ID, learned from the welcome message
        self.connected = True
        self.closing = False            # True once WE decided to leave

        # Typing indicator state
        self.typing_users = {}          # chat_id -> label of OTHER users currently typing
        self.i_am_typing = False        # have we told the server we are typing?
        self.typing_timer = None        # Tk "after" id that will send is_typing=False

        self.build_widgets(host, port)

        # Start the RECEIVER THREAD. daemon=True: it never keeps the program alive.
        threading.Thread(target=self.receive_loop, name="receiver", daemon=True).start()

        # Start polling the queue from the main thread.
        self.root.after(POLL_MS, self.poll_queue)

        # Closing the window with the X button = leaving the chat gracefully.
        self.root.protocol("WM_DELETE_WINDOW", self.leave)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def build_widgets(self, host, port):
        self.root.title(f"IS436 G3 Chat - {host}:{port}")
        self.root.minsize(520, 400)

        self.status = tk.Label(self.root, text=f"Connecting to {host}:{port}...", anchor="w",
                               font=("Segoe UI", 10, "bold"))
        self.status.pack(fill="x", padx=8, pady=(8, 0))

        # The chat log. state="disabled" makes it read-only for the user;
        # we briefly enable it in append() to insert text.
        self.chat = scrolledtext.ScrolledText(self.root, wrap="word", state="disabled",
                                              height=20, font=("Segoe UI", 10))
        self.chat.pack(fill="both", expand=True, padx=8, pady=6)
        self.chat.tag_config("time", foreground="#888888")
        self.chat.tag_config("me", foreground="#1a5fb4", font=("Segoe UI", 10, "bold"))
        self.chat.tag_config("other", foreground="#26a269", font=("Segoe UI", 10, "bold"))
        self.chat.tag_config("server", foreground="#c64600", font=("Segoe UI", 10, "bold"))
        self.chat.tag_config("system", foreground="#666666", font=("Segoe UI", 10, "italic"))
        self.chat.tag_config("history", foreground="#999999")
        self.chat.tag_config("error", foreground="#c01c28")

        self.typing_label = tk.Label(self.root, text="", anchor="w", fg="#666666",
                                     font=("Segoe UI", 9, "italic"))
        self.typing_label.pack(fill="x", padx=8)

        bottom = tk.Frame(self.root)
        bottom.pack(fill="x", padx=8, pady=(2, 4))
        self.entry_text = tk.StringVar()
        self.entry = tk.Entry(bottom, textvariable=self.entry_text, font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda event: self.send_chat())
        self.entry.bind("<KeyRelease>", self.on_key)
        self.counter = tk.Label(bottom, text=f"0/{config.MAX_MESSAGE_LENGTH}", width=8, fg="#888888")
        self.counter.pack(side="left", padx=4)
        # Update the "123/500" counter whenever the text changes (typing, pasting or clearing).
        self.entry_text.trace_add("write", lambda *unused: self.update_counter())
        self.send_button = tk.Button(bottom, text="Send", width=8, command=self.send_chat)
        self.send_button.pack(side="left", padx=(0, 4))
        self.leave_button = tk.Button(bottom, text="Leave", width=8, command=self.leave)
        self.leave_button.pack(side="left")

        tk.Label(self.root, text=f"Press Enter to send. Type '{config.EXIT_KEYWORD}' or click Leave to exit.",
                 anchor="w", fg="#888888", font=("Segoe UI", 8)).pack(fill="x", padx=8, pady=(0, 6))
        self.entry.focus_set()

    def append(self, parts):
        """Add one line to the chat log. parts = [(text, tag), ...]. MAIN THREAD ONLY."""
        self.chat.configure(state="normal")
        for text, tag in parts:
            self.chat.insert("end", text, tag)
        self.chat.insert("end", "\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")                # scroll to the newest message

    # ------------------------------------------------------------------
    # RECEIVER THREAD - network only, never touches widgets
    # ------------------------------------------------------------------
    def receive_loop(self):
        buffer = b""
        try:
            while True:
                try:
                    data = self.sock.recv(config.BUFFER_SIZE)   # BLOCKS until data arrives
                except OSError:
                    break           # socket closed (we left) or connection reset
                if not data:
                    break           # b"" = the server closed the connection
                buffer += data      # TCP stream: keep partial lines until complete
                messages, buffer = protocol.split_lines(buffer)
                for message in messages:
                    self.incoming.put(message)      # hand over to the GUI thread
        finally:
            self.incoming.put(DISCONNECTED)

    # ------------------------------------------------------------------
    # MAIN THREAD - process queued messages
    # ------------------------------------------------------------------
    def poll_queue(self):
        """Called every POLL_MS by Tkinter: handle everything the receiver has queued."""
        if self.closing:
            return                  # window is going away; stop polling
        try:
            while True:
                self.show(self.incoming.get_nowait())
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self.poll_queue)   # schedule the next check

    def show(self, message):
        """Display one message from the server."""
        kind = message.get("type")
        time = f"[{protocol.format_time(message.get('timestamp'))}] "

        if kind == "welcome":
            self.chat_id = message.get("chat_id")
            self.status.config(text=f"Connected as {self.chat_id}")
            self.append([(time, "time"), (message.get("text", ""), "system")])

        elif kind == "history":
            items = message.get("messages", [])
            self.append([(f"--- Last {len(items)} message(s) before you joined ---", "history")])
            for item in items:
                self.append([(protocol.format_message(item), "history")])
            self.append([("--- End of chat history ---", "history")])

        elif kind == "chat":
            sender = message.get("sender")
            if sender == self.chat_id:
                tag = "me"
            elif sender == SERVER_NAME:
                tag = "server"
            else:
                tag = "other"
            self.set_typing(sender, None, False)    # they just sent, so they stopped typing
            self.append([(time, "time"), (protocol.sender_label(message), tag),
                         (": " + message.get("text", ""), None)])

        elif kind == "join":
            # Our own join message tells us the username the server gave us.
            if message.get("chat_id") == self.chat_id:
                self.status.config(text=f"Connected as {message.get('username')} ({self.chat_id})")
            self.append([(time, "time"), (message.get("text", ""), "system")])

        elif kind == "leave":
            self.set_typing(message.get("chat_id"), None, False)
            self.append([(time, "time"), (message.get("text", ""), "system")])

        elif kind == "typing":
            label = protocol.sender_label({"sender": message.get("chat_id"), "username": message.get("username")})
            self.set_typing(message.get("chat_id"), label, message.get("is_typing"))

        elif kind in ("error", "shutdown"):
            self.append([(time, "time"), (message.get("text", ""), "error")])

        elif message is DISCONNECTED:
            self.on_disconnected()

    def on_disconnected(self):
        """The connection is gone. If we did not choose to leave, tell the user."""
        self.connected = False
        if self.closing:
            return
        self.typing_users.clear()
        self.refresh_typing_label()
        self.append([("*** Disconnected from the server. You can close this window.", "error")])
        self.status.config(text="Disconnected")
        self.entry.config(state="disabled")
        self.send_button.config(state="disabled")
        self.leave_button.config(text="Close")

    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------
    def set_typing(self, chat_id, label, is_typing):
        """Remember who else is typing and update the "... is typing" label."""
        if is_typing:
            self.typing_users[chat_id] = label
        else:
            self.typing_users.pop(chat_id, None)
        self.refresh_typing_label()

    def refresh_typing_label(self):
        names = list(self.typing_users.values())
        if not names:
            text = ""
        elif len(names) == 1:
            text = f"{names[0]} is typing..."
        elif len(names) == 2:
            text = f"{names[0]} and {names[1]} are typing..."
        else:
            text = "Several people are typing..."
        self.typing_label.config(text=text)

    def on_key(self, event):
        """Every keystroke in the entry box: update the counter and our typing status."""
        if event.keysym == "Return":
            return
        text = self.entry_text.get()
        if not text.strip():
            self.stop_typing()
            return
        if not self.i_am_typing:
            self.i_am_typing = True
            self.send({"type": "typing", "is_typing": True})
        # Restart the idle timer: if no key is pressed for TYPING_IDLE_MS, we stop "typing".
        if self.typing_timer is not None:
            self.root.after_cancel(self.typing_timer)
        self.typing_timer = self.root.after(TYPING_IDLE_MS, self.stop_typing)

    def update_counter(self):
        """Show how many characters are typed; turn red when over the limit."""
        length = len(self.entry_text.get())
        self.counter.config(text=f"{length}/{config.MAX_MESSAGE_LENGTH}",
                            fg="#c01c28" if length > config.MAX_MESSAGE_LENGTH else "#888888")

    def stop_typing(self):
        if self.typing_timer is not None:
            self.root.after_cancel(self.typing_timer)
            self.typing_timer = None
        if self.i_am_typing:
            self.i_am_typing = False
            self.send({"type": "typing", "is_typing": False})

    # ------------------------------------------------------------------
    # Sending and leaving
    # ------------------------------------------------------------------
    def send(self, message):
        """Send one message (main thread). Returns False if the connection is broken."""
        if not self.connected:
            return False
        try:
            self.sock.sendall(protocol.encode(message))
            return True
        except OSError:
            return False

    def send_chat(self):
        text = self.entry_text.get()
        if text == "":
            return                  # nothing typed: ignore
        if text.strip().lower() == config.EXIT_KEYWORD:
            self.leave()
            return
        # Length/blank rules are checked by the SERVER, which replies with a
        # friendly error shown in red, so the rules live in one place.
        if self.send({"type": "chat", "text": text}):
            self.entry_text.set("")         # the counter resets itself through the trace
            self.stop_typing()

    def leave(self):
        """Exit gracefully: tell the server, close the socket, close the window."""
        if self.closing:
            return
        self.closing = True
        if self.connected:
            self.send({"type": "exit"})
        protocol.close_socket(self.sock)    # also wakes the receiver thread out of recv()
        self.root.destroy()                 # ends root.mainloop() in main()


def parse_args():
    parser = argparse.ArgumentParser(description="IS436 G3 chat client (Tkinter GUI).")
    parser.add_argument("port", help=f"server port ({config.MIN_PORT}-{config.MAX_PORT})")
    parser.add_argument("--host", default=config.HOST, help=f"server address (default {config.HOST})")
    parser.add_argument("--name", help="your username")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        port = config.parse_port(args.port)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        print("Usage: python client_gui.py <port>   e.g. python client_gui.py 5050", file=sys.stderr)
        sys.exit(1)

    root = tk.Tk()
    root.withdraw()                 # keep the main window hidden until we are connected

    name = args.name
    if name is None:
        name = simpledialog.askstring("IS436 G3 Chat", "Choose a username\n(leave blank to use your chat ID):",
                                      parent=root)
        if name is None:            # user pressed Cancel
            root.destroy()
            return

    try:
        sock = protocol.connect_to_server(args.host, port)
    except ConnectionError as error:
        messagebox.showerror("Cannot connect", str(error), parent=root)
        root.destroy()
        sys.exit(1)

    sock.sendall(protocol.encode({"type": "hello", "username": name.strip()}))

    window = ChatWindow(root, sock, args.host, port)
    window.append([(f"Connected to {args.host}:{port}. Type '{config.EXIT_KEYWORD}' or click Leave to exit.",
                    "system")])
    root.deiconify()
    try:
        root.mainloop()
    except KeyboardInterrupt:       # Ctrl+C in the terminal that started the GUI
        window.leave()


if __name__ == "__main__":
    main()
