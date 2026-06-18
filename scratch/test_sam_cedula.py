import sys
import os
import unittest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Agregar directorio padre al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models
import sam_bot_service

class TestSamCedula(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Usar una base de datos SQLite en memoria para la prueba
        cls.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        self.db = self.Session()
        # Limpiar datos anteriores
        self.db.query(models.Cliente).delete()
        self.db.query(models.Pago).delete()
        self.db.commit()

        # Insertar cliente de prueba
        self.cliente = models.Cliente(
            id=101,
            nombre="JOSE PEREZ",
            cedula="1712345678",
            celular="0999999999",
            plan="Plan Fibra 200MB",
            pago_mensual=20.00,
            saldo=15.00,
            estado="Activo"
        )
        self.db.add(self.cliente)
        self.db.commit()

        # Mock del cliente de Anthropic para evitar llamadas reales
        self.mock_client = MagicMock()
        sam_bot_service.get_anthropic_client = lambda: self.mock_client
        
        # Limpiar estados de memoria del chatbot para cada test
        sam_bot_service.estados_skills.clear()
        sam_bot_service.historial_conversaciones.clear()

        # Mock del envío de mensajes de whatsapp_service para no mandar mensajes reales
        import whatsapp_service
        whatsapp_service.send_whatsapp_message = MagicMock(return_value=True)

    def tearDown(self):
        self.db.close()

    def test_extraer_cedula(self):
        self.assertEqual(sam_bot_service.extraer_cedula("1712345678"), "1712345678")
        self.assertEqual(sam_bot_service.extraer_cedula("mi cedula es 171234567-8"), "1712345678")
        self.assertEqual(sam_bot_service.extraer_cedula("171234567 8"), "1712345678")
        self.assertEqual(sam_bot_service.extraer_cedula("no tengo cedula"), "")

    def test_flujo_completo_consulta_saldo_exito(self):
        # 1. El usuario saluda
        # Mock de Claude para chat general
        mock_response_general = MagicMock()
        mock_response_general.content = [MagicMock(text="Hola, soy SAM de Opsatel. ¿Cómo puedo ayudarte hoy?")]
        self.mock_client.messages.create.return_value = mock_response_general

        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "Hola buenas", self.db)
        self.assertIn("ayudarte hoy", res)
        self.assertIsNone(sam_bot_service.estados_skills.get("593999999999"))

        # 2. El usuario pide consultar su saldo
        # Mock de Claude para clasificar la intención como consultar_pagos_y_saldos
        mock_intent = MagicMock()
        mock_intent.content = [MagicMock(text="consultar_pagos_y_saldos")]
        
        # Mock de Claude para extraer_nombre (responde "auto" para saldo propio)
        mock_name = MagicMock()
        mock_name.content = [MagicMock(text="auto")]

        self.mock_client.messages.create.side_effect = [mock_intent, mock_name]

        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "quiero consultar mi saldo", self.db)
        self.assertEqual(res, "Por favor, ayúdame con tu número de cédula para consultar tu saldo.")
        self.assertEqual(sam_bot_service.estados_skills.get("593999999999"), "consultar_pagos_y_saldos")

        # 3. El usuario envía su cédula
        # Mock de Claude para generar el resumen de pago final
        mock_pago = MagicMock()
        mock_pago.content = [MagicMock(text="Hola JOSE PEREZ, tu saldo es $15.00.")]
        self.mock_client.messages.create.side_effect = [mock_pago]

        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "1712345678", self.db)
        self.assertIn("JOSE PEREZ", res)
        self.assertIn("$15.00", res)
        # El estado del skill debe haberse limpiado
        self.assertIsNone(sam_bot_service.estados_skills.get("593999999999"))

    def test_flujo_consulta_saldo_cancelar(self):
        # Inicializar el estado de forma simulada
        sam_bot_service.estados_skills["593999999999"] = "consultar_pagos_y_saldos"

        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "cancelar", self.db)
        self.assertIn("he cancelado la consulta de saldo", res)
        self.assertIsNone(sam_bot_service.estados_skills.get("593999999999"))

    def test_flujo_consulta_saldo_invalido_reintento(self):
        # Inicializar el estado de forma simulada
        sam_bot_service.estados_skills["593999999999"] = "consultar_pagos_y_saldos"

        # Envía algo inválido
        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "no me acuerdo", self.db)
        self.assertIn("No logré identificar un número de cédula de 10 dígitos", res)
        # Sigue en el estado
        self.assertEqual(sam_bot_service.estados_skills.get("593999999999"), "consultar_pagos_y_saldos")

        # Envía cédula que no existe en DB
        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "9999999999", self.db)
        self.assertIn("no encontré ningún cliente con el número de cédula", res)
        # Sigue en el estado
        self.assertEqual(sam_bot_service.estados_skills.get("593999999999"), "consultar_pagos_y_saldos")

        # Envía cédula correcta
        mock_pago = MagicMock()
        mock_pago.content = [MagicMock(text="Tu saldo es $15.00.")]
        self.mock_client.messages.create.side_effect = [mock_pago]

        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "1712345678", self.db)
        self.assertIn("$15.00", res)
        # Ya terminó y limpió estado
        self.assertIsNone(sam_bot_service.estados_skills.get("593999999999"))

    def test_fallback_when_api_fails(self):
        # Configurar el mock para que levante una excepción (como un 404 del modelo)
        self.mock_client.messages.create.side_effect = Exception("Model not found 404")

        # 1. El usuario saluda. Debe usar la respuesta fallback de chat general
        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "Hola buenas", self.db)
        self.assertEqual(res, "Hola soy Sam de opsatel, espero estes teniendo un buen dia en que puedo ayudarte el dia de hoy?")
        self.assertIsNone(sam_bot_service.estados_skills.get("593999999999"))

        # 2. El usuario pide saldo. Clasificador falla y usa keywords.
        # Debe identificar "saldo" y pedir la cédula
        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "quiero consultar mi saldo", self.db)
        self.assertEqual(res, "Por favor, ayúdame con tu número de cédula para consultar tu saldo.")
        self.assertEqual(sam_bot_service.estados_skills.get("593999999999"), "consultar_pagos_y_saldos")

        # 3. El usuario envía su cédula. El bot procesa el pago y Claude vuelve a fallar.
        # Debe caer en la respuesta básica formateada con los datos del cliente
        res = sam_bot_service.procesar_mensaje_entrante("593999999999", "1712345678", self.db)
        self.assertIn("JOSE PEREZ", res)
        self.assertIn("$15.00", res)
        self.assertIn("Activo", res)
        # Debe haberse limpiado el estado
        self.assertIsNone(sam_bot_service.estados_skills.get("593999999999"))

if __name__ == "__main__":
    unittest.main()
