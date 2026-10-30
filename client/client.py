"""Chat client: connects to the server, sends what you type, prints what others say.

Run:  python client/client.py [host] [port]
"""
import socket
import sys
import threading

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5050
ENCODING = "utf-8"


def receive_loop(sock):
    reader = sock.makefile("r", encoding=ENCODING)
    for line in reader:
        print(line.rstrip("\n"))
    print("Disconnected from server.")


def main():
    username = input("Username: ").strip()
    sock = socket.create_connection((HOST, PORT))
    sock.sendall((username + "\n").encode(ENCODING))

    threading.Thread(target=receive_loop, args=(sock,), daemon=True).start()
    print(f"Connected to {HOST}:{PORT}. Type messages, /quit to exit.")

    try:
        while True:
            text = input()
            sock.sendall((text + "\n").encode(ENCODING))
            if text == "/quit":
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
