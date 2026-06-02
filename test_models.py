import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import models

url = "postgresql://postgres:YLeKCvzhDTEdIyVwmrduyOEKyWVObufn@postgres-production-e9d4.up.railway.app:5432/railway?sslmode=require"
engine = create_engine(url)
Session = sessionmaker(bind=engine)
db = Session()

models_to_test = [
    (models.Cliente, "Clientes"),
    (models.Pago, "Pagos"),
    (models.Nodo, "Nodos"),
    (models.PlanInternet, "Planes de Internet"),
    (models.Banco, "Bancos"),
    (models.Puerto, "Puertos"),
    (models.FinanzasBase, "Finanzas Base"),
    (models.Parroquia, "Parroquias"),
    (models.ClienteExtra, "Clientes Extras"),
    (models.PagoExtra, "Pagos Extras"),
    (models.HojaRuta, "Hojas de Ruta"),
    (models.Ticket, "Tickets de Asistencia"),
    (models.CallCenterTicket, "Tickets Call Center"),
    (models.Egreso, "Egresos"),
    (models.Proyecto, "Proyectos"),
    (models.ProyectoPago, "Proyecto Pagos"),
    (models.GastoProyecto, "Gasto Proyectos"),
    (models.Colchon, "Colchón de Reserva"),
    (models.GastoFijo, "Gastos Fijos"),
    (models.Asistencia, "Asistencias del Personal"),
    (models.WhatsAppHistorial, "Historial WhatsApp"),
    (models.WhatsAppConfiguracion, "Configuración WhatsApp"),
    (models.ReporteMensual, "Reportes Mensuales"),
    (models.Usuario, "Usuarios del Sistema")
]

for model, name in models_to_test:
    try:
        count = db.query(model).count()
        print(f"✅ {name}: {count} records")
    except Exception as e:
        print(f"❌ {name} failed: {e}")
db.close()
