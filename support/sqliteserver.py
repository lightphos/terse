from pathlib import Path

from sqlite_rx.server import SQLiteServer

def main():
    # Share the same file used by the native Terse database runtime.
    database = Path(__file__).resolve().parents[1] / "terse.db"
    server = SQLiteServer(database=str(database), bind_address="tcp://127.0.0.1:5000")
    server.start()
    server.join()

if __name__ == '__main__':
    main()   
