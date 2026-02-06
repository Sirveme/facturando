/**
 * NOTA DE CRÉDITO - LÓGICA
 */

// Estado global
let comprobanteSeleccionado = null;
let itemsComprobante = [];

// Constantes
const MOTIVOS = {
    '01': { nombre: 'Anulación de operación', tipo: 'total' },
    '02': { nombre: 'Anulación por error en RUC', tipo: 'total' },
    '03': { nombre: 'Corrección por error en descripción', tipo: 'editable' },
    '04': { nombre: 'Descuento global', tipo: 'descuento_global' },
    '05': { nombre: 'Descuento por ítem', tipo: 'descuento_item' },
    '06': { nombre: 'Devolución total', tipo: 'total' },
    '07': { nombre: 'Devolución parcial', tipo: 'parcial' }
};

// =============================================
// INICIALIZACIÓN
// =============================================
document.addEventListener('DOMContentLoaded', function() {
    initSeleccionComprobante();
    initMotivos();
    initFormulario();
    console.log('✅ Nota de Crédito JS cargado');
});

// =============================================
// SELECCIÓN DE COMPROBANTE
// =============================================
function initSeleccionComprobante() {
    // Click en tarjetas de comprobante
    document.querySelectorAll('.ref-card').forEach(card => {
        card.addEventListener('click', () => seleccionarComprobante(card));
    });
    
    // Búsqueda
    const buscar = document.getElementById('buscar-comprobante');
    if (buscar) {
        buscar.addEventListener('input', filtrarComprobantes);
    }
    
    // Filtro por tipo
    const filtroTipo = document.getElementById('filtro-tipo');
    if (filtroTipo) {
        filtroTipo.addEventListener('change', filtrarComprobantes);
    }
}

async function seleccionarComprobante(card) {
    // Remover selección anterior
    document.querySelectorAll('.ref-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    
    // Guardar datos
    const id = card.dataset.id;
    document.getElementById('comprobante_ref_id').value = id;
    document.getElementById('comprobante_ref_numero').value = card.dataset.numero;
    document.getElementById('comprobante_ref_tipo').value = card.dataset.tipo;
    
    comprobanteSeleccionado = {
        id: id,
        numero: card.dataset.numero,
        tipo: card.dataset.tipo,
        serie: card.dataset.serie,
        total: parseFloat(card.dataset.total) || 0,
        base: parseFloat(card.dataset.base) || 0,
        igv: parseFloat(card.dataset.igv) || 0,
        cliente: card.dataset.cliente,
        clienteDoc: card.dataset.clienteDoc
    };
    
    // Cargar items
    await cargarItems(id);
    
    // Actualizar vista según motivo seleccionado
    const motivoSeleccionado = document.querySelector('input[name="motivo"]:checked')?.value;
    if (motivoSeleccionado) {
        actualizarVistaMotivo(motivoSeleccionado);
    }
}

async function cargarItems(comprobanteId) {
    try {
        const response = await fetch(`/api/comprobantes/${comprobanteId}/detalle`);
        const result = await response.json();
        
        if (result.exito && result.datos && result.datos.items) {
            itemsComprobante = result.datos.items;
            document.getElementById('msg-seleccionar').style.display = 'none';
            document.getElementById('detalle-container').style.display = 'block';
        }
    } catch (error) {
        console.error('Error cargando items:', error);
        toast.error('Error', 'No se pudieron cargar los items del comprobante');
    }
}

function filtrarComprobantes() {
    const busqueda = (document.getElementById('buscar-comprobante')?.value || '').toLowerCase();
    const tipo = document.getElementById('filtro-tipo')?.value || '';
    
    document.querySelectorAll('.ref-card').forEach(card => {
        const texto = `${card.dataset.numero} ${card.dataset.cliente} ${card.dataset.clienteDoc}`.toLowerCase();
        const coincideBusqueda = texto.includes(busqueda);
        const coincideTipo = !tipo || card.dataset.tipo === tipo;
        
        card.style.display = (coincideBusqueda && coincideTipo) ? 'block' : 'none';
    });
}

// =============================================
// MOTIVOS
// =============================================
function initMotivos() {
    document.querySelectorAll('input[name="motivo"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            actualizarVistaMotivo(e.target.value);
        });
    });
}

