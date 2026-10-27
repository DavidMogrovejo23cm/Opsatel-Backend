# 📘 DOCUMENTACIÓN TÉCNICA Y OPERATIVA - BACKEND OPSATEL

Documento maestro de especificación de arquitectura, lógica de negocio, modelo de datos y operación del sistema backend de **Opsatel**.

---

## 1. Visión General del Sistema

El backend de **Opsatel** es el núcleo de cómputo, almacenamiento y orquestación del ISP. Proporciona una interfaz RESTful robusta y asíncrona construida sobre **FastAPI**, interactuando con una base de datos relacional **MySQL** a través de **SQLAlchemy ORM**.

Sus responsabilidades esenciales comprenden:
*   **Gestión del Ciclo de Vida del Cliente:** Registro, validación geográfica, cálculo algorítmico de red, aprovisionamiento en OLT, facturación y suspensión/reactivación.
*   **Aprovisionamiento de Infraestructura GPON:** Cálculo de colisiones de red, secuenciación de puertos PON y generación de comandos nativos para OLTs Huawei.
*   **Contabilidad y Tesorería Independiente:** Aislamiento estricto de conceptos de facturación (Internet recurrente, Plus IPTV y cargos Adicionales extraordinarios).
*   **Soporte al Cliente y Operaciones de Campo (CRM & Field Dispatch):** Módulo de Call Center integrado de forma bidireccional con la Hoja de Ruta técnica, con control de SLA y expiración automática de tareas tras 24 horas.
*   **Automatización de Mensajería y Bot Asistente:** Pasarela de comunicación bidireccional con WhatsApp para recordatorios de pago y soporte automatizado con Inteligencia Artificial.
*   **Integridad de Datos y Respaldos:** Creación y restauración validada de volcados SQL sin interrupción del servicio.

---

## 2. Pila Tecnológica y Dependencias

*   **Lenguaje de Programación:** Python 3.10+
*   **Framework Web:** FastAPI 0.100+
*   **Servidor ASGI:** Uvicorn con soporte de workers asíncronos
*   **Capa ORM:** SQLAlchemy 2.0+
*   **Base de Datos Relacional:** MySQL 8.0 / MariaDB 10.5+ (con soporte transaccional InnoDB)
*   **Seguridad:** PyJWT, Passlib (algoritmo Bcrypt para hashing seguro de credenciales)
*   **Análisis y Reportes:** Pandas y Openpyxl para generación de hojas de cálculo de cierres mensuales
*   **Procesamiento de Lenguaje Natural (IA):** API de Anthropic Claude para extracción estructurada de datos no formateados
*   **Bridge de Mensajería:** Node.js 18+ con `whatsapp-web.js` para conexión de sesión web

---

## 3. Modelo Relacional de Base de Datos

```text
+------------------------------------+          +------------------------------------+
|              Cliente               |          |                Pago                |
| (hoja_de_c__lculo_sin_t__tulo)     |          |         (historial_pagos)          |
+------------------------------------+          +------------------------------------+
| id (PK)                            | 1      * | id (PK)                            |
| cedula (Index)                     |<---------| cliente_id (FK)                    |
| nombres, apellidos                 |          | monto_total                        |
| telefono, correo                   |          | monto_internet                     |
| direccion, coordenadas_gps         |          | monto_plus                         |
| nodo, puerto, id_port              |          | monto_adicional                    |
| service_port, ip, mac              |          | metodo_pago (Efectivo/Pichincha...) |
| plan, precio_plan, plus            |          | referencia, cortesia_mode          |
| saldo, pago_mensual, adicional     |          | fecha_pago, registrado_por         |
| estado (Pendiente/Activo/Cortado)  |          +------------------------------------+
| tiempo, fecha_firma, foto_cedula   |
+------------------------------------+
         | 1                      | 1
         |                        |
         | *                      | *
+--------------------+   +------------------------------------+
|  CallCenterTicket  |   |              HojaRuta              |
+--------------------+   +------------------------------------+
| id (PK)            |   | id (PK)                            |
| cliente_id (FK)    |   | cliente_id (FK, Nullable)          |
| nombres_reporte    | 1 | callcenter_ticket_id (FK, Nullable)|<---+
| telefono_contacto  |---| tecnico_responsable                |    |
| motivo_llamada     |   | fecha, hora, tipo_actividad        |    |
| prioridad, estado  | * | estado (Pendiente/Completado...)   |----+
| resolucion         |   | observaciones, created_at          |
+--------------------+   +------------------------------------+
```

