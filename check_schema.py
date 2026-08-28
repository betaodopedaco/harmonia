import sqlite3
conn = sqlite3.connect(r'C:\Users\porra\.local\share\opencode\opencode.db')
cursor = conn.cursor()

cursor.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name="project"')
print(cursor.fetchone())

cursor.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name="session"')
print(cursor.fetchone())

conn.close()