import unittest
from unittest.mock import MagicMock, patch
import json

from services.smart_parser import parse_unstructured_client_data

class SmartParserTests(unittest.TestCase):
    @patch('services.smart_parser.get_anthropic_client')
    def test_parse_unstructured_client_data_success(self, mock_get_client):
        # Mock client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock Claude response containing clean JSON
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps({
            "nombre": "Juan Perez",
            "cedula": "0102030405",
            "cedula_tipo": "Cédula",
            "celular": "0998877665",
            "correo": "juan@perez.com",
            "direccion": "Sayausi centro",
            "nodo": "SAYAUSI",
            "parroquia": "Sayausi",
            "plan": "Plan 30 Megas",
            "fecha_firma": "2026-07-14",
            "ubicacion": "-2.8974, -79.0045",
            "tiempo": "12",
            "tercera_edad": False,
            "precio_plan_especial": None,
            "comentarios": "Instalar por la mañana",
            "mac": "HWTC12345678",
            "puerto": "Puerto 3",
            "ip": "172.18.3.15",
            "dispositivo": "Huawei EG8145V5",
            "nap": "NAP 5",
            "red": "VLAN 403",
            "clave": "wifi1234",
            "tecnico": "Alex",
            "iptv_max_conn": 2,
            "iptv_activar": True
        }))]
        mock_client.messages.create.return_value = mock_message

        # Input
        text = "Registrar a Juan Perez, ci 0102030405, cel 0998877665, plan de 30 megas en Sayausi, mac HWTC12345678, puerto 3"
        valid_nodos = ["SAYAUSI", "BAÑOS"]
        valid_parroquias = ["Sayausi", "Baños"]
        valid_planes = ["Plan 30 Megas", "Plan 50 Megas"]

        result = parse_unstructured_client_data(text, valid_nodos, valid_parroquias, valid_planes)

        # Assertions
        self.assertEqual(result["nombre"], "Juan Perez")
        self.assertEqual(result["cedula"], "0102030405")
        self.assertEqual(result["nodo"], "SAYAUSI")
        self.assertEqual(result["plan"], "Plan 30 Megas")
        self.assertEqual(result["mac"], "HWTC12345678")
        self.assertEqual(result["puerto"], "Puerto 3")
        self.assertTrue(result["iptv_activar"])

    @patch('services.smart_parser.get_anthropic_client')
    def test_parse_unstructured_client_data_with_markdown(self, mock_get_client):
        # Mock client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock Claude response wrapped in markdown block
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="""```json
{
    "nombre": "Maria Gomez",
    "cedula": "0102030406",
    "plan": "Plan 50 Megas"
}
```""")]
        mock_client.messages.create.return_value = mock_message

        result = parse_unstructured_client_data("Maria Gomez, plan 50 megas", [], [], [])

        self.assertEqual(result["nombre"], "Maria Gomez")
        self.assertEqual(result["plan"], "Plan 50 Megas")

if __name__ == '__main__':
    unittest.main()