function actualizarVistaMotivo(motivo) {
    const config = MOTIVOS[motivo];
    if (!config) return;
    
    // Ocultar todos los paneles
    document.querySelectorAll('.detalle-panel').forEach(p => p.classList.remove('active'));
    
    // Mostrar panel correspondiente
    const panel = document.getElementById(`panel-${config.tipo}`);
    if (panel) {
        panel.classList.add('active');
    }
    
    // Renderizar contenido según tipo
    switch (config.tipo) {
        case 'total':
            renderizarTotal();
            break;
        case 'editable':
            renderizarEditable();
            break;
        case 'descuento_global':
            renderizarDescuentoGlobal();
            break;
        case 'descuento_item':
            renderizarDescuentoItem();
            break;
        case 'parcial':
            renderizarParcial();
            break;
    }
}

// =============================================
// RENDERIZADO POR TIPO
// =============================================

// Anulación total / Devolución total / Error RUC
function renderizarTotal() {
    if (!comprobanteSeleccionado || !itemsComprobante.length) return;
    
    const container = document.getElementById('items-total');
    container.innerHTML = itemsComprobante.map((item, i) => `
        <div class="nc-item">
            <div class="nc-item-info">
                <span class="nc-item-desc">${item.descripcion}</span>
                <span class="nc-item-original">${item.cantidad} x S/ ${parseFloat(item.precio_unitario).toFixed(2)}</span>
                <span class="nc-item-monto">S/ ${parseFloat(item.monto_linea).toFixed(2)}</span>
            </div>
        </div>
    `).join('');
    
    actualizarTotales(comprobanteSeleccionado.base, comprobanteSeleccionado.igv, comprobanteSeleccionado.total);
}

// Corrección de descripción
function renderizarEditable() {
    if (!comprobanteSeleccionado || !itemsComprobante.length) return;
    
    const container = document.getElementById('items-editable');
    container.innerHTML = itemsComprobante.map((item, i) => `
        <div class="nc-item">
            <div class="nc-item-info" style="flex-direction: column; gap: var(--space-2);">
                <input type="text" class="input" value="${item.descripcion}" 
                       data-index="${i}" style="width: 100%;"
                       placeholder="Descripción corregida">
                <div style="display: flex; justify-content: space-between; width: 100%;">
                    <span class="nc-item-original">${item.cantidad} x S/ ${parseFloat(item.precio_unitario).toFixed(2)}</span>
                    <span class="nc-item-monto">S/ ${parseFloat(item.monto_linea).toFixed(2)}</span>
                </div>
            </div>
        </div>
    `).join('');
    
    actualizarTotales(comprobanteSeleccionado.base, comprobanteSeleccionado.igv, comprobanteSeleccionado.total);
}

// Descuento global
function renderizarDescuentoGlobal() {
    if (!comprobanteSeleccionado) return;
    
    // Mostrar info del comprobante original
    document.getElementById('dg-total-original').textContent = `S/ ${comprobanteSeleccionado.total.toFixed(2)}`;
    document.getElementById('dg-base-original').textContent = `S/ ${comprobanteSeleccionado.base.toFixed(2)}`;
    
    // Limpiar valores
    document.getElementById('dg-valor').value = '';
    calcularDescuentoGlobal();
}

function calcularDescuentoGlobal() {
    if (!comprobanteSeleccionado) return;
    
    const tipo = document.getElementById('dg-tipo').value;
    const valor = parseFloat(document.getElementById('dg-valor').value) || 0;
    
    let descuentoBase = 0;
    
    if (tipo === 'porcentaje') {
        if (valor > 100) {
            toast.warning('Valor inválido', 'El porcentaje no puede ser mayor a 100%');
            return;
        }
        descuentoBase = round(comprobanteSeleccionado.base * (valor / 100), 2);
    } else {
        if (valor > comprobanteSeleccionado.base) {
            toast.warning('Valor inválido', 'El monto no puede ser mayor al total');
            return;
        }
        descuentoBase = round(valor, 2);
    }
    
    const descuentoIGV = round(descuentoBase * 0.18, 2);
    const descuentoTotal = round(descuentoBase + descuentoIGV, 2);
    
    // Actualizar preview
    document.getElementById('dg-descuento-base').textContent = `S/ ${descuentoBase.toFixed(2)}`;
    document.getElementById('dg-descuento-igv').textContent = `S/ ${descuentoIGV.toFixed(2)}`;
    document.getElementById('dg-descuento-total').textContent = `S/ ${descuentoTotal.toFixed(2)}`;
    
    actualizarTotales(descuentoBase, descuentoIGV, descuentoTotal);
}

