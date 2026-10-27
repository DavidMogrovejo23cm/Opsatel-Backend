# ⚙️ OPSATEL BACKEND - MOTOR CENTRAL Y API REST ISP

Plataforma backend de alto rendimiento para la gestión integral de proveedores de servicios de internet (**ISP**). Desarrollada en **Python** con **FastAPI**, **SQLAlchemy** y **MySQL**, integrando aprovisionamiento automatizado de infraestructura GPON (Huawei OLT), control de calidad de servicio (LibreQoS), contabilidad independiente de cobros, asistente inteligente con IA y pasarela de mensajería automatizada por WhatsApp.

---

## 📑 Tabla de Contenidos
1. [Arquitectura y Tecnologías](#-arquitectura-y-tecnologías)
2. [Estructura del Proyecto](#-estructura-del-proyecto)
3. [Instalación y Configuración](#-instalación-y-configuración)
4. [Modelo de Datos y Base de Datos (MySQL)](#-modelo-de-datos-y-base-de-datos-mysql)
5. [Lógica de Negocio y Algoritmos Centrales](#-lógica-de-negocio-y-algoritmos-centrales)
6. [Catálogo Completo de Rutas y Endpoints](#-catálogo-completo-de-rutas-y-endpoints)
7. [Automatizaciones y Servicios Asíncronos](#-automatizaciones-y-servicios-asíncronos)
8. [Scripts de Mantenimiento y Utilidades](#-scripts-de-mantenimiento-y-utilidades)
9. [Guía de Despliegue en Producción](#-guía-de-despliegue-en-producción)

---

## 🛠️ Arquitectura y Tecnologías

| Componente | Tecnología | Rol en la Plataforma |
| :--- | :--- | :--- |
| **Framework Web** | FastAPI (Python 3.10+) | API REST asíncrona, validación estricta y Swagger OpenAPI interactivo |
| **Servidor ASGI** | Uvicorn / Gunicorn | Procesamiento concurrente de peticiones HTTP en tiempo real |
| **Base de Datos** | MySQL 8.0 / MariaDB | Motor relacional con integridad referencial e índices optimizados |
| **ORM** | SQLAlchemy | Mapeo objeto-relacional y construcción declarativa de consultas |
| **Validación de Datos** | Pydantic v2 | Tipado estricto, serialización y validación de esquemas JSON |
| **Seguridad** | PyJWT + Passlib (Bcrypt) | Autenticación sin estado basada en JWT con control de roles (RBAC) |
| **Procesamiento de Datos** | Pandas + Openpyxl | Generación y transformación de reportes contables en Excel |
| **IA Generativa** | Anthropic Claude API | Normalización y extracción estructurada de contratos desde texto crudo |
| **Bridge WhatsApp** | Node.js + whatsapp-web.js | Interfaz sin navegador para envíos masivos y recepción de mensajes |
| **Control de Ancho de Banda** | Integración LibreQoS | Sincronización de reglas FQ_CoDel / CAKE para gestión de tráfico |

---

## 📂 Estructura del Proyecto

```text
Opsatel-Backend/
├── main.py                     # Punto de entrada de la aplicación, CORS, middlewares y registro de routers
├── database.py                 # Configuración de pool de conexiones MySQL y sesión SQLAlchemy
├── models.py                   # Modelos de base de datos principales (Clientes, Pagos, Usuarios, Nodos, etc.)
├── models_olt_extension.py     # Extensiones para equipos OLT, tarjetas y puertos PON
├── discovery_models.py         # Tablas para descubrimiento y auto-asignación de dispositivos de red
├── inventory_models.py         # Modelos para inventario físico de ONTs, routers y suministros
├── libreqos_models.py          # Esquemas de integración de shaper y colas de ancho de banda
├── schemas.py                  # Modelos Pydantic para validación de entrada/salida de la API
├── auth_utils.py               # Generación, firma y verificación de tokens JWT, hashing Bcrypt
├── config_manager.py           # Gestor unificado de configuraciones de entorno y credenciales
├── scheduler.py                # Tareas programadas en segundo plano (facturación, expiraciones, backups)
├── observability.py            # Monitoreo de salud del sistema, métricas de rendimiento y logging
├── system_prompt.py            # Prompts y contexto del sistema para la capa de Inteligencia Artificial
├── ai_tools.py                 # Definición de herramientas de consulta automática para el bot con IA
├── chatbot_service.py          # Lógica conversacional y enrutamiento del asistente virtual
├── sam_bot_service.py          # Motor avanzado de atención al cliente automatizada por WhatsApp
├── whatsapp_service.py         # Servicio Python para encolado y control de envíos de mensajería
├── whatsapp_bridge.js          # Proceso Node.js que conecta con la librería whatsapp-web.js (QR y sockets)
├── workflow_engine.py          # Orquestador de flujos de trabajo técnicos y transiciones de estado
├── huawei_discovery.py         # Conector SSH/Telnet para consultas y comandos en OLT Huawei
├── resource_manager.py         # Administrador de recursos de hardware y almacenamiento en disco
├── routes/                     # Controladores modulares de la API REST (20 routers)
│   ├── auth.py                 # Inicio de sesión, registro y perfil de usuarios
│   ├── clientes.py             # Controlador principal: CRUD, estados, pagos, scripts OLT y reportes
│   ├── balance.py              # Auditoría contable, conciliación bancaria y gastos
│   ├── callcenter.py           # Gestión de tickets CRM y atención al cliente
│   ├── hoja_ruta.py            # Agenda técnica de campo y auto-expiración de visitas a las 24h
│   ├── asistencia.py           # Marcaciones de entrada/salida del personal
│   ├── extras.py               # Gestión comercial y financiera de clientes y cobros extras
│   ├── backup.py               # Creación, descarga y restauración de respaldos SQL
│   ├── whatsapp.py             # Control de campañas masivas, estado del bridge y código QR
│   ├── bulk_activation.py      # Flujo de activación masiva de dispositivos
│   ├── olt_tasks.py            # Ejecución asíncrona de comandos GPON en la OLT
│   ├── discovery.py            # Descubrimiento de ONTs en línea no registradas
│   ├── libreqos.py             # Sincronización y sincronismo de perfiles de ancho de banda
│   ├── caja.py                 # Control de arqueo de caja chica diaria
│   ├── tickets.py              # Gestión administrativa centralizada de incidentes
│   ├── peliculas.py            # Catálogo complementario de entretenimiento / IPTV
│   ├── sync.py                 # Sincronización de datos entre bases distribuidas
│   └── workflows.py            # Definición y disparo de workflows automáticos
├── rutas_configuraciones.py     # CRUD de Nodos, Planes, Bancos, Puertos y Finanzas Base
├── sync_db.py                  # Script para sincronizar nuevas columnas de SQLAlchemy con MySQL
├── create_users.py             # Inicializador de usuarios administrativos por defecto
├── seed_configuraciones.py     # Carga de catálogo inicial (Nodos Baños/Sayausí, Planes, Puertos)
├── wait-for-db.py              # Verificador de disponibilidad de la base de datos para Docker
├── requirements.txt            # Dependencias de paquetes Python
├── package.json                # Dependencias Node.js para el bridge de WhatsApp
├── Dockerfile                  # Contenedor Docker para ejecución del backend
└── docker-compose.yml          # Orquestación de servicios (FastAPI, MySQL, Bridge)
```

---

## ⚙️ Instalación y Configuración

### Requisitos del Entorno
*   **Python**: 3.10 o superior (con soporte para tipos de unión `|`).
*   **MySQL**: Versión 8.0 o MariaDB 10.5+.
*   **Node.js**: Versión 18+ (necesario únicamente si se ejecuta el bridge de WhatsApp).

### 1. Entorno Virtual y Dependencias de Python
```bash
# Navegar a la carpeta del backend
cd Opsatel-Backend

# Crear el entorno virtual
python -m venv venv

# Activar en Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# O en Linux/macOS
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 2. Dependencias del Bridge de WhatsApp
```bash
npm install
```

### 3. Configuración de Variables de Entorno (`.env`)
Crear o editar el archivo `.env` en la raíz de `Opsatel-Backend`:
```env
# Conexión a Base de Datos MySQL
DB_USER=root
DB_PASSWORD=tu_contraseña
DB_HOST=localhost
DB_PORT=3306
DB_NAME=opsatel

# Seguridad JWT
JWT_SECRET=tu_clave_secreta_super_segura_opsatel_2026
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Credenciales OLT Huawei (Opcional para aprovisionamiento directo)
OLT_HOST=192.168.100.1
OLT_USER=admin
OLT_PASSWORD=tu_clave_olt

# Inteligencia Artificial (Anthropic Claude)
ANTHROPIC_API_KEY=sk-ant-api03-...

# Servidor
PORT=8000
DEBUG=False
```

### 4. Inicialización y Migración de Datos
```bash
# 1. Asegurar que las columnas del modelo existan en la base de datos
python sync_db.py

# 2. Crear los usuarios iniciales del sistema (Admin, Técnico, Secretario)
python create_users.py

# 3. Cargar catálogo base de Nodos, Planes y Puertos
python seed_configuraciones.py
```

### 5. Puesta en Marcha
```bash
# Iniciar servidor con recarga en caliente
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
*   **API Base:** [http://localhost:8000](http://localhost:8000)
*   **Documentación Interactiva (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
*   **Especificación OpenAPI:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## 🗄️ Modelo de Datos y Base de Datos (MySQL)

El motor relacional está modelado mediante SQLAlchemy en `models.py` y extensiones modulares:

### 1. Entidad Principal: `Cliente` (`hoja_de_c__lculo_sin_t__tulo`)
*   **Identificación:** `id`, `cedula` (indexada), `nombres`, `apellidos`, `telefono`, `correo`, `direccion`, `referencia_direccion`, `coordenadas_gps`.
*   **Ubicación de Red:** `nodo` (relación a catálogo), `parroquia`, `puerto` (relación a puerto de nodo).
*   **Datos Técnicos:** `ip` (dirección estática asignada), `mac`, `id_port` (ONT ID secuencial por puerto), `service_port` (puerto de servicio global único), `script_olt` (comandos generados), `potencia_nap` (dBm), `bridge` (modo router o bridge).
*   **Datos Comerciales y Financieros:** `plan` (nombre del plan), `precio_plan`, `plus` (valor IPTV/adicional mensual), `saldo` (deuda pendiente acumulada), `pago_mensual` (total abonado en el ciclo actual), `adicional` (cargo extraordinario temporal), `corte` (estado de suspensión).
*   **Contrato y Ciclo de Vida:** `estado` (`Pendiente`, `En Activación`, `Activo`, `Cortado`, `Retirado`), `tiempo` (duración del contrato en meses), `fecha_firma` (fecha de alta), `foto_cedula_path` (enlace al archivo digital).

### 2. Entidad: `Usuario`
*   `id`, `username`, `hashed_password`, `nombre_completo`, `rol` (`administrador`, `secretario`, `tecnico`, `instalador`), `is_active`, `created_at`.

### 3. Entidad: `Pago` (`historial_pagos`)
*   `id`, `cliente_id` (FK), `monto_total`, `monto_internet` (abono al plan recurrente), `monto_plus` (abono a servicio IPTV), `monto_adicional` (abono a cargos extraordinarios independientes), `metodo_pago` (Efectivo, Pichincha, JEP), `referencia`, `cortesia_mode` (`NONE`, `CORTESIA_COMPLETA`), `fecha_pago`, `registrado_por`.

### 4. Entidad: `HojaRuta`
*   `id`, `cliente_id` (FK opcional), `callcenter_ticket_id` (FK opcional), `tecnico_responsable`, `fecha`, `hora`, `tipo_actividad` (Instalación, Reparación, Retiro, Inspección), `estado` (`Pendiente`, `En proceso`, `Completado`, `No completado`), `observaciones`, `created_at`.

### 5. Entidad: `CallCenterTicket`
*   `id`, `cliente_id` (FK), `nombres_reporte`, `telefono_contacto`, `motivo_llamada`, `prioridad` (`Baja`, `Media`, `Alta`, `Urgente`), `estado` (`Abierto`, `En Proceso`, `Solucionado`, `Cancelado`), `resolucion`, `created_at`.

### 6. Entidades de Catálogo y Finanzas
*   `Nodo`: `id`, `nombre`, `prefijo_ip` (ej: `172.16`), `descripcion`.
*   `Puerto`: `id`, `nodo_id` (FK), `numero_puerto`, `descripcion`.
*   `PlanInternet`: `id`, `nombre`, `velocidad_mbps`, `precio_mensual`.
*   `Banco`: `id`, `nombre`, `numero_cuenta`, `titular`.
*   `FinanzasBase`: `id`, `caja_chica_base`, `banco_pichincha_base`, `coop_jep_base`, `actualizado_el`.
*   `Asistencia`: `id`, `empleado_nombre`, `tipo_registro` (`ENTRADA`, `SALIDA`), `timestamp`, `observacion`.

---

## 🧠 Lógica de Negocio y Algoritmos Centrales

### A. Aprovisionamiento GPON y Cálculo de Parámetros Técnicos
Al momento de aprovisionar un cliente (`GET /clientes/siguiente-valor-tecnico`):
1.  **ONT ID (`id_port`):** Se consulta el valor máximo de `id_port` para los clientes asignados al mismo `nodo` y al mismo `puerto`. El nuevo valor es `MAX(id_port) + 1` (empezando en 0 o 1 según la configuración del puerto).
2.  **Service Port:** Para evitar colisiones en la OLT Huawei, se consulta el valor máximo global de `service_port` en toda la base de datos de clientes y se incrementa en `+1`.
3.  **Dirección IP:** Se toma el `prefijo_ip` del nodo (por ejemplo `172.16`), el número de puerto físico y se calcula:
    $$\text{IP} = \text{prefijo\_ip} \cdot \text{puerto} \cdot (\text{id\_port} + 1)$$
4.  **Generación de Scripts:** Se ensamblan dinámicamente las cadenas CLI Huawei:
    ```text
    interface gpon 0/{slot}
    ont add {puerto} {id_port} sn-auth "{sn}" omci ont-lineprofile-name {perfil} ont-srvprofile-name {perfil}
    ont port native-vlan {puerto} {id_port} eth 1 vlan {vlan} priority 0
    quit
    service-port {service_port} vlan {vlan} gpon 0/{slot}/{puerto} ont {id_port} gemport 1 multi-service user-vlan {vlan} tag-transform translate
    ```

### B. Independencia Contable del Cargo "Adicional"
*   Históricamente, en sistemas ISP los cargos extras (costo de router, bobina de cable, traslados) solían mezclarse con la deuda recurrente de internet, provocando que un cliente con corte de servicio pagara un adicional y el sistema le reactivara erróneamente el internet.
*   **Regla Opsatel:** La columna `monto_adicional` en los pagos y el campo `adicional` en el cliente son contablemente independientes de `total_pago` y `saldo`. Al liquidar un valor adicional, este no reduce la deuda recurrente ni elimina el estado de suspensión hasta que se cancelen las mensualidades debidas.

### C. Clasificación Inteligente de Prospectos con IA (`/clientes/parse-smart`)
*   Se utiliza un modelo de lenguaje de Anthropic Claude integrado en `ai_tools.py` y `system_prompt.py`.
*   El backend recupera dinámicamente la lista oficial de nodos, parroquias y planes registrados en MySQL y los pasa como restricciones al modelo.
*   El texto no estructurado enviado por el usuario se normaliza:
    *   Cédula ecuatoriana: Se extraen los 10 dígitos numéricos, agregando el cero inicial si fue omitido.
    *   Teléfono: Formato estándar celular de 10 dígitos (`09...`).
    *   Fuzzy Mapping: Transforma variaciones como "plan 30 megas" o "la 30" al ID exacto del plan en catálogo.

### D. Ciclo Mensual de Facturación y Cierre
1.  **Facturación Mensual Global (`POST /clientes/facturacion-mensual-global`):**
    *   Itera sobre todos los clientes en estado `Activo`.
    *   Suma al `saldo` de cada cliente el valor de su `precio_plan` más el valor mensual de `plus` (IPTV).
2.  **Cierre de Mes:**
    *   Resetea el campo `pago_mensual` a `0.00` para todos los abonados, dejando intacto el `saldo` acumulado pendiente.
    *   Genera un archivo Excel analítico con el desglose de lo cobrado durante el mes mediante Pandas y lo almacena en `rutas_reportes/`.

### E. Auto-Expiración de Hoja de Ruta (SLA de Campo)
*   En cada consulta a `/hoja-ruta/`, el sistema ejecuta una verificación automática de vencimiento:
    *   Cualquier tarea con estado `Pendiente` o `En proceso` cuya fecha y hora de creación supere las **24 horas** de antigüedad se actualiza automáticamente a estado `No completado`.
    *   Esto garantiza que los trabajos no atendidos por los técnicos se auditen inmediatamente y no queden flotando indefinidamente.

---

## 📡 Catálogo Completo de Rutas y Endpoints

### 1. Autenticación (`/auth`)
*   `POST /auth/login`: Autentica credenciales y genera el token Bearer JWT con los claims del usuario.
*   `POST /auth/register`: Creación de nuevos usuarios del sistema (restringido a `administrador`).
*   `GET /auth/me`: Retorna los datos y privilegios del usuario autenticado actual.
*   `GET /auth/usuarios`: Lista todos los operadores del sistema.
*   `DELETE /auth/usuarios/{id}`: Da de baja a un usuario del sistema.

### 2. Gestión de Clientes (`/clientes`)
*   `GET /clientes/`: Lista todos los abonados con soporte para filtros por estado, nodo y búsqueda de texto.
*   `POST /clientes/`: Registra un nuevo prospecto de cliente con validación de datos.
*   `GET /clientes/{id}`: Obtiene el expediente completo de un cliente específico.
*   `PUT /clientes/{id}`: Actualización integral de los datos del abonado.
*   `DELETE /clientes/{id}`: Traslada al cliente a la papelera (soft-delete).
*   `GET /clientes/siguiente-valor-tecnico`: Calcula automáticamente el siguiente `id_port`, `service_port` e IP disponible para un nodo y puerto.
*   `PATCH /clientes/{id}/configuracion-tecnica`: Guarda los datos definitivos de instalación y activa al cliente.
*   `POST /clientes/{id}/pagar`: Registra un pago desglosado (Internet, IPTV, Adicional) con selección de banco.
*   `POST /clientes/facturacion-mensual-global`: Ejecuta el cargo masivo mensual a todos los clientes activos.
*   `POST /clientes/cierre-mes`: Ejecuta el cierre del ciclo financiero mensual.
*   `POST /clientes/parse-smart`: Extrae datos estructurados desde texto libre utilizando IA.
*   `POST /clientes/{id}/subir-cedula`: Almacena la fotografía del documento de identidad en `uploads/`.

### 3. Configuraciones del Sistema (`/configuraciones`)
*   `GET /configuraciones/nodos` | `POST` | `PUT /{id}` | `DELETE /{id}`: Catálogo de nodos e IPs base.
*   `GET /configuraciones/planes` | `POST` | `PUT /{id}` | `DELETE /{id}`: Catálogo de planes y anchos de banda.
*   `GET /configuraciones/puertos` | `POST` | `PUT /{id}` | `DELETE /{id}`: Puertos físicos por nodo.
*   `GET /configuraciones/bancos` | `POST` | `PUT /{id}` | `DELETE /{id}`: Entidades bancarias autorizadas.
*   `GET /configuraciones/finanzas-base`: Obtiene los fondos base de arranque en bancos y caja chica.
*   `POST /configuraciones/finanzas-base`: Actualiza los valores base para el cálculo de liquidez global.

### 4. Balance y Tesorería (`/balance`)
*   `GET /balance/resumen`: Retorna el balance consolidado entre ingresos desglosados y egresos.
*   `GET /balance/ingresos-bancos`: Desglose detallado de recaudación en Pichincha, JEP y Efectivo.
*   `POST /balance/gastos`: Registro de un nuevo egreso u orden de compra.
*   `GET /balance/gastos`: Historial de gastos con filtros de fecha y categoría.

### 5. Call Center y Mesa de Ayuda (`/callcenter`)
*   `GET /callcenter/tickets`: Lista todos los reportes de incidentes recibidos.
*   `POST /callcenter/tickets`: Registra una nueva llamada o reclamo de un cliente.
*   `PUT /callcenter/tickets/{id}`: Actualiza el estado o resolución del ticket.
*   `POST /callcenter/tickets/{id}/agendar-hoja-ruta`: Convierte automáticamente el ticket en una orden de trabajo programada en la Hoja de Ruta.

### 6. Agenda de Campo (`/hoja-ruta`)
*   `GET /hoja-ruta/`: Obtiene la lista de tareas ordenadas por fecha y hora, ejecutando previamente el auto-cierre de 24h.
*   `POST /hoja-ruta/`: Asigna una nueva visita a un técnico responsable.
*   `PATCH /hoja-ruta/{id}/estado`: Modifica el estado del trabajo (`Completado`, `No completado`, etc.).
*   `DELETE /hoja-ruta/{id}`: Cancela o elimina la orden técnica.

### 7. Control de Asistencia (`/asistencia`)
*   `GET /asistencia/`: Consulta las marcas de asistencia registradas por fecha y empleado.
*   `POST /asistencia/marcar`: Registra una nueva marca de entrada o salida con validación de hora.

### 8. Mensajería WhatsApp (`/whatsapp`)
*   `GET /whatsapp/status`: Informa si el bridge de Node.js está conectado y autenticado.
*   `GET /whatsapp/qr`: Retorna el código QR en Base64 para emparejar la sesión con un teléfono móvil.
*   `POST /whatsapp/enviar-mensaje`: Envía un mensaje individual directo a un número celular.
*   `POST /whatsapp/campana-masiva`: Encola un comunicado o recordatorio de cobro a un grupo de clientes.
*   `POST /whatsapp/cancelar-todos-envios`: Detiene de emergencia cualquier campaña masiva en curso.

### 9. Respaldos y Base de Datos (`/backup`)
*   `GET /backup/listar`: Muestra los archivos `.sql` generados históricamente en `backups/`.
*   `POST /backup/crear`: Dispara la creación de un nuevo volcado SQL completo con timestamp.
*   `GET /backup/descargar/{nombre_archivo}`: Descarga un volcado localmente.
*   `POST /backup/restaurar`: Restaura la base de datos a partir de un volcado SQL validado.

### 10. Gestión de Servicios Extras (`/extras`)
*   Controladores completos para el catálogo, altas y cobranzas de servicios complementarios (`ClienteExtra`, `PagoExtra`).

---

## 🤖 Automatizaciones y Servicios Asíncronos

### 1. Planificador de Tareas (`scheduler.py`)
Utiliza tareas asíncronas para ejecutar procesos críticos sin intervención humana:
*   **Revisión de SLA de Visitas Técnicas:** Evaluación recurrente de órdenes vencidas en la Hoja de Ruta.
*   **Limpieza de Archivos Temporales:** Depuración periódica de reportes exportados antiguos y logs rotados.
*   **Respaldos Automáticos:** Programación de copias de seguridad de la base de datos MySQL en horas de bajo tráfico.

### 2. Motor de Mensajería WhatsApp (`whatsapp_service.py` y `whatsapp_bridge.js`)
*   El archivo `whatsapp_bridge.js` ejecuta una instancia sin cabeza de Chromium a través de `whatsapp-web.js`.
*   Mantiene los sockets locales para comunicar el estado de la sesión al backend FastAPI.
*   **Algoritmo Anti-Baneo:** Implementa intervalos aleatorios de espera (entre 3 y 8 segundos) entre envíos masivos para prevenir bloqueos de la línea corporativa.

### 3. Asistente Virtual Inteligente (`sam_bot_service.py`)
*   Procesa los mensajes entrantes de clientes en WhatsApp.
*   Identifica el remitente en la base de datos de clientes por su número de teléfono.
*   Responde consultas sobre valores a pagar, estado del servicio, cuentas bancarias autorizadas y toma de reclamos básicos, transfiriendo a un operador humano en caso de problemas complejos.

---

## 🛠️ Scripts de Mantenimiento y Utilidades

En la raíz del proyecto se encuentran herramientas para administración del sistema:
*   `sync_db.py`: Compara los modelos declarados en SQLAlchemy con las tablas reales de MySQL y añade columnas faltantes sin perder información.
*   `create_users.py`: Crea o restablece las cuentas iniciales (`admin`, `tecnico`, `secretario`).
*   `seed_configuraciones.py`: Carga los nodos territoriales primarios, velocidades y puertos de prueba.
*   `reconciliar_extras.py`: Corrige posibles discrepancias contables en la tabla de clientes extras.
*   `force_fix.py`: Script de contingencia para resolver bloqueos de sesión o índices duplicados en la base de datos.

---

## 🚀 Guía de Despliegue en Producción

### 1. Despliegue con Docker Compose
El proyecto incluye un archivo `docker-compose.yml` que levanta la arquitectura completa:
```bash
# Construir y levantar contenedores en segundo plano
docker-compose up -d --build

# Ver logs del backend
docker-compose logs -f backend
```

### 2. Despliegue en Servidor Linux (Ubuntu 22.04 LTS / 24.04 LTS)

#### A. Crear Servicio Systemd para FastAPI (`/etc/systemd/system/opsatel-backend.service`)
```ini
[Unit]
Description=Opsatel FastAPI Backend Service
After=network.target mysql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/opsatel/Opsatel-Backend
Environment="PATH=/var/www/opsatel/Opsatel-Backend/venv/bin"
ExecStart=/var/www/opsatel/Opsatel-Backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### B. Habilitar y Arrancar Servicio
```bash
sudo systemctl daemon-reload
sudo systemctl enable opsatel-backend
sudo systemctl start opsatel-backend
sudo systemctl status opsatel-backend
```

#### C. Reverse Proxy con Nginx
```nginx
server {
    listen 80;
    server_name api.opsatel.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Soporte para WebSockets de WhatsApp y logs
    location /ws {
        proxy_pass http://127.0.0.1:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
    }
}
```

---

*Documentación técnica del Backend actualizada conforme al estado funcional del sistema.*
