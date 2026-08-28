import sqlite3
conn = sqlite3.connect(r'C:\Users\porra\.local\share\opencode\opencode.db')
cursor = conn.cursor()

# Check workspace table
cursor.execute('SELECT * FROM workspace')
rows = cursor.fetchall()
print('workspace:', rows)

# Check project table
cursor.execute('SELECT * FROM project')
rows = cursor.fetchall()
print('project:', rows)

# Check project_directory table
cursor.execute('SELECT * FROM project_directory')
rows = cursor.fetchall()
print('project_directory:', rows)

conn.close()