# 🚀 DOCUMENTACIÓN TÉCNICA - BACKEND OPSATEL

Este documento proporciona una visión detallada de la arquitectura, lógica de negocio y funcionamiento del backend del sistema de gestión ISP **Opsatel**.

---

## 🛠️ 1. Arquitectura y Tecnologías
La API está construida con un stack moderno y eficiente diseñado para manejar grandes volúmenes de datos de clientes y automatizar procesos técnicos.

*   **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python) - Proporciona alto rendimiento y generación automática de documentación (Swagger).
*   **Base de Datos:** [MySQL](https://www.mysql.com/) - Motor relacional para persistencia de datos complejos.
*   **ORM:** [SQLAlchemy](https://www.sqlalchemy.org/) - Mapeo objeto-relacional para interactuar con la DB de forma segura.
*   **Autenticación:** [JWT (JSON Web Tokens)](https://jwt.io/) - Seguridad basada en tokens con roles definidos.
*   **Procesamiento de Datos:** [Pandas](https://pandas.pydata.org/) - Generación de reportes dinámicos en Excel.
*   **Servidor:** [Uvicorn](https://www.uvicorn.org/) - Servidor ASGI para ejecución en tiempo real.

---

## 📂 2. Estructura del Proyecto
El código está organizado de forma modular para facilitar su mantenimiento:

```text
opsatel/
├── main.py                 # Punto de entrada de la aplicación y configuración de CORS.
├── database.py             # Configuración de la conexión MySQL y sesión de SQLAlchemy.
├── models.py               # Definición de las tablas de la base de datos (Entidades).
├── schemas.py              # Definición de modelos Pydantic (Validación de datos API).
├── auth_utils.py           # Utilidades para hashing de contraseñas y generación de JWT.
├── routes/                 # Directorio de controladores de rutas
│   ├── auth.py             # Gestión de login, registro y usuarios.
│   └── clientes.py         # Lógica central: Clientes, pagos, scripts y reportes.
├── rutas_configuraciones.py # CRUD de Nodos, Planes, Bancos y Puertos.
├── uploads/                # Directorio de almacenamiento de imágenes (Cédulas).
├── rutas_reportes/         # Almacenamiento de reportes Excel generados.
└── [scripts_varios].py     # Herramientas de mantenimiento, seeding y correcciones de DB.
```

---

## 🗄️ 3. Modelo de Datos (DB Schema)
El sistema utiliza un esquema relacional con las siguientes entidades principales:

*   **`Cliente` (`hoja_de_c__lculo_sin_t__tulo`):** Tabla central. Almacena datos personales, geográficos (Nodo/Puerto), técnicos (IP, ONT, Scripts) y financieros (Saldo, Pagos).
*   **`Usuario`:** Gestión de accesos con roles (`administrador`, `secretario`, `tecnico`, `instalador`).
*   **`Pago`:** Historial detallado de transacciones financieras por cliente.
*   **`Nodo`:** Entidad geográfica que define el prefijo IP base (Ej: 172.16).
*   **`Puerto`:** Subdivisiones físicas/lógicas dentro de un nodo para organizar ONTs.
*   **`PlanInternet`:** Catálogo de velocidades y precios mensuales.
*   **`Banco`:** Lista de entidades financieras permitidas para pagos.
*   **`ReporteMensual`:** Registro de archivos Excel generados históricamente.

---

## 🔐 4. Sistema de Seguridad y Roles (RBAC)
El sistema implementa un control de acceso basado en roles para proteger la integridad de los datos:

| Rol | Permisos Principales |
| :--- | :--- |
| **Administrador** | Acceso total, gestión de usuarios, facturación global, eliminación de datos. |
| **Secretario** | Gestión de clientes, registro de pagos, generación de reportes, edición de planes. |
| **Técnico** | Configuración técnica de clientes, generación de scripts GPON, actualización de potencia (NAP). |
| **Instalador** | Similar al técnico, enfocado en el despliegue inicial en campo. |

---

## ⚙️ 5. Lógica de Negocio Crucial

### A. Flujo de Estados del Cliente
1.  **Pendiente:** Cliente registrado pero sin instalación física.
2.  **En Activación:** Etapa donde el equipo técnico asigna IP, ONT y genera scripts.
3.  **Activo:** Cliente operando normalmente, genera deudas mensuales automáticas.

### B. Generación de Automatismos Técnicos (OLT Huawei)
El backend calcula automáticamente los siguientes valores para evitar colisiones:
*   **ID Port (ONT ID):** Se autoincrementa por cada Puerto específico.
*   **Service Port:** Autoincremento global para asegurar unicidad en la OLT.
*   **IP Dinámica:** Basada en la fórmula: `{Prefijo_Nodo}.{Num_Puerto}.{ONT_ID + 1}`.
*   **Scripts:** Generación de comandos `ont add`, `service-port` y `native-vlan` listos para copiar y pegar.

### C. Ciclo Financiero y Facturación
El sistema maneja un ciclo mensual riguroso para evitar errores contables:
1.  **Facturación Mensual Global:** Suma el valor del Plan + Plus al saldo de todos los clientes "Activos". Requiere que el mes anterior esté "Cerrado".
2.  **Cierre de Mes:** Resetea los contadores de `pago_mensual` para iniciar el nuevo ciclo desde cero, manteniendo la deuda/saldo pendiente.
3.  **Generación de Reporte:** Exporta a Excel los cobros efectuados del mes y realiza el cierre automático.

---

## 📡 6. Endpoints Principales (Resumen)

### Autenticación (`/auth`)
*   `POST /login`: Retorna token JWT y datos del usuario.
*   `POST /register`: (Solo Admin) Crea nuevos usuarios de sistema.

### Gestión de Clientes (`/clientes`)
*   `GET /`: Lista todos los clientes.
*   `POST /`: Crea un nuevo prospecto de cliente.
*   `GET /siguiente-valor-tecnico`: Calcula IP, ID Port y genera comandos OLT en tiempo real.
*   `PATCH /{id}/configuracion-tecnica`: Finaliza la instalación y activa al cliente.
*   `POST /{id}/pagar`: Registra un pago y liquida saldos/plus/adicionales.
*   `POST /facturacion-mensual-global`: Ejecuta el cobro masivo del mes.

### Configuración (`/configuraciones`)
*   CRUD completo para `nodos`, `planes`, `bancos` y `puertos`.

---

## 🛠️ 7. Herramientas de Mantenimiento
Existen scripts especializados en la raíz del proyecto para tareas administrativas:
*   `create_users.py`: Inicializa usuarios base (Admin: `admin123`).
*   `seed_configuraciones.py`: Carga nodos (Baños, Sayausí), planes y puertos iniciales.
*   `sync_db.py`: Sincroniza automáticamente cambios en las columnas de `models.py` con MySQL.
*   `cleanup_database.py`: Limpia registros de prueba o inconsistentes.

---

## 🚀 8. Instrucciones de Despliegue (Local)
1. Instalar dependencias: `pip install -r requirements.txt`.
2. Configurar DB en `database.py`: `SQLALCHEMY_DATABASE_URL`.
3. Ejecutar inicialización: `python create_users.py` y `python seed_configuraciones.py`.
4. Iniciar servidor: `uvicorn main:app --reload`.

---
**Nota:** Esta documentación refleja el estado actual del backend y debe actualizarse ante cambios significativos en los modelos o lógica financiera.

---

## 🆕 9. Actualizaciones Recientes (v1.2)

### A. Mejoras en Lógica Financiera (Independencia Contable)
Se refactorizó el sistema de cobros para aislar el cargo "Adicional":
*   **Base de Datos (`historial_pagos`):** Se implementó la columna `monto_adicional`.
*   **Registro de Pagos (`POST /clientes/{id}/pagar`):** Los abonos ingresados como "Adicional" **no** disminuyen el saldo base de la deuda por internet/IPTV (`total_pago`). Esto garantiza que los cobros extraordinarios (instalaciones, ventas de routers) se mantengan independientes de la facturación recurrente.
*   **Frontend Sincronizado:** El dashboard y el modal interactivo de pagos del UI reflejan ahora el cálculo aislado, acumulando el "TOTAL" recaudado en la "Vista General" sin contaminar la contabilidad de la deuda pendiente.

### B. Gestión de Contratos (Campo `tiempo`)
Se optimizó el modelo de creación de clientes para incluir métricas de permanencia:
*   **Esquema `ClienteCreate`:** Incorporación del campo `tiempo` (duración del contrato en meses).
*   **Endpoint (`POST /clientes/`):** La ruta captura el tiempo estipulado desde la venta inicial.
*   **Frontend (UX):** Se eliminó la edición manual del "Tiempo" en el panel administrativo, y se trasladó la captura de este valor al formulario inicial de Ventas, protegiendo los parámetros comerciales.

### C. Configuración de Finanzas Base y Dashboard Global
Se añadió un sistema para gestionar y visualizar la liquidez real de las cuentas principales:
*   **Base de Datos (`FinanzasBase`):** Nueva tabla `finanzas_base` que centraliza los montos estáticos establecidos (Caja Chica, Pichincha, JEP).
*   **Nuevos Endpoints (`/configuraciones/finanzas-base`):** Rutas integradas para permitir a los administradores fijar valores base de arranque de caja.
*   **Cálculo Asíncrono en Dashboard (`GET /clientes/dashboard-stats`):** El backend suma automáticamente todos los ingresos registrados y los acumula a los valores preconfigurados, entregando el parámetro consolidado de `finanzas_globales`.
*   **Representación Visual:** Implementación de un gráfico `BarChart` en el panel de control del cliente que grafica de manera interactiva el saldo total acumulado de cada institución bancaria en el momento, optimizando la visibilidad de cuentas.

---

## 🆕 10. Clasificación Inteligente de Datos (v1.3)

Se implementó una capa de Inteligencia Artificial (IA) capaz de procesar textos desestructurados o datos crudos semi-estructurados y clasificarlos automáticamente a los campos correspondientes de la base de datos de clientes:

### A. Endpoint `/clientes/parse-smart` (IA Inteligente)
*   **Método:** `POST /clientes/parse-smart`
*   **Payload:** `{"text": "texto crudo a interpretar"}`
*   **Funcionamiento:**
    1. Consulta dinámicamente la lista de Nodos, Parroquias y Planes de Internet vigentes en la base de datos.
    2. Envía el texto a Claude (`claude-3-5-haiku-20241022`) junto con estas listas utilizando un prompt optimizado para extracción de entidades.
    3. Normaliza automáticamente campos críticos:
        *   **Cédula:** Elimina guiones y puntos, valida longitud, agrega ceros iniciales si es necesario.
        *   **Teléfono:** Limpia formatos de celular.
        *   **Booleans:** Detecta automáticamente si califica para tercera edad/discapacidad o si tiene IPTV activado.
        *   **Fuzzy Mapping:** Mapea variaciones de texto (ej: "sayausi", "30 megas") al nombre exacto del Nodo o Plan registrado en la base de datos para evitar discrepancias.
    4. Devuelve un objeto JSON estructurado con todos los campos listos para poblar el formulario del frontend.
