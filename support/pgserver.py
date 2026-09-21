import pgserver

# Start an embedded Postgres server (data stored in ./pgdata)
db = pgserver.get_server("./pgdata")

# Get a connection URI to use with any driver
uri = db.get_uri()
print(uri)  # e.g. postgresql://postgres@localhost:5432/postgres   