// Descuento por ítem
function renderizarDescuentoItem() {
    if (!comprobanteSeleccionado || !itemsComprobante.length) return;
    
    const container = document.getElementById('items-descuento');
    container.innerHTML = itemsComprobante.map((item, i) => `
        <div class="nc-item">
            <input type="checkbox" data-index="${i}" checked>
            <div class="nc-item-info">
                <div>
                    <span class="nc-item-desc">${item.descripcion}</span>
                    <span class="nc-item-original" style="margin-left: 8px;">
                        (Original: S/ ${parseFloat(item.monto_linea).toFixed(2)})
                    </span>
                </div>
                <div class="nc-item-input">
                    <input type="number" class="input" data-index="${i}" 
                           value="0" min="0" step="0.01" 
                           onchange="calcularDescuentoItem()">
                    <select class="input" data-index="${i}" onchange="calcularDescuentoItem()">
                        <option value="monto">S/</option>
                        <option value="porcentaje">%</option>
                    </select>
                    <span class="nc-item-monto" data-monto="${i}">S/ 0.00</span>
                </div>
            </div>
        </div>
    `).join('');
    
    // Eventos checkbox
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', calcularDescuentoItem);
    });
    
    calcularDescuentoItem();
}

function calcularDescuentoItem() {
    let totalBase = 0;
    
    document.querySelectorAll('#items-descuento .nc-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        const valorInput = item.querySelector('input[type="number"]');
        const tipoSelect = item.querySelector('select');
        const montoSpan = item.querySelector('.nc-item-monto');
        const index = parseInt(valorInput.dataset.index);
        
        if (!checkbox.checked || !itemsComprobante[index]) {
            montoSpan.textContent = 'S/ 0.00';
            return;
        }
        
        const valor = parseFloat(valorInput.value) || 0;
        const tipo = tipoSelect.value;
        const montoOriginal = parseFloat(itemsComprobante[index].monto_linea) || 0;
        
        let descuento = 0;
        if (tipo === 'porcentaje') {
            descuento = round(montoOriginal * (valor / 100), 2);
        } else {
            descuento = round(Math.min(valor, montoOriginal), 2);
        }
        
        montoSpan.textContent = `S/ ${descuento.toFixed(2)}`;
        totalBase += descuento;
    });
    
    const totalIGV = round(totalBase * 0.18, 2);
    const total = round(totalBase + totalIGV, 2);
    
    actualizarTotales(totalBase, totalIGV, total);
}

// Devolución parcial
function renderizarParcial() {
    if (!comprobanteSeleccionado || !itemsComprobante.length) return;
    
    const container = document.getElementById('items-parcial');
    container.innerHTML = itemsComprobante.map((item, i) => `
        <div class="nc-item">
            <input type="checkbox" data-index="${i}" checked>
            <div class="nc-item-info">
                <span class="nc-item-desc">${item.descripcion}</span>
                <div class="nc-item-input">
                    <label style="font-size: 12px; color: var(--text-secondary);">Cant:</label>
                    <input type="number" class="input" data-index="${i}" 
                           value="${item.cantidad}" min="0.01" max="${item.cantidad}" step="0.01"
                           style="width: 80px;" onchange="calcularParcial()">
                    <span style="color: var(--text-muted);">/ ${item.cantidad}</span>
                    <span style="margin-left: 8px;">x S/ ${parseFloat(item.precio_unitario).toFixed(2)}</span>
                    <span class="nc-item-monto" data-monto="${i}">S/ ${parseFloat(item.monto_linea).toFixed(2)}</span>
                </div>
            </div>
        </div>
    `).join('');
    
    // Eventos checkbox
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', calcularParcial);
    });
    
    calcularParcial();
}