### Entidades Secundarias y Catálogos:
*   **`Usuario`:** Credenciales del sistema (`id`, `username`, `hashed_password`, `rol`, `is_active`).
*   **`Nodo`:** Zonas geográficas de distribución (`id`, `nombre`, `prefijo_ip`, `descripcion`).
*   **`Puerto`:** Puertos GPON asignados por cada nodo (`id`, `nodo_id`, `numero_puerto`).
*   **`PlanInternet`:** Planes comerciales (`id`, `nombre`, `velocidad_mbps`, `precio_mensual`).
*   **`Banco`:** Cuentas autorizadas (`id`, `nombre`, `numero_cuenta`, `titular`).
*   **`FinanzasBase`:** Registros de caja inicial (`caja_chica_base`, `banco_pichincha_base`, `coop_jep_base`).
*   **`Asistencia`:** Control laboral (`empleado_nombre`, `tipo_registro`, `timestamp`).
*   **`ClienteExtra` / `PagoExtra`:** Registro contable paralelo para contratos temporales o servicios especiales.

---

## 4. Control de Acceso Basado en Roles (RBAC)

El middleware de seguridad valida en cada solicitud el token Bearer JWT y contrasta el campo `rol` del usuario contra los permisos definidos en el endpoint:

| Rol | Privilegios y Alcance |
| :--- | :--- |
| **`administrador`** | Control total sin restricciones. Gestión de usuarios, facturación mensual global, cierres de ciclo, configuración de nodos/planes/bancos, respaldos de base de datos y eliminación permanente de registros. |
| **`secretario`** | Gestión operativa comercial y de cobranza. Alta de prospectos, cobro y registro de pagos desglosados, consulta de clientes, gestión de tickets de call center y emisión de reportes. |
| **`tecnico`** | Aprovisionamiento técnico en campo. Visualización y cambio de estados en Hoja de Ruta, cálculo de parámetros técnicos (IP, ONT ID, Service Port), generación de scripts OLT Huawei y visualización de tickets de averías. Al ingresar al sistema, es canalizado por defecto a la agenda de campo. |
| **`instalador`** | Funciones de despliegue físico y conexión de acometidas de fibra en el domicilio del cliente. |

---

## 5. Algoritmos y Reglas de Negocio Clave

### A. Algoritmo de Cálculo Técnico (Aprovisionamiento GPON)
Ubicación: `routes/clientes.py -> @router.get("/siguiente-valor-tecnico")`
1.  **ONT ID (`id_port`):** Se realiza una consulta agregada `SELECT MAX(id_port) FROM clientes WHERE nodo = :nodo AND puerto = :puerto`. El valor devuelto es incrementado en 1 para garantizar que dentro de un mismo puerto PON nunca existan dos ONTs con el mismo identificador.
2.  **Service Port:** La OLT Huawei exige que los identificadores de servicio (`service-port`) sean únicos en todo el chasis. Se ejecuta `SELECT MAX(service_port) FROM clientes` en toda la base y se asigna el valor subsiguiente.
3.  **Dirección IP:** Utilizando el prefijo IP configurado para el nodo (ejemplo: `172.16`), se genera la IP dinámica con la convención:
    $$\text{IP} = \text{prefijo} \,.\, \text{numero\_puerto} \,.\, (\text{id\_port} + 1)$$
4.  **Generación de Comandos CLI:** Se construyen las directivas Huawei para asociar el perfil de línea, el puerto de servicio y la VLAN correspondiente al plan contratado.

### B. Separación Contable del Cargo "Adicional"
Ubicación: `routes/clientes.py -> @router.post("/{id}/pagar")`
*   El modelo `Pago` persiste de forma aislada las cantidades:
    *   `monto_internet`: Descuenta la deuda de mensualidades atrasadas o actuales del cliente.
    *   `monto_plus`: Cubre el costo de servicios de streaming / IPTV.
    *   `monto_adicional`: Liquida exclusivamente valores por venta de routers, cables o traslados.
*   **Regla de Negocio:** Un abono realizado a un concepto adicional **no reduce** la deuda acumulada de mensualidades de internet, evitando que clientes suspendidos por falta de pago sean reactivados fraudulentamente sin pagar su servicio de conectividad.

