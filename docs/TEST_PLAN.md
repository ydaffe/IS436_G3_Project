# Test Plan

Run every command from the project folder. Use a separate terminal window for the server and for each client. Port `5050` is used as the example. On Windows, use `py` instead of `python` if needed.

The **Expected** column says what should happen. If anything prints a Python `Traceback`, the test fails.

---

## 1. Invalid ports

| # | Command | Expected |
|---|---|---|
| 1.1 | `python server.py abc` | `Error: the port must be a whole number, but got 'abc'.` plus a usage line. Exit code 1. |
| 1.2 | `python server.py 80` | `Error: the port must be between 1025 and 65535, but got 80.` |
| 1.3 | `python server.py 1024` | Rejected. 1024 is below the range. |
| 1.4 | `python server.py 65536` | Rejected. 65536 is above the range. |
| 1.5 | `python server.py 50.5` | Rejected. The port must be a whole number. |
| 1.6 | `python server.py` | argparse usage error: the port is missing. |
| 1.7 | `python server.py 1025` and `python server.py 65535` | Both accepted, because the range includes both edges. Stop each with `/quit`. |
| 1.8 | `python client.py 99999` and `python client_gui.py abc` | Same clear error, exit code 1, no window opens. |
| 1.9 | Start `python server.py 5050`, then run `python server.py 5050` in a second terminal | The second server prints `Error: cannot listen on 127.0.0.1:5050 ... Is another program already using that port?` |

Check the exit code in PowerShell with `$LASTEXITCODE` (`echo $?` in bash). It should be `1`.

## 2. Normal single-client chat

1. Run `python server.py 5050`. The server prints the address it's listening on, the log file path, and how to stop it.
2. Run `python client.py 5050` and enter `Alice`.
   - The client banner says **Type 'exit' (or press Ctrl+C) to leave the chat.**
   - Then: `[HH:MM:SS] *** Welcome to the IS436 G3 chat server! You are Client-1. 1 user(s) online. Type 'exit' to leave the chat.`
   - Then: `*** Alice (Client-1) joined the chat. Say hi!`
   - The server console shows `[+] Client-1 connected from 127.0.0.1:xxxxx` and the join line.
3. Type `hello` in the client. Both the client and the server show `[HH:MM:SS] Alice (Client-1): hello`.
4. Type `hi Alice` at the server console. The client shows `[HH:MM:SS] Server: hi Alice`.
5. Type `exit` in the client. The client prints `You have left the chat. Goodbye!` and returns to the prompt. The server shows `*** Alice (Client-1) left the chat.`

## 3. Multiple clients

1. With the server running, start three clients: CLI `Alice`, CLI `Bob`, and GUI `Carol` (`python client_gui.py 5050`).
2. Each client gets a different chat ID (`Client-1`, `Client-2`, `Client-3`). Each new join is announced to everyone already in the chat.
3. Alice sends a message. Bob, Carol and the server console all see it with Alice's ID and the same timestamp.
4. Carol sends from the GUI. Her own messages appear in blue, others in green, and Server messages in orange.
5. At the server console, `/users` lists all three.
6. Start two clients that both use the name `Alice`. Both are allowed, and the chat IDs tell them apart (`Alice (Client-4)` and `Alice (Client-5)`).

## 4. A client quits abruptly

1. With Alice and Bob connected, **close Bob's terminal window** with the X button, or end the `python` process in Task Manager.
2. Expected: the server and Alice see `*** Bob (Client-2) lost connection.` (or `disconnected.`). The server keeps running, with no traceback.
3. Alice can keep chatting, and `/users` no longer lists Bob.
4. Repeat with a GUI client, using Task Manager to end its process. The result should be the same.
5. Close the GUI window with its X button. That counts as a normal leave: `... left the chat.`

## 5. The server quits while clients are connected

**Using the console command:**

1. Connect Alice (CLI) and Carol (GUI).
2. Type `/quit` (or `shutdown`) at the server console.
3. The server prints `Shutting down: notifying clients...` and `Server stopped. Goodbye!`, exits with code 0, and shows no traceback.
4. The CLI client shows `*** The server is shutting down. Goodbye!` and then `*** Disconnected from the server. Press Enter to exit.` Pressing Enter closes it cleanly.
5. The GUI client shows the shutdown message in red, then `Disconnected from the server`. The text box and Send button are disabled, and Leave changes to **Close**.

**Using Ctrl+C:** repeat the steps above, but press Ctrl+C in the server terminal. The result should be the same, with `Ctrl+C pressed.` printed and no traceback. The server may take up to 1 second to notice, because of the accept timeout.

**Restart:** run `python server.py 5050` again immediately. It should start without an "address in use" error.

## 6. Message limits

| # | Action | Expected |
|---|---|---|
| 6.1 | Press Enter on an empty line | Nothing is sent. |
| 6.2 | Type only spaces and press Enter | Only the sender sees, in red in the GUI, `Empty messages are not sent - type something first.` Nobody else sees anything. |
| 6.3 | Paste a message longer than 500 characters | Only the sender sees `Your message is N characters long; the limit is 500. It was not sent.` The GUI counter turns red above 500. |
| 6.4 | Send exactly 500 characters | Delivered normally. |
| 6.5 | Type ` EXIT ` (uppercase, with spaces around it) | The client leaves. The exit keyword ignores case and surrounding spaces. |

## 7. Chat history on join

1. Send a few messages, then connect a new client.
2. The new client sees `--- Last N message(s) before you joined ---`, followed by up to 10 earlier messages with their original timestamps and senders, then `--- End of chat history ---`.
3. Stop the server, start it again, and connect a client. The history from before the restart is still shown, because it is loaded from `logs/chat_log.jsonl`.

## 8. Logging and database

1. Open `logs/chat_log.jsonl`. It should contain one JSON line per chat message, join, leave, `Server started` and `Server stopped`.
2. Optionally, inspect the database:
   ```
   python -c "import sqlite3; c=sqlite3.connect('db/chat.db'); print(c.execute('select * from connection_sessions').fetchall())"
   ```
   After a shutdown, every session has a `disconnected_at` time, and every user's status is `offline`.

## 9. Typing indicator (GUI)

1. Open two GUI clients, `Carol` and `Dan`.
2. Start typing in Carol's window without pressing Enter. Dan's window shows `Carol (Client-x) is typing...`. Carol's own window doesn't.
3. Stop typing for 2 seconds. The indicator disappears.
4. Type again and press Enter. The indicator disappears as soon as the message arrives.
5. While two people type at once, the indicator reads `A and B are typing...`.

## 10. Special cases

| # | Case | Expected |
|---|---|---|
| 10.1 | Start a client with no server running | `Error: Could not connect to 127.0.0.1:5050 - the connection was refused. Is the chat server running on port 5050?` The GUI shows the same text in an error box. |
| 10.2 | Use a username longer than 20 characters | The CLI asks again. The GUI and `--name` cut the name to 20 characters. |
| 10.3 | Use a blank username | The chat ID is used as the name, for example `Client-4`. |
| 10.4 | Send emoji or accented text (`café ☕ 😀`) | The text displays correctly on every client and in the log. |
| 10.5 | Send messages quickly from two clients at once | Every message arrives whole, never mixed together. |
| 10.6 | Connect with a raw TCP tool, such as `telnet 127.0.0.1 5050` (if installed), and type text | The raw client is welcomed with a JSON line, and its plain text is treated as chat. Typing `exit` leaves. |
| 10.7 | Run the server with `--host 0.0.0.0` and connect from another computer with `--host <server-ip>` | Works across the network. You may need to allow Python through the firewall. |