function calcularParcial() {
    let totalBase = 0;
    
    document.querySelectorAll('#items-parcial .nc-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        const cantidadInput = item.querySelector('input[type="number"]');
        const montoSpan = item.querySelector('.nc-item-monto');
        const index = parseInt(cantidadInput.dataset.index);
        
        if (!checkbox.checked || !itemsComprobante[index]) {
            montoSpan.textContent = 'S/ 0.00';
            return;
        }
        
        const cantidad = parseFloat(cantidadInput.value) || 0;
        const precioUnit = parseFloat(itemsComprobante[index].precio_unitario) || 0;
        const monto = round(cantidad * precioUnit, 2);
        
        montoSpan.textContent = `S/ ${monto.toFixed(2)}`;
        totalBase += monto;
    });
    
    const totalIGV = round(totalBase * 0.18, 2);
    const total = round(totalBase + totalIGV, 2);
    
    actualizarTotales(totalBase, totalIGV, total);
}

// =============================================
// TOTALES
// =============================================
function actualizarTotales(base, igv, total) {
    document.getElementById('nc-subtotal').textContent = `S/ ${base.toFixed(2)}`;
    document.getElementById('nc-igv').textContent = `S/ ${igv.toFixed(2)}`;
    document.getElementById('nc-total').textContent = `S/ ${total.toFixed(2)}`;
}

// =============================================
// ENVÍO DEL FORMULARIO
// =============================================
function initFormulario() {
    const form = document.getElementById('form-nota-credito');
    if (form) {
        form.addEventListener('submit', enviarNC);
    }
}

