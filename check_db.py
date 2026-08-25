import sqlite3
conn = sqlite3.connect('opsatel.db')
c = conn.cursor()
c.execute("SELECT id, nombre, total_pago, saldo, plus, `INTERNET PAYMENT` FROM clientes WHERE nombre LIKE '%GUAMAN YUNGA%'")
print(c.fetchall())
