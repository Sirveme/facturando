"""
Servicio para integración con SUNAT
Maneja generación XML, firma y envío
"""
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, Optional
import xml.etree.ElementTree as ET
from src.models.models import Comprobante, Emisor, LineaDetalle, RespuestaSunat
import hashlib
import base64


class SunatService:
    """Servicio de integración con SUNAT"""
    
    def __init__(self, db: Session):
        self.db = db
        self.sunat_beta_url = "https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService"
        self.sunat_prod_url = "https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService"
    
    def enviar_comprobante(self, comprobante_id: str) -> Dict:
        """
        Enviar comprobante a SUNAT
        
        Args:
            comprobante_id: ID del comprobante
            
        Returns:
            Dict con resultado del envío
        """
        try:
            # Buscar comprobante
            comprobante = self.db.query(Comprobante).filter(
                Comprobante.id == comprobante_id
            ).first()
            
            if not comprobante:
                return {
                    "exito": False,
                    "mensaje": "Comprobante no encontrado"
                }
            
            # Buscar emisor
            emisor = self.db.query(Emisor).filter(
                Emisor.id == comprobante.emisor_id
            ).first()
            
            if not emisor:
                return {
                    "exito": False,
                    "mensaje": "Emisor no encontrado"
                }
            
            # 1. Generar XML
            xml_content = self._generar_xml(comprobante, emisor)
            
            if not xml_content:
                return {
                    "exito": False,
                    "mensaje": "Error generando XML"
                }
            
            # Guardar XML en BD
            comprobante.xml = xml_content
            
            # 2. Generar hash y QR
            comprobante.hash_cpe = self._generar_hash(xml_content)
            comprobante.codigo_qr = self._generar_qr(comprobante, emisor)
            
            # 3. Firmar XML (si hay certificado)
            if emisor.certificado:
                xml_firmado = self._firmar_xml(xml_content, emisor.certificado)
            else:
                xml_firmado = xml_content
            
            # 4. Enviar a SUNAT (simulado por ahora)
            # TODO: Implementar envío real con requests/SOAP
            resultado_sunat = self._enviar_a_sunat_mock(comprobante, emisor)
            
            # 5. Guardar respuesta
            respuesta = RespuestaSunat(
                comprobante_id=comprobante.id,
                codigo_respuesta=resultado_sunat.get('codigo', '0'),
                descripcion_respuesta=resultado_sunat.get('descripcion', ''),
                cdr_xml=resultado_sunat.get('cdr_xml', ''),
                fecha_respuesta=datetime.now()
            )
            
            self.db.add(respuesta)
            
            # Actualizar comprobante
            comprobante.estado = resultado_sunat.get('estado', 'aceptado')
            comprobante.codigo_respuesta = resultado_sunat.get('codigo', '0')
            comprobante.descripcion_respuesta = resultado_sunat.get('descripcion', '')
            comprobante.cdr_xml = resultado_sunat.get('cdr_xml', '')
            comprobante.fecha_envio_sunat = datetime.now()
            
            self.db.commit()
            
            return {
                "exito": resultado_sunat.get('estado') == 'aceptado',
                "mensaje": resultado_sunat.get('descripcion', 'Procesado'),
                "codigo": resultado_sunat.get('codigo', '0')
            }
            
        except Exception as e:
            self.db.rollback()
            return {
                "exito": False,
                "mensaje": f"Error: {str(e)}"
            }
    
    def _generar_xml(self, comprobante: Comprobante, emisor: Emisor) -> Optional[str]:
        """Generar XML UBL 2.1 del comprobante"""
        try:
            # Namespace UBL
            ns = {
                'xmlns': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
                'xmlns:cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
                'xmlns:cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
                'xmlns:ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
            }
            
            # Root element
            invoice = ET.Element('Invoice', ns)
            
            # UBLVersionID
            ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}UBLVersionID').text = '2.1'
            
            # CustomizationID
            ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CustomizationID').text = '2.0'
            
            # ID
            ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID').text = f"{comprobante.serie}-{comprobante.numero}"
            
            # IssueDate
            ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}IssueDate').text = comprobante.fecha_emision.strftime('%Y-%m-%d')
            
            # InvoiceTypeCode
            ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}InvoiceTypeCode').text = comprobante.tipo_documento
            
            # DocumentCurrencyCode
            ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}DocumentCurrencyCode').text = comprobante.moneda
            
            # Signature (placeholder)
            signature = ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Signature')
            ET.SubElement(signature, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID').text = emisor.ruc
            
            # AccountingSupplierParty (Emisor)
            supplier = ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}AccountingSupplierParty')
            party = ET.SubElement(supplier, '{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Party')
            party_id = ET.SubElement(party, '{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}PartyIdentification')
            ET.SubElement(party_id, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID').text = emisor.ruc
            
            party_name = ET.SubElement(party, '{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}PartyName')
            ET.SubElement(party_name, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Name').text = emisor.razon_social
            
            # LegalMonetaryTotal
            monetary_total = ET.SubElement(invoice, '{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}LegalMonetaryTotal')
            ET.SubElement(monetary_total, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}PayableAmount', currencyID=comprobante.moneda).text = str(comprobante.monto_total)
            
            # Convertir a string
            xml_string = ET.tostring(invoice, encoding='unicode', method='xml')
            
            return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_string}'
            
        except Exception as e:
            print(f"Error generando XML: {e}")
            return None
    
    def _firmar_xml(self, xml_content: str, certificado_id: str) -> str:
        """Firmar XML con certificado digital"""
        # TODO: Implementar firma digital real
        # Por ahora retornar el XML sin firmar
        return xml_content
    
    def _generar_hash(self, xml_content: str) -> str:
        """Generar hash SHA-256 del XML"""
        return hashlib.sha256(xml_content.encode()).hexdigest()
    
    def _generar_qr(self, comprobante: Comprobante, emisor: Emisor) -> str:
        """Generar código QR del comprobante"""
        # Formato QR: RUC|TipoDoc|Serie|Numero|IGV|Total|Fecha|TipoDocCliente|NumDocCliente
        qr_data = f"{emisor.ruc}|{comprobante.tipo_documento}|{comprobante.serie}|{comprobante.numero}|{comprobante.monto_igv}|{comprobante.monto_total}|{comprobante.fecha_emision.strftime('%Y-%m-%d')}|||"
        
        return base64.b64encode(qr_data.encode()).decode()
    
    def _enviar_a_sunat_mock(self, comprobante: Comprobante, emisor: Emisor) -> Dict:
        """
        Simulación de envío a SUNAT
        TODO: Reemplazar con envío real usando SOAP/requests
        """
        import random
        
        # Simular respuesta SUNAT (90% éxito, 10% rechazo)
        if random.random() < 0.9:
            return {
                "estado": "aceptado",
                "codigo": "0",
                "descripcion": "La Factura numero F001-00000001, ha sido aceptada",
                "cdr_xml": "<?xml version='1.0'?><CDR>Aceptado</CDR>"
            }
        else:
            # Errores comunes SUNAT
            errores = [
                ("2324", "El RUC del emisor no está activo"),
                ("2335", "El número de RUC del receptor no existe"),
                ("2108", "El certificado digital ha caducado"),
                ("2109", "La fecha de emisión no puede ser mayor a la fecha actual")
            ]
            
            error = random.choice(errores)
            
            return {
                "estado": "rechazado",
                "codigo": error[0],
                "descripcion": error[1],
                "cdr_xml": f"<?xml version='1.0'?><CDR>Rechazado: {error[1]}</CDR>"
            }