async function enviarNC(e) {
    e.preventDefault();
    
    if (!comprobanteSeleccionado) {
        toast.warning('Selecciona comprobante', 'Debes seleccionar un comprobante de referencia');
        return;
    }
    
    const motivo = document.querySelector('input[name="motivo"]:checked').value;
    const config = MOTIVOS[motivo];
    
    // Recopilar items según tipo
    const items = obtenerItemsSegunMotivo(motivo, config.tipo);
    
    if (items.length === 0) {
        toast.warning('Sin items', 'Debes seleccionar al menos un item o ingresar un descuento');
        return;
    }
    
    // Determinar serie NC según comprobante original
    const serieOriginal = comprobanteSeleccionado.serie;
    const serieNC = serieOriginal.startsWith('F') ? 'FC01' : 'BC01';
    
    const data = {
        tipo_documento: '07',
        serie: serieNC,
        comprobante_ref_id: comprobanteSeleccionado.id,
        comprobante_ref_tipo: comprobanteSeleccionado.tipo,
        comprobante_ref_numero: comprobanteSeleccionado.numero,
        motivo: motivo,
        items: items,
        observaciones: document.getElementById('observaciones').value
    };
    
    const btn = document.getElementById('btn-emitir-nc');
    btn.disabled = true;
    const toastId = toast.loading('Emitiendo Nota de Crédito...');
    
    try {
        const response = await fetch('/api/comprobantes/nota-credito', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        toast.remove(toastId);
        
        if (response.ok && result.exito) {
            toast.success('¡NC emitida!', result.mensaje);
            setTimeout(() => window.location.href = '/comprobantes', 2000);
        } else {
            toast.error('Error', result.detail || result.mensaje || 'Error al emitir NC');
        }
    } catch (error) {
        toast.remove(toastId);
        toast.error('Error de conexión', error.message);
    } finally {
        btn.disabled = false;
    }
}

function obtenerItemsSegunMotivo(motivo, tipo) {
    const items = [];
    
    switch (tipo) {
        case 'total':
            // Todos los items originales
            itemsComprobante.forEach(item => {
                items.push({
                    descripcion: item.descripcion,
                    cantidad: parseFloat(item.cantidad),
                    unidad_medida: item.unidad || 'NIU',
                    precio_unitario: parseFloat(item.precio_unitario),
                    tipo_afectacion_igv: '10'
                });
            });
            break;
            
        case 'editable':
            // Items con descripción editada
            document.querySelectorAll('#items-editable input[type="text"]').forEach(input => {
                const index = parseInt(input.dataset.index);
                if (itemsComprobante[index]) {
                    items.push({
                        descripcion: input.value || itemsComprobante[index].descripcion,
                        cantidad: parseFloat(itemsComprobante[index].cantidad),
                        unidad_medida: itemsComprobante[index].unidad || 'NIU',
                        precio_unitario: parseFloat(itemsComprobante[index].precio_unitario),
                        tipo_afectacion_igv: '10'
                    });
                }
            });
            break;
            
        case 'descuento_global':
            // Un solo item con el descuento
            const dgTipo = document.getElementById('dg-tipo').value;
            const dgValor = parseFloat(document.getElementById('dg-valor').value) || 0;
            let descBase = dgTipo === 'porcentaje' 
                ? round(comprobanteSeleccionado.base * (dgValor / 100), 2)
                : round(dgValor, 2);
            
            if (descBase > 0) {
                const descripcion = dgTipo === 'porcentaje'
                    ? `Descuento global ${dgValor}% sobre ${comprobanteSeleccionado.numero}`
                    : `Descuento global S/ ${dgValor.toFixed(2)} sobre ${comprobanteSeleccionado.numero}`;
                    
                items.push({
                    descripcion: descripcion,
                    cantidad: 1,
                    unidad_medida: 'ZZ',
                    precio_unitario: descBase,
                    tipo_afectacion_igv: '10'
                });
            }
            break;
            
        case 'descuento_item':
            // Items con descuento individual
            document.querySelectorAll('#items-descuento .nc-item').forEach(item => {
                const checkbox = item.querySelector('input[type="checkbox"]');
                const valorInput = item.querySelector('input[type="number"]');
                const tipoSelect = item.querySelector('select');
                const index = parseInt(valorInput.dataset.index);
                
                if (checkbox.checked && itemsComprobante[index]) {
                    const valor = parseFloat(valorInput.value) || 0;
                    const tipoDesc = tipoSelect.value;
                    const montoOriginal = parseFloat(itemsComprobante[index].monto_linea) || 0;
                    
                    let descuento = tipoDesc === 'porcentaje'
                        ? round(montoOriginal * (valor / 100), 2)
                        : round(Math.min(valor, montoOriginal), 2);
                    
                    if (descuento > 0) {
                        items.push({
                            descripcion: `Descuento: ${itemsComprobante[index].descripcion}`,
                            cantidad: 1,
                            unidad_medida: 'ZZ',
                            precio_unitario: descuento,
                            tipo_afectacion_igv: '10'
                        });
                    }
                }
            });
            break;
            
        case 'parcial':
            // Items con cantidad parcial
            document.querySelectorAll('#items-parcial .nc-item').forEach(item => {
                const checkbox = item.querySelector('input[type="checkbox"]');
                const cantidadInput = item.querySelector('input[type="number"]');
                const index = parseInt(cantidadInput.dataset.index);
                
                if (checkbox.checked && itemsComprobante[index]) {
                    const cantidad = parseFloat(cantidadInput.value) || 0;
                    if (cantidad > 0) {
                        items.push({
                            descripcion: itemsComprobante[index].descripcion,
                            cantidad: cantidad,
                            unidad_medida: itemsComprobante[index].unidad || 'NIU',
                            precio_unitario: parseFloat(itemsComprobante[index].precio_unitario),
                            tipo_afectacion_igv: '10'
                        });
                    }
                }
            });
            break;
    }
    
    return items;
}

// =============================================
// UTILIDADES
// =============================================
function round(value, decimals) {
    return Number(Math.round(value + 'e' + decimals) + 'e-' + decimals);
}

function seleccionarTodos(containerId) {
    document.querySelectorAll(`#${containerId} input[type="checkbox"]`).forEach(cb => cb.checked = true);
    recalcularSegunMotivo();
}

function deseleccionarTodos(containerId) {
    document.querySelectorAll(`#${containerId} input[type="checkbox"]`).forEach(cb => cb.checked = false);
    recalcularSegunMotivo();
}

function recalcularSegunMotivo() {
    const motivo = document.querySelector('input[name="motivo"]:checked')?.value;
    if (!motivo) return;
    
    const config = MOTIVOS[motivo];
    switch (config.tipo) {
        case 'descuento_item':
            calcularDescuentoItem();
            break;
        case 'parcial':
            calcularParcial();
            break;
    }
}