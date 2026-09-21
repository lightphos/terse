import sqlite3

# Create connection to in-memory database
conn = sqlite3.connect(":memory:")
cursor = conn.cursor()

# Create a table
cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")

# Insert data
cursor.execute("INSERT INTO users (name) VALUES (?)", ("Alice",))

# Query data
cursor.execute("SELECT * FROM users")
print(cursor.fetchall())

# Close connection (database is now deleted)
conn.close()   