### C. Normalización y Extracción con Inteligencia Artificial
Ubicación: `routes/clientes.py -> @router.post("/parse-smart")`
*   Técnica de procesamiento con **Anthropic Claude**:
    1.  El backend extrae los nombres válidos de Nodos, Planes y Parroquias desde la base de datos MySQL en tiempo real.
    2.  Envía el texto crudo pegado por el usuario al modelo con instrucciones estrictas de extracción JSON.
    3.  Limpia cédulas ecuatorianas asegurando 10 dígitos (añadiendo ceros iniciales si el portapapeles los omitió).
    4.  Mapea variaciones coloquiales ("nodo los baños", "plan 50") al registro oficial correspondiente.

### D. Ciclo de SLA y Auto-Expiración en Hoja de Ruta
Ubicación: `routes/hoja_ruta.py -> @router.get("/")`
*   Cada vez que se solicita la lista de tareas de campo, se ejecuta una transacción previa en la base de datos:
    *   Registros con `created_at <= (NOW() - 24 horas)` que mantengan estado `Pendiente` o `En proceso` son actualizados automáticamente a `No completado`.
    *   Si el registro carece de `created_at`, se evalúa el campo `fecha` contra la fecha actual del servidor.
*   Esto previene que órdenes de servicio desatendidas queden ocultas en el flujo de trabajo diario.

### E. Integración Call Center -> Hoja de Ruta
Ubicación: `routes/callcenter.py -> @router.post("/tickets/{id}/agendar-hoja-ruta")`
*   Permite a la secretaria o agente de soporte convertir con un solo clic un reclamo telefónico en una orden de trabajo de campo.
*   Crea el registro en la tabla `hoja_ruta` vinculando la clave foránea `callcenter_ticket_id`, permitiendo trazabilidad bidireccional entre la llamada de reclamo y la solución en el domicilio del cliente.

---

## 6. Módulos y Enrutadores REST

| Módulo / Archivo | Prefijo de Ruta | Responsabilidad Principal |
| :--- | :--- | :--- |
| `routes/auth.py` | `/auth` | Autenticación de usuarios, tokens JWT, roles y altas de operadores |
| `routes/clientes.py` | `/clientes` | Núcleo de clientes, estados, pagos, aprovisionamiento OLT y facturación |
| `routes/balance.py` | `/balance` | Consolidación contable de ingresos por bancos, caja chica y registro de egresos |
| `routes/callcenter.py` | `/callcenter` | CRM de incidentes telefónicos, categorización y derivación técnica |
| `routes/hoja_ruta.py` | `/hoja-ruta` | Despacho de personal de campo, cronograma de visitas y SLA de 24h |
| `routes/asistencia.py` | `/asistencia` | Marcación biométrica/digital de ingreso y egreso de trabajadores |
| `routes/backup.py` | `/backup` | Volcados SQL automáticos, descarga y restauración con validación de integridad |
| `routes/whatsapp.py` | `/whatsapp` | Monitoreo del socket web, código QR y orquestación de campañas masivas |
| `routes/extras.py` | `/extras` | Gestión paralela de clientes y cobranzas especiales |
| `routes/bulk_activation.py`| `/bulk-activation` | Procesamiento en lote para activación de ONTs detectadas |
| `routes/olt_tasks.py` | `/olt` | Envío asíncrono de comandos directos al chasis OLT |
| `routes/discovery.py` | `/discovery` | Sondeo de equipos no configurados en puertos PON |
| `routes/libreqos.py` | `/libreqos` | Sincronización con el motor de conformación de tráfico y colas FQ_CoDel |
| `routes/caja.py` | `/caja` | Arqueo físico diario de efectivo en caja |
| `rutas_configuraciones.py`| `/configuraciones`| Catálogo de Nodos, Puertos, Planes, Bancos y fondos de arranque financiero |

---

## 7. Mantenimiento y Operación

### Procedimiento de Sincronización de Base de Datos
Si se introducen nuevos campos o modelos en `models.py`:
```bash
# Ejecutar el sincronizador automático
python sync_db.py
```
Este script analiza las diferencias entre los metadatos de SQLAlchemy y las tablas en MySQL, ejecutando las sentencias `ALTER TABLE` necesarias sin afectar la información existente.

### Respaldo y Restauración de Emergencia
Los respaldos se almacenan en el directorio `backups/` con formato de fecha y hora:
*   **Creación manual por terminal:**
    ```bash
    mysqldump -u root -p opsatel > backups/backup_manual_$(date +%Y%m%d_%H%M%S).sql
    ```
*   **Restauración por API:** Disponible a través de `POST /backup/restaurar` subiendo el archivo `.sql` validado.

---

*Documento de especificación técnica del Backend Opsatel.*
