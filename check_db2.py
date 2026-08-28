import sqlite3
conn = sqlite3.connect(r'C:\Users\porra\.local\share\opencode\opencode.db')
cursor = conn.cursor()

# Check credential table
cursor.execute('SELECT * FROM credential')
rows = cursor.fetchall()
print('credential:', rows)

# Check account table
cursor.execute('SELECT * FROM account')
rows = cursor.fetchall()
print('account:', rows)

# Check control_account table
cursor.execute('SELECT * FROM control_account')
rows = cursor.fetchall()
print('control_account:', rows)

# Check account_state table
cursor.execute('SELECT * FROM account_state')
rows = cursor.fetchall()
print('account_state:', rows)

conn.close()