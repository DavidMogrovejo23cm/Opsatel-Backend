# Documentación del Proyecto: Sistema de Gestión ISP Opsatel

Este documento detalla los pasos seguidos para la implementación del backend de gestión de clientes ISP, basado en una importación de Excel a MySQL.

## 1. Tecnologías Utilizadas
*   **Lenguaje**: Python 3.13
*   **Framework API**: FastAPI
*   **Servidor Web**: Uvicorn
*   **ORM (Base de Datos)**: SQLAlchemy
*   **Base de Datos**: MySQL (vía XAMPP / MariaDB)

## 2. Proceso de Implementación

### Paso 1: Instalación de Dependencias
Se instalaron los paquetes necesarios para el funcionamiento del servidor y la conexión a la base de datos:
```powershell
pip install fastapi uvicorn sqlalchemy pymysql
```

### Paso 2: Configuración de la Base de Datos
Se configuró la conexión en el archivo `database.py` apuntando a la base de datos local `opsatel` en XAMPP.
*   **URL de conexión**: `mysql+pymysql://root:@localhost/opsatel`

### Paso 3: Limpieza y Normalización de Datos (Crítico)
Debido a que el Excel se importó con nombres genéricos (`COL 1`, `COL 2`, etc.) y los nombres de las columnas reales estaban en la primera fila de datos, se ejecutaron scripts de limpieza para:
1.  **Renombrar Columnas**: Se mapearon todas las columnas (41 en total) a sus nombres reales: `NUMERO`, `NOMBRE`, `CELULAR`, `CEDULA`, `CORREO`, `DIRECCION`, `PARROQUIA`, `PLAN`, `CEDULA_TIPO`, `UBICACION`, `ESTADO`, `TIEMPO`, `ARRIENDA`, `CUENTA`, `FECHA_FIRMA`, `INSTALATION DATE`, `PUERTO`, `ONT`, `SERVICIO`, `BREACH`, `ID_PORT`, `SERVICE PORT`, `IP`, `DISPOSITIVO`, `POTENCIA`, `NAP`, `TECNICO`, `ACTIVADOR`, `RED`, `CLAVE`, `FACTURAS`, `INTERNET PAYMENT`, `APP`, `PAYMENT DATE`, `CLIENT PAYMENT DATE`, `BANK`, `COD`, `PLUS`, `BANK_PLUS`, `SALDO`.
2.  **Eliminar Cabeceras**: Se borró la primera fila de la tabla que contenía los nombres como datos.
3.  **Configurar IDs**: Se convirtió la columna `NUMERO` en llave primaria autoincremental, desplazando los valores originales para evitar conflictos con el valor 0 de MySQL.

### Paso 4: Creación de Modelos y Esquemas
*   **`models.py`**: Se definieron las clases `Cliente` (mapeada a la tabla de Excel) y `Pago` (historial de transacciones).
*   **`schemas.py`**: Se crearon las validaciones de datos para las tres etapas de gestión (Creación, Técnica y Administración).

### Paso 5: Implementación de Endpoints (Rutas)
Se desarrollaron las funciones en `routes/clientes.py` para manejar el ciclo de vida del cliente:
*   `POST /clientes/`: Creación inicial (Etapa 1).
*   `PATCH /clientes/{id}/configuracion-tecnica`: Activación técnica (Etapa 2).
*   `PATCH /clientes/{id}/administracion`: Gestión de saldos (Etapa 3).
*   `POST /clientes/{id}/pagar`: Registro de pagos y reset de saldo a 0.
*   `POST /clientes/facturacion-mensual-global`: Simulación de cobro mensual masivo.

## 3. Guía de Ejecución

Para iniciar el servidor, ejecuta el siguiente comando desde la carpeta `opsatel`:

```powershell
python -m uvicorn main:app --reload
```

Luego, accede a la documentación interactiva en:
👉 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## 4. Notas Importantes
*   **Nombre de la Tabla**: El sistema usa directamente la tabla `hoja_de_c__lculo_sin_t__tulo` para evitar migraciones complejas de datos.
*   **Logs**: El servidor mostrará en consola cualquier error de conexión o validación de datos.
