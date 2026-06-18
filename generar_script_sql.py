import sqlite3
import os

db_path = "opsatel.db"
output_sql_path = "importar_todo.sql"

# Schemas mapped to MySQL syntax
TABLE_SCHEMAS = {
    "hoja_de_c__lculo_sin_t__tulo": """CREATE TABLE IF NOT EXISTS `hoja_de_c__lculo_sin_t__tulo` (
  `NUMERO` INT NOT NULL AUTO_INCREMENT,
  `NOMBRE` VARCHAR(255) NULL,
  `CEDULA` VARCHAR(100) NULL,
  `CEDULA_TIPO` VARCHAR(100) NULL,
  `CEDULA_FRONTAL` VARCHAR(500) NULL,
  `CEDULA_POSTERIOR` VARCHAR(500) NULL,
  `CELULAR` VARCHAR(255) NULL,
  `CORREO` VARCHAR(255) NULL,
  `DIRECCION` VARCHAR(1000) NULL,
  `NODO` VARCHAR(255) NULL,
  `PARROQUIA` VARCHAR(255) NULL,
  `PLAN` VARCHAR(255) NULL,
  `FECHA_FIRMA` VARCHAR(50) NULL,
  `ESTADO` VARCHAR(50) DEFAULT 'Pendiente',
  `PUERTO` VARCHAR(100) NULL,
  `ONT` VARCHAR(2000) NULL,
  `SERVICIO` VARCHAR(2000) NULL,
  `BREACH` VARCHAR(2000) NULL,
  `ID_PORT` VARCHAR(200) NULL,
  `SERVICE PORT` VARCHAR(2000) NULL,
  `IP` VARCHAR(50) NULL,
  `DISPOSITIVO` VARCHAR(50) NULL,
  `POTENCIA` VARCHAR(50) NULL,
  `NAP` VARCHAR(50) NULL,
  `UBICACION` VARCHAR(255) NULL,
  `TECNICO` VARCHAR(100) NULL,
  `ACTIVADOR` VARCHAR(100) NULL,
  `RED` VARCHAR(100) NULL,
  `CLAVE` VARCHAR(100) NULL,
  `MAC` VARCHAR(50) NULL,
  `INSTALATION_DATE` VARCHAR(50) NULL,
  `TIEMPO` VARCHAR(50) NULL,
  `ARRIENDA` VARCHAR(50) NULL,
  `CUENTA` VARCHAR(50) NULL,
  `FACTURAS` VARCHAR(100) NULL,
  `INTERNET PAYMENT` VARCHAR(100) NULL,
  `APP` VARCHAR(100) NULL,
  `PAYMENT DATE` VARCHAR(50) NULL,
  `CLIENT PAYMENT DATE` VARCHAR(50) NULL,
  `BANK` VARCHAR(50) NULL,
  `COD` VARCHAR(50) NULL,
  `PLUS` VARCHAR(50) NULL,
  `BANK_PLUS` VARCHAR(50) NULL,
  `ADICIONAL` VARCHAR(255) NULL,
  `PLUS_PAGADO` DECIMAL(10,2) DEFAULT 0.00,
  `ADICIONAL_PAGADO` DECIMAL(10,2) DEFAULT 0.00,
  `COMENTARIOS` VARCHAR(2000) NULL,
  `OBSERVACIONES` VARCHAR(2000) NULL,
  `NOTAS_PAGO` VARCHAR(2000) NULL,
  `TERCERA_EDAD` TINYINT(1) DEFAULT 0,
  `PRECIO_PLAN_ESPECIAL` DECIMAL(10,2) DEFAULT 0.00,
  `PAGO_MENSUAL` DECIMAL(10,2) DEFAULT 0.00,
  `TOTAL_PAGO` DECIMAL(10,2) DEFAULT 0.00,
  `SALDO` DECIMAL(10,2) DEFAULT 0.00,
  `IPTV_ACTIVAR` TINYINT(1) DEFAULT 0,
  `IPTV_USER` VARCHAR(255) NULL,
  `IPTV_PASS` VARCHAR(255) NULL,
  `IPTV_BOUQUETS` VARCHAR(255) NULL,
  `IPTV_EXP_DATE` VARCHAR(100) NULL,
  `IPTV_MAX_CONN` INT DEFAULT 0,
  `IPTV_OUTPUTS` VARCHAR(1255) NULL,
  `IPTV_NOTES` VARCHAR(2000) NULL,
  `IPTV_MEMBER_ID` INT DEFAULT 1,
  PRIMARY KEY (`NUMERO`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "historial_pagos": """CREATE TABLE IF NOT EXISTS `historial_pagos` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `cliente_id` INT NULL,
  `monto` DECIMAL(10,2) NULL,
  `fecha_pago` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `metodo_pago` VARCHAR(50) NULL,
  `mes_correspondiente` VARCHAR(20) NULL,
  `referencia` VARCHAR(100) NULL,
  `monto_internet` DECIMAL(10,2) DEFAULT 0.00,
  `monto_plus` DECIMAL(10,2) DEFAULT 0.00,
  `monto_adicional` DECIMAL(10,2) DEFAULT 0.00,
  PRIMARY KEY (`id`),
  FOREIGN KEY (`cliente_id`) REFERENCES `hoja_de_c__lculo_sin_t__tulo` (`NUMERO`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "reportes_mensuales": """CREATE TABLE IF NOT EXISTS `reportes_mensuales` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `mes_anio` VARCHAR(20) NULL,
  `fecha_generacion` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `archivo_ruta_excel` VARCHAR(255) NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "usuarios": """CREATE TABLE IF NOT EXISTS `usuarios` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(50) UNIQUE NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `rol` VARCHAR(20) NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "nodos": """CREATE TABLE IF NOT EXISTS `nodos` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) UNIQUE NOT NULL,
  `base_ip` VARCHAR(50) DEFAULT '172.16',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "planes_internet": """CREATE TABLE IF NOT EXISTS `planes_internet` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) UNIQUE NOT NULL,
  `megas` INT DEFAULT 100,
  `precio` DECIMAL(10,2) DEFAULT 0.00,
  `pantallas` INT DEFAULT 1,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "bancos": """CREATE TABLE IF NOT EXISTS `bancos` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) UNIQUE NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "puertos": """CREATE TABLE IF NOT EXISTS `puertos` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) NULL,
  `nodo_id` INT NULL,
  `limite_ip` VARCHAR(100) DEFAULT '2 al 129',
  `limite_device` VARCHAR(100) DEFAULT '0 al 127',
  `limite_service_port` VARCHAR(100) DEFAULT '0 al 127',
  PRIMARY KEY (`id`),
  FOREIGN KEY (`nodo_id`) REFERENCES `nodos` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "finanzas_base": """CREATE TABLE IF NOT EXISTS `finanzas_base` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `caja_chica` DECIMAL(10,2) DEFAULT 0.00,
  `pichincha` DECIMAL(10,2) DEFAULT 0.00,
  `jep` DECIMAL(10,2) DEFAULT 0.00,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "parroquias": """CREATE TABLE IF NOT EXISTS `parroquias` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(100) UNIQUE NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "clientes_extras": """CREATE TABLE IF NOT EXISTS `clientes_extras` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `cod` VARCHAR(50) NULL,
  `nombre_cliente` VARCHAR(255) NULL,
  `contacto` VARCHAR(255) NULL,
  `proveedor` VARCHAR(255) NULL,
  `usuario` VARCHAR(255) NULL,
  `contrasena` VARCHAR(255) NULL,
  `cuentas` VARCHAR(50) NULL,
  `mac_smart_one` VARCHAR(100) NULL,
  `observaciones` TEXT NULL,
  `estado` VARCHAR(50) NULL,
  `valor` DECIMAL(10,2) DEFAULT 0.00,
  `activo` VARCHAR(10) DEFAULT 'SI',
  `fecha_ingreso` VARCHAR(50) NULL,
  `saldo_pendiente` DECIMAL(10,2) DEFAULT 0.00,
  `total_pagado` DECIMAL(10,2) DEFAULT 0.00,
  `enero_factura` VARCHAR(100) NULL,
  `enero_fecha_a_pagar` VARCHAR(50) NULL,
  `enero_fecha_pago` VARCHAR(50) NULL,
  `enero_pago` DECIMAL(10,2) DEFAULT 0.00,
  `enero_banco` VARCHAR(100) NULL,
  `enero_cod` VARCHAR(100) NULL,
  `enero_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `febrero_factura` VARCHAR(100) NULL,
  `febrero_fecha_a_pagar` VARCHAR(50) NULL,
  `febrero_fecha_pago` VARCHAR(50) NULL,
  `febrero_pago` DECIMAL(10,2) DEFAULT 0.00,
  `febrero_banco` VARCHAR(100) NULL,
  `febrero_cod` VARCHAR(100) NULL,
  `febrero_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `marzo_factura` VARCHAR(100) NULL,
  `marzo_fecha_a_pagar` VARCHAR(50) NULL,
  `marzo_fecha_pago` VARCHAR(50) NULL,
  `marzo_pago` DECIMAL(10,2) DEFAULT 0.00,
  `marzo_banco` VARCHAR(100) NULL,
  `marzo_cod` VARCHAR(100) NULL,
  `marzo_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `abril_factura` VARCHAR(100) NULL,
  `abril_fecha_a_pagar` VARCHAR(50) NULL,
  `abril_fecha_pago` VARCHAR(50) NULL,
  `abril_pago` DECIMAL(10,2) DEFAULT 0.00,
  `abril_banco` VARCHAR(100) NULL,
  `abril_cod` VARCHAR(100) NULL,
  `abril_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `mayo_factura` VARCHAR(100) NULL,
  `mayo_fecha_a_pagar` VARCHAR(50) NULL,
  `mayo_fecha_pago` VARCHAR(50) NULL,
  `mayo_pago` DECIMAL(10,2) DEFAULT 0.00,
  `mayo_banco` VARCHAR(100) NULL,
  `mayo_cod` VARCHAR(100) NULL,
  `mayo_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `junio_factura` VARCHAR(100) NULL,
  `junio_fecha_a_pagar` VARCHAR(50) NULL,
  `junio_fecha_pago` VARCHAR(50) NULL,
  `junio_pago` DECIMAL(10,2) DEFAULT 0.00,
  `junio_banco` VARCHAR(100) NULL,
  `junio_cod` VARCHAR(100) NULL,
  `junio_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `julio_factura` VARCHAR(100) NULL,
  `julio_fecha_a_pagar` VARCHAR(50) NULL,
  `julio_fecha_pago` VARCHAR(50) NULL,
  `julio_pago` DECIMAL(10,2) DEFAULT 0.00,
  `julio_banco` VARCHAR(100) NULL,
  `julio_cod` VARCHAR(100) NULL,
  `julio_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `agosto_factura` VARCHAR(100) NULL,
  `agosto_fecha_a_pagar` VARCHAR(50) NULL,
  `agosto_fecha_pago` VARCHAR(50) NULL,
  `agosto_pago` DECIMAL(10,2) DEFAULT 0.00,
  `agosto_banco` VARCHAR(100) NULL,
  `agosto_cod` VARCHAR(100) NULL,
  `agosto_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `septiembre_factura` VARCHAR(100) NULL,
  `septiembre_fecha_a_pagar` VARCHAR(50) NULL,
  `septiembre_fecha_pago` VARCHAR(50) NULL,
  `septiembre_pago` DECIMAL(10,2) DEFAULT 0.00,
  `septiembre_banco` VARCHAR(100) NULL,
  `septiembre_cod` VARCHAR(100) NULL,
  `septiembre_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `octubre_factura` VARCHAR(100) NULL,
  `octubre_fecha_a_pagar` VARCHAR(50) NULL,
  `octubre_fecha_pago` VARCHAR(50) NULL,
  `octubre_pago` DECIMAL(10,2) DEFAULT 0.00,
  `octubre_banco` VARCHAR(100) NULL,
  `octubre_cod` VARCHAR(100) NULL,
  `octubre_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `noviembre_factura` VARCHAR(100) NULL,
  `noviembre_fecha_a_pagar` VARCHAR(50) NULL,
  `noviembre_fecha_pago` VARCHAR(50) NULL,
  `noviembre_pago` DECIMAL(10,2) DEFAULT 0.00,
  `noviembre_banco` VARCHAR(100) NULL,
  `noviembre_cod` VARCHAR(100) NULL,
  `noviembre_saldo` DECIMAL(10,2) DEFAULT 0.00,
  `diciembre_factura` VARCHAR(100) NULL,
  `diciembre_fecha_a_pagar` VARCHAR(50) NULL,
  `diciembre_fecha_pago` VARCHAR(50) NULL,
  `diciembre_pago` DECIMAL(10,2) DEFAULT 0.00,
  `diciembre_banco` VARCHAR(100) NULL,
  `diciembre_cod` VARCHAR(100) NULL,
  `diciembre_saldo` DECIMAL(10,2) DEFAULT 0.00,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "historial_pagos_extras": """CREATE TABLE IF NOT EXISTS `historial_pagos_extras` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `cliente_id` INT NULL,
  `monto` DECIMAL(10,2) NULL,
  `fecha_pago` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `metodo_pago` VARCHAR(50) NULL,
  `mes_correspondiente` VARCHAR(20) NULL,
  `referencia` VARCHAR(100) NULL,
  `factura` VARCHAR(100) NULL,
  PRIMARY KEY (`id`),
  FOREIGN KEY (`cliente_id`) REFERENCES `clientes_extras` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "hoja_ruta": """CREATE TABLE IF NOT EXISTS `hoja_ruta` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `fecha` VARCHAR(50) NULL,
  `tecnico` VARCHAR(100) NULL,
  `hora` VARCHAR(50) NULL,
  `cliente_id` INT NULL,
  `nombre_cliente` VARCHAR(255) NULL,
  `ubicacion_cliente` VARCHAR(255) NULL,
  `celular_cliente` VARCHAR(255) NULL,
  `ubicacion_caja` VARCHAR(255) NULL,
  `actividad` VARCHAR(255) NULL,
  `observacion` VARCHAR(2000) NULL,
  `observacion_tecnico` VARCHAR(2000) NULL,
  `parroquia` VARCHAR(100) NULL,
  `estado` VARCHAR(50) DEFAULT 'Pendiente',
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  FOREIGN KEY (`cliente_id`) REFERENCES `hoja_de_c__lculo_sin_t__tulo` (`NUMERO`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "tickets_desarrollo": """CREATE TABLE IF NOT EXISTS `tickets_desarrollo` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `titulo` VARCHAR(255) NOT NULL,
  `contenido` TEXT NOT NULL,
  `estado` VARCHAR(50) DEFAULT 'Pendiente',
  `autor` VARCHAR(100) NOT NULL,
  `fecha_creacion` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "call_center_tickets": """CREATE TABLE IF NOT EXISTS `call_center_tickets` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `cliente_nombre` VARCHAR(255) NULL,
  `fecha_ingreso` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `ip` VARCHAR(50) NULL,
  `direccion` VARCHAR(255) NULL,
  `telefono` VARCHAR(255) NULL,
  `registrado_por` VARCHAR(100) NULL,
  `estado` VARCHAR(50) DEFAULT 'PENDIENTE',
  `a_cargo` VARCHAR(100) NULL,
  `problema` TEXT NULL,
  `observacion_revision` TEXT NULL,
  `fecha_cambio_estado` VARCHAR(50) NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "egresos_balance": """CREATE TABLE IF NOT EXISTS `egresos_balance` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `descripcion` VARCHAR(255) NOT NULL,
  `categoria` VARCHAR(100) DEFAULT 'operacional',
  `monto` DECIMAL(10,2) DEFAULT 0.00,
  `subcategoria` VARCHAR(150) NULL,
  `fecha` VARCHAR(50) NULL,
  `mes` VARCHAR(20) NULL,
  `metodo_pago` VARCHAR(100) DEFAULT 'Efectivo',
  `notas` TEXT NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "proyectos_balance": """CREATE TABLE IF NOT EXISTS `proyectos_balance` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `nombre` VARCHAR(255) NOT NULL,
  `descripcion` TEXT NULL,
  `monto_total` DECIMAL(10,2) DEFAULT 0.00,
  `monto_invertido` DECIMAL(10,2) DEFAULT 0.00,
  `estado` VARCHAR(50) DEFAULT 'En progreso',
  `fecha_inicio` VARCHAR(50) NULL,
  `fecha_fin` VARCHAR(50) NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "proyecto_pagos": """CREATE TABLE IF NOT EXISTS `proyecto_pagos` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `proyecto_id` INT NULL,
  `item` INT DEFAULT 1,
  `descripcion` VARCHAR(255) NULL,
  `fecha` VARCHAR(50) NULL,
  `tipo_pago` VARCHAR(100) DEFAULT 'Pichincha',
  `valor` DECIMAL(10,2) DEFAULT 0.00,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  FOREIGN KEY (`proyecto_id`) REFERENCES `proyectos_balance` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "gastos_proyecto": """CREATE TABLE IF NOT EXISTS `gastos_proyecto` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `proyecto_id` INT NULL,
  `subcategoria` VARCHAR(150) NULL,
  `item` INT DEFAULT 1,
  `descripcion` VARCHAR(255) NULL,
  `fecha` VARCHAR(50) NULL,
  `tipo_pago` VARCHAR(150) DEFAULT 'Pichincha',
  `valor` DECIMAL(10,2) DEFAULT 0.00,
  `pendiente` TINYINT(1) DEFAULT 0,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  FOREIGN KEY (`proyecto_id`) REFERENCES `proyectos_balance` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "colchon_balance": """CREATE TABLE IF NOT EXISTS `colchon_balance` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `descripcion` VARCHAR(255) NOT NULL,
  `monto` DECIMAL(10,2) DEFAULT 0.00,
  `fecha` VARCHAR(50) NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "gastos_fijos_balance": """CREATE TABLE IF NOT EXISTS `gastos_fijos_balance` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `descripcion` VARCHAR(255) NOT NULL,
  `monto` DECIMAL(10,2) DEFAULT 0.00,
  `categoria` VARCHAR(100) DEFAULT 'operacional',
  `metodo_pago` VARCHAR(100) DEFAULT 'Efectivo',
  `activo` TINYINT(1) DEFAULT 1,
  `notas` TEXT NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "asistencias": """CREATE TABLE IF NOT EXISTS `asistencias` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `usuario_id` INT NULL,
  `nombre_usuario` VARCHAR(100) NULL,
  `fecha` VARCHAR(50) NULL,
  `hora_entrada` VARCHAR(50) NULL,
  `ubicacion` VARCHAR(255) NULL,
  `distancia_metros` FLOAT NULL,
  `hora_salida` VARCHAR(50) NULL,
  `ubicacion_salida` VARCHAR(255) NULL,
  `distancia_metros_salida` FLOAT NULL,
  `biometria_salida_validada` TINYINT(1) DEFAULT 0,
  `dispositivo_info` VARCHAR(255) NULL,
  `biometria_validada` TINYINT(1) DEFAULT 0,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  FOREIGN KEY (`usuario_id`) REFERENCES `usuarios` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "whatsapp_historial": """CREATE TABLE IF NOT EXISTS `whatsapp_historial` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `numero_destino` VARCHAR(50) NOT NULL,
  `mensaje` TEXT NOT NULL,
  `tipo_envio` VARCHAR(50) DEFAULT 'manual',
  `estado` VARCHAR(50) DEFAULT 'enviado',
  `fecha_envio` VARCHAR(50) NULL,
  `fecha_creacion` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;""",

    "whatsapp_configuracion": """CREATE TABLE IF NOT EXISTS `whatsapp_configuracion` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `hora_programada` VARCHAR(10) NOT NULL,
  `mensaje_programado` TEXT NOT NULL,
  `activo` TINYINT(1) DEFAULT 1,
  `enviar_a_todos` TINYINT(1) DEFAULT 1,
  `fecha_programada` DATETIME NULL,
  `recurrencia` VARCHAR(50) DEFAULT 'diario',
  `job_id` VARCHAR(200) NULL,
  `fecha_creacion` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""
}

def escape_string(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    # Convert to string and escape single quotes
    val_str = str(val).replace("'", "''").replace("\\", "\\\\")
    return f"'{val_str}'"

def dump():
    print(f"Buscando base de datos SQLite en: {db_path}")
    if not os.path.exists(db_path):
        print(f"Error: No se encontró el archivo {db_path}. ¿Está en el directorio correcto?")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get list of tables in sqlite
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    sqlite_tables = [t[0] for t in cursor.fetchall() if not t[0].startswith("sqlite_")]

    with open(output_sql_path, "w", encoding="utf-8") as f:
        # Initial settings
        f.write("-- RESPALDO DE BASE DE DATOS OPSATEL\n")
        f.write("CREATE DATABASE IF NOT EXISTS `opsatel`;\n")
        f.write("USE `opsatel`;\n\n")
        f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")

        # Write CREATE TABLE schemas first
        for table in sqlite_tables:
            if table in TABLE_SCHEMAS:
                f.write(f"-- Estructura de tabla para `{table}`\n")
                f.write(TABLE_SCHEMAS[table])
                f.write("\n\n")
            else:
                # If table is not pre-defined, try to get raw schema from sqlite (as fallback)
                cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}';")
                sql = cursor.fetchone()[0]
                # Try simple type replacements for MySQL
                sql = sql.replace("AUTOINCREMENT", "AUTO_INCREMENT")
                sql = sql.replace("DATETIME", "DATETIME DEFAULT CURRENT_TIMESTAMP")
                f.write(f"-- Estructura de tabla autogenerada para `{table}`\n")
                f.write(sql + ";\n\n")

        # Write INSERT statements
        for table in sqlite_tables:
            print(f"Exportando datos de la tabla `{table}`...")
            # Get columns
            cursor.execute(f"PRAGMA table_info(`{table}`)")
            cols = [c[1] for c in cursor.fetchall()]
            cols_str = ", ".join([f"`{c}`" for c in cols])

            # Get rows
            cursor.execute(f"SELECT * FROM `{table}`")
            rows = cursor.fetchall()
            
            if rows:
                f.write(f"-- Volcado de datos para la tabla `{table}`\n")
                # Group inserts in batches to avoid query size limits
                batch_size = 100
                for i in range(0, len(rows), batch_size):
                    batch = rows[i:i+batch_size]
                    values_list = []
                    for row in batch:
                        vals = ", ".join([escape_string(v) for v in row])
                        values_list.append(f"({vals})")
                    
                    insert_sql = f"INSERT INTO `{table}` ({cols_str}) VALUES \n" + ",\n".join(values_list) + ";\n"
                    f.write(insert_sql)
                f.write("\n")
        
        f.write("SET FOREIGN_KEY_CHECKS = 1;\n")
        
    print(f"\n¡Proceso completado exitosamente!")
    print(f"Se ha generado el archivo '{output_sql_path}' con la estructura y los datos.")
    conn.close()

if __name__ == "__main__":
    dump()
