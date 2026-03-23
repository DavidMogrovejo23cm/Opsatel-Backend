# 🌐 Opsatel - Backend (API)

Este es el núcleo de datos y lógica de Opsatel, diseñado para gestionar los clientes de un Proveedor de Servicios de Internet (ISP) desde su etapa inicial de venta hasta la configuración técnica en la OLT y la facturación mensual. 

## 🏗️ ¿Qué se hizo desde el principio?
El backend fue construido desde cero con el objetivo de centralizar todas las reglas del negocio, quitando la carga computacional y la lógica compleja de las interfaces de usuario.

1. **Diseño de Base de Datos:** Se estructuró un sistema relacional en **MySQL** usando **SQLAlchemy** (ORM). Se definieron tres agrupaciones clave:
   - `Cliente`: Todos los datos de venta, datos GPON y saldos.
   - `Pago`: Historial contable de cada transacción realizada.
   - `ConfiguracionGlobal`: Sistema de auditoría para evitar dobles facturaciones.
2. **API RESTful:** Se desarrollaron endpoints modulares usando **FastAPI**.
3. **Mecanismo de Facturación:** Se implementó una lógica (`/facturacion-mensual-global`) que recorre a todos los clientes activos y les incrementa la deuda según el costo de su plan base + extras (plus), asegurando que solo se ejecute una vez por mes.
4. **Automatización OLT y Redes:** Se incorporó un algoritmo dinámico que, basado en la parroquia (BAÑOS / SAYAUSÍ) y el puerto físico, calcula la siguiente IP disponible sin solaparse y genera automáticamente los scripts CLI (comandos) exactos para aprovisionar equipos en OLTs Huawei.

## 🛠️ ¿Cómo se hizo?
- **Lenguaje / Framework:** Python + FastAPI (Elegido por su altísimo rendimiento y su autogeneración de documentación en `/docs`).
- **Base de Datos:** MySQL conectada mediante `mysql-connector-python` y gestionada a través de las sesiones de SQLAlchemy.
- **Seguridad y Accesibilidad:** Se configuró **CORS** (Cross-Origin Resource Sharing) permitiendo que cualquier frontend (especialmente el local en puertos 5173/5174) pueda hacer peticiones a la API sin ser bloqueado por el navegador.

## ⚙️ ¿Cómo funciona?
La arquitectura funciona de la siguiente manera:

### 1. Sistema de Rutas (`routes/clientes.py`)
- **`POST /clientes/`**: Crea un cliente en estado `Pendiente` (etapa de Ventas).
- **`GET /clientes/siguiente-valor-tecnico`**: El cerebro técnico. Recibe la MAC, la parroquia y el puerto, calcula la cantidad de clientes existentes para autoincrementar el `Service Port`, `ID Port` e `IP`, y devuelve los 3 comandos exactos de Huawei (`ont add`, `service-port`, `ont port native-vlan`).
- **`PATCH /clientes/{id}/configuracion-tecnica`**: Termina de grabar los datos de fibra, NAP, potencia, y la configuración del router final, pasando al cliente a estado `Activo`.
- **`PATCH /clientes/{id}/administracion`**: Modifica en vivo datos comerciales (Plan, Plus).
- **`PATCH /clientes/{id}`**: Modificaciones generales de cualquier tabla.
- **`POST /clientes/{id}/pagar`**: Introduce dinero a la cuenta del cliente (restando a su deuda total en `saldo`) y deja una huella en la tabla `pagos`.

### 2. Capa de Modelos (`models.py`)
Mapea exactamente las columnas de la tabla SQL (`hoja_de_c__lculo_sin_t__tulo`) hacia variables de Python. En cuanto la app se ejecuta desde `main.py`, SQLAlchemy escanea la base de datos y verifica que todas las estructuras existan gracias a `Base.metadata.create_all()`.

### 3. Arranque (`main.py`)
Punto de entrada primario. Invoca a Uvicorn y monta el enrutador de `clientes`.
Para iniciarlo en desarrollo:
```bash
python -m uvicorn main:app --reload
```
