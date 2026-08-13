import logging
import time
import json
import paramiko
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("opsatel.network.adapters.libreqos")

class LibreQoSAccessError(Exception):
    """Excepción para errores de autenticación o conexión SSH."""
    pass

class LibreQoSCommandError(Exception):
    """Excepción para errores en la ejecución del comando remoto."""
    pass

class SSHResult:
    def __init__(self, stdout: str, stderr: str, exit_code: int, duration_ms: int):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.success = (exit_code == 0)

class LibreQoSAdapter:
    """
    Adaptador LibreQoS que utiliza SSH (Paramiko) para gestionar las políticas de QoS.
    Soporta reintentos de conexión con backoff exponencial y ejecución robusta de comandos.
    """
    def __init__(self, server_cfg: Any):
        self.server_id = server_cfg.id
        self.host = server_cfg.host
        self.port = server_cfg.ssh_port or 22
        self.username = server_cfg.username
        self.auth_method = server_cfg.auth_method
        self.password = server_cfg.password
        self.private_key_path = server_cfg.private_key_path
        self.passphrase = server_cfg.passphrase
        self.timeout = server_cfg.ssh_timeout or 30
        self.max_retries = server_cfg.ssh_retries or 3
        
        # Comandos del servidor
        self.libreqos_path = server_cfg.libreqos_path or "/opt/libreqos"
        self.libreqos_apply_cmd = server_cfg.libreqos_apply_cmd
        self.libreqos_list_cmd = server_cfg.libreqos_list_cmd
        self.libreqos_config_file = server_cfg.libreqos_config_file or "/opt/libreqos/src/ispConfig.py"
        
        self.ssh_client: Optional[paramiko.SSHClient] = None

    def connect(self) -> bool:
        """Establece una conexión SSH segura con reintentos."""
        attempt = 0
        backoff = 2
        
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        while attempt < self.max_retries:
            try:
                attempt += 1
                logger.info(f"SSH: Conectando a LibreQoS {self.host}:{self.port} (Intento {attempt}/{self.max_retries})...")
                
                if self.auth_method == "key" and self.private_key_path:
                    # Cargar clave privada
                    try:
                        key = paramiko.RSAKey.from_private_key_file(
                            self.private_key_path, password=self.passphrase
                        )
                    except paramiko.PasswordRequiredException:
                        raise LibreQoSAccessError("La clave privada requiere passphrase y no fue provista.")
                    except Exception as ke:
                        # Reintento con Ed25519 por si acaso
                        try:
                            key = paramiko.Ed25519Key.from_private_key_file(
                                self.private_key_path, password=self.passphrase
                            )
                        except Exception:
                            raise LibreQoSAccessError(f"Error cargando clave privada SSH: {ke}")
                            
                    self.ssh_client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        pkey=key,
                        timeout=self.timeout
                    )
                else:
                    self.ssh_client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        password=self.password,
                        timeout=self.timeout
                    )
                
                logger.info(f"✓ Conexión SSH establecida con LibreQoS {self.host}")
                return True
            except Exception as e:
                logger.warning(f"Intento {attempt} fallido para conectar a LibreQoS: {e}")
                if attempt >= self.max_retries:
                    raise LibreQoSAccessError(f"Error de conexión SSH final tras {self.max_retries} intentos: {e}")
                time.sleep(backoff)
                backoff *= 2
        return False

    def disconnect(self):
        """Cierra la conexión SSH."""
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception as e:
                logger.warning(f"Error al cerrar la conexión SSH: {e}")
        self.ssh_client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def _execute(self, command: str) -> SSHResult:
        """Ejecuta un comando en el servidor y retorna el resultado detallado."""
        if not self.ssh_client:
            raise LibreQoSAccessError("No hay sesión SSH activa.")
            
        start_time = time.time()
        logger.debug(f"SSH Exec: {command}")
        
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=self.timeout)
            # Leer buffer completamente
            out_str = stdout.read().decode('utf-8', errors='ignore')
            err_str = stderr.read().decode('utf-8', errors='ignore')
            exit_code = stdout.channel.recv_exit_status()
            
            duration_ms = int((time.time() - start_time) * 1000)
            return SSHResult(out_str, err_str, exit_code, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Fallo al ejecutar comando SSH remoto: {e}")
            return SSHResult("", str(e), -1, duration_ms)

    def get_version(self) -> str:
        """Obtiene la versión o estado general de LibreQoS."""
        res = self._execute("libreqos --version || cli-status || echo 'LibreQoS SSH Server'")
        return res.stdout.strip() if res.success else "Unknown"

    def apply_config(self) -> SSHResult:
        """Ejecuta el script para regenerar y aplicar el shaping en LibreQoS."""
        return self._execute(self.libreqos_apply_cmd)

    def provision_client(self, client_id: int, ip: str, download_mbps: int, upload_mbps: int, comment: str) -> bool:
        """
        Agrega o actualiza un cliente en el archivo de configuración.
        Usa idempotencia: primero verifica si ya existe o está desactualizado.
        """
        esc_comment = comment.replace('"', '\\"').replace("'", "")
        cmd = f"sudo python3 {self.libreqos_path}/src/rust_integration/ispConfig.py --add --id {client_id} --ip {ip} --down {download_mbps} --up {upload_mbps} --name \"{esc_comment}\" || " \
              f"sudo {self.libreqos_path}/bin/lqcli client add --id {client_id} --ip {ip} --download {download_mbps} --upload {upload_mbps} --name \"{esc_comment}\""
              
        res = self._execute(cmd)
        if not res.success:
            logger.error(f"Fallo al agregar cliente a LibreQoS: {res.stderr}")
            if "exists" in res.stderr.lower() or "already" in res.stderr.lower():
                return self.update_client(client_id, ip, download_mbps, upload_mbps, comment)
            raise LibreQoSCommandError(f"Error provisionando cliente: {res.stderr}")
            
        apply_res = self.apply_config()
        return apply_res.success

    def update_client(self, client_id: int, ip: str, download_mbps: int, upload_mbps: int, comment: str = "") -> bool:
        """Actualiza la velocidad o IP de un cliente en LibreQoS."""
        esc_comment = comment.replace('"', '\\"').replace("'", "")
        cmd = f"sudo python3 {self.libreqos_path}/src/rust_integration/ispConfig.py --update --id {client_id} --ip {ip} --down {download_mbps} --up {upload_mbps} --name \"{esc_comment}\" || " \
              f"sudo {self.libreqos_path}/bin/lqcli client update --id {client_id} --ip {ip} --download {download_mbps} --upload {upload_mbps} --name \"{esc_comment}\""
              
        res = self._execute(cmd)
        if not res.success:
            raise LibreQoSCommandError(f"Error actualizando cliente en LibreQoS: {res.stderr}")
            
        apply_res = self.apply_config()
        return apply_res.success

    def remove_client(self, client_id: int, ip: str) -> bool:
        """Remueve la regla de QoS del cliente."""
        cmd = f"sudo python3 {self.libreqos_path}/src/rust_integration/ispConfig.py --remove --id {client_id} --ip {ip} || " \
              f"sudo {self.libreqos_path}/bin/lqcli client delete --id {client_id}"
              
        res = self._execute(cmd)
        if not res.success:
            if "not found" in res.stderr.lower() or "no existe" in res.stderr.lower():
                logger.info(f"Cliente {client_id} no existía en LibreQoS. Eliminación exitosa (no-op).")
                return True
            raise LibreQoSCommandError(f"Error eliminando cliente de LibreQoS: {res.stderr}")
            
        apply_res = self.apply_config()
        return apply_res.success

    def list_shaped_clients(self) -> List[Dict[str, Any]]:
        """
        Retorna la lista de todos los clientes configurados en el shaper.
        Utilizado para reconciliación.
        """
        res = self._execute(self.libreqos_list_cmd)
        if not res.success:
            raise LibreQoSCommandError(f"Error listando clientes del shaper: {res.stderr}")
            
        try:
            return json.loads(res.stdout.strip())
        except Exception as e:
            logger.warning(f"No se pudo parsear output JSON de LibreQoS list: {e}. Raw: {res.stdout[:200]}")
            return []
