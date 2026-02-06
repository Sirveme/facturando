"""
Servicio de consulta RUC/DNI usando apis.net.pe
"""
import requests
import logging
from typing import Optional, Dict
from src.core.config import settings

class ApisNetPeClient:
    """Cliente para la API de apis.net.pe"""
    
    def __init__(self, token: Optional[str] = None):
        self._api_token = token.strip() if token else None
        self._api_url = "https://api.apis.net.pe"
        
        if not self._api_token:
            logging.warning("APIS_NET_PE_TOKEN no configurado - consultas RUC/DNI no funcionarán")
    
    def _get(self, path: str, params: dict) -> Optional[dict]:
        """Realiza petición GET a la API"""
        if not self._api_token:
            return None
        
        url = f"{self._api_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
        }
        
        print(f"DEBUG API: GET {url} params={params}")
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.HTTPError as http_err:
            print(f"ERROR API HTTP: {http_err.response.status_code} - {http_err.response.text}")
            return None
        
        except requests.exceptions.RequestException as req_err:
            print(f"ERROR API Network: {req_err}")
            return None
    
    def get_company(self, ruc: str) -> Optional[dict]:
        """Consulta RUC en SUNAT"""
        return self._get("/v2/sunat/ruc", {"numero": ruc})
    
    def get_person(self, dni: str) -> Optional[dict]:
        """Consulta DNI en RENIEC"""
        return self._get("/v2/reniec/dni", {"numero": dni})


# Instancia global del cliente
api_client = ApisNetPeClient(token=settings.APIS_NET_PE_TOKEN if hasattr(settings, 'APIS_NET_PE_TOKEN') else None)


def consultar_ruc(ruc: str) -> Optional[Dict]:
    """
    Consulta RUC en SUNAT
    Retorna: {ruc, razon_social, direccion, estado, condicion, encontrado}
    """
    if not ruc or len(ruc) != 11:
        return {"ruc": ruc, "encontrado": False, "mensaje": "RUC debe tener 11 dígitos"}
    
    if not ruc.isdigit():
        return {"ruc": ruc, "encontrado": False, "mensaje": "RUC debe ser numérico"}
    
    data = api_client.get_company(ruc)
    
    if data:
        # Normalizar respuesta
        razon_social = data.get('razonSocial') or data.get('nombre') or ''
        direccion = data.get('direccion') or ''
        
        if direccion.strip() == '-':
            direccion = ''
        
        return {
            "ruc": ruc,
            "razon_social": razon_social,
            "direccion": direccion,
            "estado": data.get('estado', ''),
            "condicion": data.get('condicion', ''),
            "ubigeo": data.get('ubigeo', ''),
            "departamento": data.get('departamento', ''),
            "provincia": data.get('provincia', ''),
            "distrito": data.get('distrito', ''),
            "encontrado": True
        }
    
    return {"ruc": ruc, "encontrado": False, "mensaje": "No se encontró información"}


def consultar_dni(dni: str) -> Optional[Dict]:
    """
    Consulta DNI en RENIEC
    Retorna: {dni, nombre_completo, nombres, apellido_paterno, apellido_materno, encontrado}
    """
    if not dni or len(dni) != 8:
        return {"dni": dni, "encontrado": False, "mensaje": "DNI debe tener 8 dígitos"}
    
    if not dni.isdigit():
        return {"dni": dni, "encontrado": False, "mensaje": "DNI debe ser numérico"}
    
    data = api_client.get_person(dni)
    
    if data:
        nombres = data.get('nombres', '')
        ap_paterno = data.get('apellidoPaterno', '')
        ap_materno = data.get('apellidoMaterno', '')
        nombre_completo = f"{ap_paterno} {ap_materno} {nombres}".strip()
        
        return {
            "dni": dni,
            "nombres": nombres,
            "apellido_paterno": ap_paterno,
            "apellido_materno": ap_materno,
            "nombre_completo": nombre_completo,
            "encontrado": True
        }
    
    return {"dni": dni, "encontrado": False, "mensaje": "No se encontró información"}