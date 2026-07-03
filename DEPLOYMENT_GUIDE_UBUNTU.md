# OPSATEL OLT Provisioning System - Deployment Guide (Ubuntu)

## 📋 Requisitos Previos

- Ubuntu 20.04 LTS o superior
- MySQL 8.0+ o MariaDB 10.5+
- Python 3.8+
- Acceso root o sudo
- OLT Huawei con Telnet habilitado
- Espacio mínimo: 2GB

## 🔧 Paso 1: Preparación del Sistema

### 1.1 Actualizar sistema
```bash
sudo apt-get update
sudo apt-get upgrade -y
```

### 1.2 Instalar dependencias del sistema
```bash
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    git \
    mysql-client-core-8.0 \
    libmysqlclient-dev \
    python3-dev \
    gcc \
    curl \
    wget
```

### 1.3 Crear usuario de servicio
```bash
sudo useradd -m -s /bin/bash -d /home/opsatel opsatel
sudo usermod -aG sudo opsatel
```

### 1.4 Crear directorios necesarios
```bash
sudo mkdir -p /home/opsatel/Opsatel-Backend
sudo mkdir -p /var/log/opsatel
sudo mkdir -p /var/run/opsatel
sudo mkdir -p /home/opsatel/.config

sudo chown -R opsatel:opsatel /home/opsatel
sudo chown -R opsatel:opsatel /var/log/opsatel
sudo chown -R opsatel:opsatel /var/run/opsatel

sudo chmod 755 /var/log/opsatel
sudo chmod 755 /var/run/opsatel
```

## 📦 Paso 2: Deploy del Código

### 2.1 Copiar código backend
```bash
# Desde tu máquina local (o servidor de deployment)
git clone https://github.com/tuorg/Opsatel-Backend.git /tmp/opsatel-deploy
sudo cp -r /tmp/opsatel-deploy/* /home/opsatel/Opsatel-Backend/
sudo chown -R opsatel:opsatel /home/opsatel/Opsatel-Backend
```

### 2.2 Crear virtual environment
```bash
cd /home/opsatel/Opsatel-Backend
python3 -m venv venv
source venv/bin/activate
```

### 2.3 Instalar dependencias Python
```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

## 🗄️ Paso 3: Configuración de Base de Datos

### 3.1 Configurar archivo .env
```bash
cp .env.production /home/opsatel/.env
nano /home/opsatel/.env

# Editar estos valores con tus datos reales:
# DATABASE_URL
# OLT_BAÑOS_HOST, OLT_BAÑOS_PASSWORD
# OLT_SAYAUSI_HOST, OLT_SAYAUSI_PASSWORD
# WORKER_LOG_FILE (verificar permisos)
```

### 3.2 Ejecutar migrations SQL
```bash
# Conectar a MySQL
mysql -h localhost -u root -p opsatel < migrations/001_create_olt_tables.sql

# Verificar que las tablas se crearon
mysql -h localhost -u root -p opsatel -e "SHOW TABLES LIKE 'olt%';"
```

### 3.3 Insertar configuración OLT inicial
```bash
# Por CLI o via phpmyadmin:
# INSERT INTO olt_config (nombre, host, port, username, password, nodo_asociado, active)
# VALUES ('huawei-baños', '192.168.1.100', 23, 'admin', 'admin123', 'BAÑOS', 1);
```

## 🔌 Paso 4: Instalar Systemd Service

### 4.1 Copiar archivo de servicio
```bash
sudo cp /home/opsatel/Opsatel-Backend/deployment/opsatel-olt-worker.service \
    /etc/systemd/system/opsatel-olt-worker.service

sudo systemctl daemon-reload
```

### 4.2 Habilitar servicio
```bash
# Permitir que el servicio inicie automáticamente
sudo systemctl enable opsatel-olt-worker.service

# Iniciar el servicio
sudo systemctl start opsatel-olt-worker.service

# Verificar status
sudo systemctl status opsatel-olt-worker.service
```

### 4.3 Verificar logs
```bash
# Ver logs en tiempo real
sudo journalctl -u opsatel-olt-worker.service -f

# Ver logs últimas 50 líneas
sudo journalctl -u opsatel-olt-worker.service -n 50

# Ver logs desde hace 30 minutos
sudo journalctl -u opsatel-olt-worker.service --since "30 min ago"

# Ver logs en archivo
tail -f /var/log/opsatel/olt-worker.log
```

## ✅ Paso 5: Verificación

### 5.1 Probar conexión OLT
```bash
# En la terminal del servidor
cd /home/opsatel/Opsatel-Backend
source venv/bin/activate
python3

# En el intérprete Python:
from services.olt_interface import OLTInterface

olt = OLTInterface(
    host="192.168.1.100",  # IP de tu OLT
    username="admin",
    password="admin123",
    timeout=30
)

if olt.connect():
    print("✓ Conexión OLT exitosa")
    response = olt.send_command("display ont info 0/0/1 1")
    print(response)
    olt.disconnect()
else:
    print("✗ Fallo la conexión")
```

### 5.2 Probar sanitizador
```python
from services.command_sanitizer import CommandSanitizer

mac = CommandSanitizer.validate_mac("AA:BB:CC:DD:EE:FF")
print(f"MAC validado: {mac}")

