import logging
import time
import csv
import io
import paramiko
from typing import Dict, Any, List, Optional

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
    Adaptador LibreQoS 1.5 que manipula directamente ShapedDevices.csv via SSH.
    
    Formato del CSV (real de producción):
    Circuit ID,Circuit Name,Device ID,Device Name,Parent Node,MAC,IPv4,IPv6,Download Min,Upload Min,Download Max,Upload Max,Comment
    35,MOROCHO QUITUIZACA MIRIAN PATRICIA,35,35,,,172.16.0.10,,2,2,300,300,
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

        # Rutas del servidor LibreQoS
        self.libreqos_path = server_cfg.libreqos_path or "/opt/libreqos"
        self.csv_path = f"{self.libreqos_path}/src/ShapedDevices.csv"

        self.ssh_client: Optional[paramiko.SSHClient] = None

    # ── Conexión SSH ──────────────────────────────────────────────────────

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
                    try:
                        key = paramiko.RSAKey.from_private_key_file(
                            self.private_key_path, password=self.passphrase
                        )
                    except paramiko.PasswordRequiredException:
                        raise LibreQoSAccessError("La clave privada requiere passphrase y no fue provista.")
                    except Exception as ke:
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
            except LibreQoSAccessError:
                raise
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

    def _execute(self, command: str, cmd_timeout: int = None) -> SSHResult:
        """Ejecuta un comando en el servidor y retorna el resultado detallado."""
        if not self.ssh_client:
            raise LibreQoSAccessError("No hay sesión SSH activa.")

        effective_timeout = cmd_timeout or self.timeout
        start_time = time.time()
        logger.debug(f"SSH Exec: {command}")

        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=effective_timeout)
            out_str = stdout.read().decode('utf-8', errors='ignore')
            err_str = stderr.read().decode('utf-8', errors='ignore')
            exit_code = stdout.channel.recv_exit_status()

            duration_ms = int((time.time() - start_time) * 1000)
            logger.debug(f"SSH Result: exit={exit_code}, stdout={out_str[:200]}, stderr={err_str[:200]}, {duration_ms}ms")
            return SSHResult(out_str, err_str, exit_code, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Fallo al ejecutar comando SSH remoto: {e}")
            return SSHResult("", str(e), -1, duration_ms)

    # ── Utilidades CSV ────────────────────────────────────────────────────

    def _sanitize_name(self, name: str) -> str:
        """Sanitiza el nombre del cliente para ser seguro en CSV y en comandos shell."""
        safe = name.replace(",", " ").replace("'", "").replace('"', '').replace("\\", "")
        return safe.strip()

    def _build_csv_line(self, client_id: int, name: str, ip: str, download: int, upload: int) -> str:
        """
        Construye una línea para ShapedDevices.csv siguiendo el formato real de producción.
        
        Formato: Circuit ID,Circuit Name,Device ID,Device Name,Parent Node,MAC,IPv4,IPv6,Download Min,Upload Min,Download Max,Upload Max,Comment
        """
        safe_name = self._sanitize_name(name)
        return f"{client_id},{safe_name},{client_id},{client_id},,,{ip},,2,2,{download},{upload},"

    def _reload_libreqos(self) -> bool:
        """
        Recarga LibreQoS para aplicar los cambios en ShapedDevices.csv.
        Usa python3 LibreQoS.py que lee el CSV y aplica las reglas tc.
        Timeout largo porque el proceso puede tardar 30-120 segundos.
        """
        logger.info("Recargando LibreQoS para aplicar cambios en ShapedDevices.csv...")
        reload_cmd = f"cd {self.libreqos_path}/src && sudo python3 LibreQoS.py"
        res = self._execute(reload_cmd, cmd_timeout=180)
        if res.success:
            logger.info(f"✓ LibreQoS recargado exitosamente ({res.duration_ms}ms)")
        else:
            # A veces LibreQoS imprime warnings en stderr pero funciona correctamente
            if res.exit_code == 0 or "shaped" in res.stdout.lower():
                logger.warning(f"LibreQoS recargado con advertencias: {res.stderr[:300]}")
                return True
            logger.error(f"Error recargando LibreQoS: exit={res.exit_code}, stderr={res.stderr[:500]}")
        return res.success

    # ── Operaciones de Cliente ────────────────────────────────────────────

    def get_version(self) -> str:
        """Obtiene la versión o estado general de LibreQoS."""
        res = self._execute(f"cat {self.libreqos_path}/src/lqos.example 2>/dev/null || echo 'LibreQoS SSH OK'")
        count_res = self._execute(f"wc -l < {self.csv_path}")
        count = count_res.stdout.strip() if count_res.success else "?"
        return f"LibreQoS SSH OK - {count} entradas en ShapedDevices.csv"

    def provision_client(self, client_id: int, ip: str, download_mbps: int, upload_mbps: int, comment: str) -> bool:
        """
        Agrega un cliente al ShapedDevices.csv y recarga LibreQoS.
        Si ya existe (por Circuit ID), lo actualiza en lugar de duplicar.
        """
        logger.info(f"PROVISION: Cliente {client_id}, IP={ip}, Down={download_mbps}, Up={upload_mbps}, Name={comment}")

        # Verificar si ya existe por Circuit ID
        check = self._execute(f"grep -c '^{client_id},' {self.csv_path}")
        count = check.stdout.strip() if check.success else "0"
        
        if count != "0":
            logger.info(f"Cliente {client_id} ya existe en ShapedDevices.csv. Actualizando en vez de duplicar...")
            return self.update_client(client_id, ip, download_mbps, upload_mbps, comment)

        # Construir la línea CSV
        csv_line = self._build_csv_line(client_id, comment, ip, download_mbps, upload_mbps)
        
        # Agregar al final del archivo usando echo (más robusto con UTF-8)
        append_cmd = f'echo "{csv_line}" >> {self.csv_path}'
        res = self._execute(append_cmd)

        if not res.success:
            raise LibreQoSCommandError(f"Error agregando cliente {client_id} a ShapedDevices.csv: {res.stderr}")

        logger.info(f"✓ Cliente {client_id} agregado a ShapedDevices.csv: {csv_line}")
        
        # Verificar que se agregó correctamente
        verify = self._execute(f"grep '^{client_id},' {self.csv_path}")
        if not verify.success:
            raise LibreQoSCommandError(f"Verificación fallida: la línea del cliente {client_id} no se encontró después de agregarla.")
        logger.info(f"✓ Verificación OK: {verify.stdout.strip()}")

        return self._reload_libreqos()

    def update_client(self, client_id: int, ip: str, download_mbps: int, upload_mbps: int, comment: str = "") -> bool:
        """
        Actualiza un cliente en ShapedDevices.csv.
        Estrategia: eliminar la línea anterior y agregar la nueva al final.
        """
        logger.info(f"UPDATE: Cliente {client_id}, IP={ip}, Down={download_mbps}, Up={upload_mbps}")
        
        csv_line = self._build_csv_line(client_id, comment, ip, download_mbps, upload_mbps)

        # 1. Eliminar línea anterior por Circuit ID (coincide con "^ID," al inicio)
        delete_cmd = f"sed -i '/^{client_id},/d' {self.csv_path}"
        res = self._execute(delete_cmd)
        if not res.success:
            raise LibreQoSCommandError(f"Error eliminando línea anterior del cliente {client_id}: {res.stderr}")

        # 2. Agregar nueva línea
        append_cmd = f'echo "{csv_line}" >> {self.csv_path}'
        res = self._execute(append_cmd)
        if not res.success:
            raise LibreQoSCommandError(f"Error agregando línea actualizada del cliente {client_id}: {res.stderr}")

        logger.info(f"✓ Cliente {client_id} actualizado en ShapedDevices.csv: {csv_line}")
        return self._reload_libreqos()

    def remove_client(self, client_id: int, ip: str) -> bool:
        """Remueve un cliente del ShapedDevices.csv."""
        logger.info(f"REMOVE: Cliente {client_id}, IP={ip}")

        # Verificar si existe
        check = self._execute(f"grep -c '^{client_id},' {self.csv_path}")
        count = check.stdout.strip() if check.success else "0"
        if count == "0":
            logger.info(f"Cliente {client_id} no existe en ShapedDevices.csv. Nada que remover (no-op exitoso).")
            return True

        delete_cmd = f"sed -i '/^{client_id},/d' {self.csv_path}"
        res = self._execute(delete_cmd)
        if not res.success:
            raise LibreQoSCommandError(f"Error eliminando cliente {client_id} de ShapedDevices.csv: {res.stderr}")

        logger.info(f"✓ Cliente {client_id} eliminado de ShapedDevices.csv")
        return self._reload_libreqos()

    def list_shaped_clients(self) -> List[Dict[str, Any]]:
        """
        Lista todos los clientes configurados en ShapedDevices.csv.
        Retorna una lista de diccionarios parseados del CSV.
        """
        res = self._execute(f"cat {self.csv_path}")
        if not res.success:
            raise LibreQoSCommandError(f"Error leyendo ShapedDevices.csv: {res.stderr}")

        clients = []
        try:
            reader = csv.DictReader(io.StringIO(res.stdout))
            for row in reader:
                clients.append(dict(row))
        except Exception as e:
            logger.warning(f"Error parseando ShapedDevices.csv: {e}")

        return clients

    def apply_config(self) -> SSHResult:
        """Recarga LibreQoS (compatibilidad con código existente)."""
        reload_cmd = f"cd {self.libreqos_path}/src && sudo python3 LibreQoS.py"
        return self._execute(reload_cmd, cmd_timeout=180)