ip = CommandSanitizer.validate_ip_address("172.16.1.100")
print(f"IP validada: {ip}")
```

### 5.3 Verificar tareas en BD
```sql
SELECT id, cliente_id, action, status, created_at FROM olt_tasks LIMIT 5;
SELECT COUNT(*) as tareas_pendientes FROM olt_tasks WHERE status = 'pending';
```

## 🚀 Paso 6: Backend FastAPI (Opcional, si no está en otro host)

### 6.1 Instalar gunicorn
```bash
pip install gunicorn uvicorn
```

### 6.2 Crear systemd service para backend
```bash
sudo tee /etc/systemd/system/opsatel-backend.service > /dev/null <<EOF
[Unit]
Description=OPSATEL Backend API
After=network.target mysql.service

[Service]
Type=notify
User=opsatel
WorkingDirectory=/home/opsatel/Opsatel-Backend
EnvironmentFile=/home/opsatel/.env
ExecStart=/home/opsatel/Opsatel-Backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable opsatel-backend.service
sudo systemctl start opsatel-backend.service
```

## 🔍 Troubleshooting

## 🧭 Paso 7: Frontend (Opsatel-Frontend) - build y ruta de Activación

1. Copiar la carpeta `Opsatel-Frontend` al servidor web o construirla y servirla detrás de Nginx:

```bash
cd /home/opsatel/Opsatel-Frontend
npm install
npm run build
sudo cp -r dist/* /var/www/opsatel-frontend/
```

2. Verificar que la ruta `/activacion` esté registrada en la SPA (ya se añadió `src/pages/Activacion.jsx` y la ruta en `src/App.jsx`).

3. Si el backend está en otro host, configurar CORS en FastAPI para permitir el origen del frontend.

4. Probar desde el navegador accediendo a `https://<your-domain>/activacion` y autenticarse como `tecnico`.


### Problema: "ModuleNotFoundError: No module named 'netmiko'"
```bash
source /home/opsatel/Opsatel-Backend/venv/bin/activate
pip install netmiko
```

### Problema: "No connection to OLT"
```bash
# Verificar conectividad a OLT
ping -c 4 192.168.1.100
telnet 192.168.1.100 23

# Revisar logs
tail -f /var/log/opsatel/olt-worker.log | grep "CONNECTION\|ERROR"
```

### Problema: "Permission denied" en log file
```bash
sudo chown opsatel:opsatel /var/log/opsatel/olt-worker.log
sudo chmod 644 /var/log/opsatel/olt-worker.log
```

### Problema: "Lock already acquired"
```bash
# Solo una instancia del worker puede correr. Si hay crash:
rm /var/run/opsatel-olt-worker.lock
sudo systemctl restart opsatel-olt-worker.service
```

## 📊 Monitoreo en Producción

### Ver status del worker
```bash
sudo systemctl is-active opsatel-olt-worker.service
sudo systemctl is-enabled opsatel-olt-worker.service
```

### Métricas útiles
```sql
-- Tareas procesadas hoy
SELECT COUNT(*) FROM olt_tasks WHERE DATE(completed_at) = CURDATE();

-- Tasa de éxito
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as exitosas,
    ROUND(100 * SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) / COUNT(*), 2) as porcentaje_exito
FROM olt_tasks
WHERE DATE(created_at) = CURDATE();

-- Errores más comunes
SELECT error_code, COUNT(*) as cantidad
FROM olt_tasks
WHERE status = 'failed'
GROUP BY error_code
ORDER BY cantidad DESC;
```

### Backup automático
```bash
# Crear script de backup
sudo tee /usr/local/bin/opsatel-backup.sh > /dev/null <<'EOF'
#!/bin/bash
BACKUP_DIR="/var/backups/opsatel"
mkdir -p $BACKUP_DIR
mysqldump -u root -p opsatel | gzip > $BACKUP_DIR/opsatel-$(date +%Y%m%d-%H%M%S).sql.gz
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete  # Borrar backups mayores a 7 días
EOF

sudo chmod +x /usr/local/bin/opsatel-backup.sh

# Agregar a crontab para backup diario
sudo crontab -e
# Añadir línea:
# 0 2 * * * /usr/local/bin/opsatel-backup.sh
```

## 🔐 Producción Checklist

- [ ] .env configurado con credenciales reales
- [ ] OLT accesible vía Telnet desde el servidor
- [ ] Logs con permisos correctos
- [ ] Systemd service habilitado y running
- [ ] Database backups configurados
- [ ] Firewall permite puerto MySQL (si remoto)
- [ ] Firewall permite puerto Telnet OLT (23)
- [ ] SELinux deshabilitado o configurado para Opsatel
- [ ] Python venv activado en paths correctos
- [ ] Testing: crear tarea de prueba y verificar queue
- [ ] Monitoreo activo (Prometheus, ELK, Grafana)
- [ ] Alertas configuradas para fallos de worker

## 📞 Support & Escalation

Si hay problemas:
1. Revisar logs: `/var/log/opsatel/olt-worker.log`
2. Verificar status: `sudo systemctl status opsatel-olt-worker`
3. Test OLT: `telnet <OLT-IP> 23`
4. Validar BD: `SELECT * FROM olt_tasks WHERE status = 'failed' LIMIT 5;`

---

**Versión:** 1.0.0
**Última actualización:** 2026-07-02
**Autor:** Arquitecto de Software Senior - OPSATEL
