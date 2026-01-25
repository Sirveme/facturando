// Emitir comprobante - JavaScript
console.log('📝 Emitir JS cargado');

document.addEventListener('DOMContentLoaded', function() {
    // Elementos
    const form = document.getElementById('emitir-form');
    const itemsContainer = document.getElementById('items-container');
    const btnAgregarItem = document.getElementById('btn-agregar-item');
    const btnEmitir = document.getElementById('btn-emitir');
    const alertContainer = document.getElementById('alert-container');
    
    // Fecha actual por defecto
    const fechaInput = document.getElementById('fecha_emision');
    const hoy = new Date().toISOString().split('T')[0];
    fechaInput.value = hoy;
    
    // Contador de items
    let itemCount = 0;
    
    // ========================================
    // AGREGAR ITEM
    // ========================================
    function agregarItem() {
        itemCount++;
        const itemHtml = `
            <div class="item-row" data-item="${itemCount}">
                <div class="input-group">
                    <label class="input-label">Descripción</label>
                    <input 
                        type="text" 
                        name="item_descripcion_${itemCount}" 
                        class="input item-descripcion" 
                        placeholder="Descripción del producto/servicio"
                        required
                    >
                </div>
                
                <div class="input-group">
                    <label class="input-label">Cantidad</label>
                    <input 
                        type="number" 
                        name="item_cantidad_${itemCount}" 
                        class="input item-cantidad" 
                        value="1"
                        min="0.01"
                        step="0.01"
                        required
                    >
                </div>
                
                <div class="input-group">
                    <label class="input-label">Unidad</label>
                    <select name="item_unidad_${itemCount}" class="input item-unidad" required>
                        <option value="NIU">NIU - Unidad</option>
                        <option value="ZZ">ZZ - Servicio</option>
                        <option value="KGM">KGM - Kilogramo</option>
                        <option value="MTR">MTR - Metro</option>
                    </select>
                </div>
                
                <div class="input-group">
                    <label class="input-label">P. Unitario</label>
                    <input 
                        type="number" 
                        name="item_precio_${itemCount}" 
                        class="input item-precio" 
                        placeholder="0.00"
                        min="0"
                        step="0.01"
                        required
                    >
                </div>
                
                <div style="display: flex; align-items: center; margin-top: 26px;">
                    <span>=</span>
                </div>
                
                <div class="input-group">
                    <label class="input-label">Total</label>
                    <input 
                        type="text" 
                        class="input item-total" 
                        value="S/ 0.00"
                        readonly
                        style="background: var(--bg-elevated); font-weight: bold;"
                    >
                </div>
                
                <button type="button" class="btn-remove-item" title="Eliminar item">
                    <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `;
        
        itemsContainer.insertAdjacentHTML('beforeend', itemHtml);
        
        // Agregar eventos al nuevo item
        const newItem = itemsContainer.querySelector(`[data-item="${itemCount}"]`);
        const cantidad = newItem.querySelector('.item-cantidad');
        const precio = newItem.querySelector('.item-precio');
        const btnRemove = newItem.querySelector('.btn-remove-item');
        
        cantidad.addEventListener('input', calcularTotales);
        precio.addEventListener('input', calcularTotales);
        btnRemove.addEventListener('click', function() {
            newItem.remove();
            calcularTotales();
        });
        
        calcularTotales();
    }
    
    // ========================================
    // CALCULAR TOTALES
    // ========================================
    function calcularTotales() {
        const items = document.querySelectorAll('.item-row');
        let subtotal = 0;
        
        items.forEach(item => {
            const cantidad = parseFloat(item.querySelector('.item-cantidad').value) || 0;
            const precio = parseFloat(item.querySelector('.item-precio').value) || 0;
            const totalItem = cantidad * precio;
            
            // Actualizar total del item
            item.querySelector('.item-total').value = `S/ ${totalItem.toFixed(2)}`;
            
            subtotal += totalItem;
        });
        
        const igv = subtotal * 0.18;
        const total = subtotal + igv;
        
        // Actualizar totales
        document.getElementById('subtotal').textContent = `S/ ${subtotal.toFixed(2)}`;
        document.getElementById('igv').textContent = `S/ ${igv.toFixed(2)}`;
        document.getElementById('total').textContent = `S/ ${total.toFixed(2)}`;
    }
    
    // ========================================
    // BUSCAR CLIENTE EN SUNAT (Placeholder)
    // ========================================
    const btnBuscarCliente = document.getElementById('btn-buscar-cliente');
    btnBuscarCliente.addEventListener('click', function() {
        const tipoDoc = document.getElementById('cliente_tipo_doc').value;
        const documento = document.getElementById('cliente_ruc').value;
        
        if (!documento) {
            showAlert('Ingrese el número de documento', 'error');
            return;
        }
        
        // TODO: Integrar API de consulta RUC/DNI
        showAlert('Función de búsqueda en SUNAT próximamente', 'info');
    });
    
    // ========================================
    // SUBMIT FORM
    // ========================================
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        // Validar que haya al menos un item
        const items = document.querySelectorAll('.item-row');
        if (items.length === 0) {
            showAlert('Debe agregar al menos un item', 'error');
            return;
        }
        
        // Preparar datos
        const formData = {
            emisor_ruc: '{{ user_ruc }}',
            tipo_documento: document.getElementById('tipo_documento').value,
            serie: document.getElementById('serie').value,
            numero: parseInt(document.getElementById('numero').value) || null,
            fecha_emision: document.getElementById('fecha_emision').value,
            tipo_comprobante: document.getElementById('tipo_documento').value,
            cliente_ruc: document.getElementById('cliente_ruc').value,
            cliente_razon_social: document.getElementById('cliente_razon_social').value,
            cliente_direccion: document.getElementById('cliente_direccion').value,
            items: []
        };
        
        // Agregar items
        items.forEach((item, index) => {
            const cantidad = parseFloat(item.querySelector('.item-cantidad').value);
            const precio = parseFloat(item.querySelector('.item-precio').value);
            
            formData.items.push({
                orden: index + 1,
                descripcion: item.querySelector('.item-descripcion').value,
                cantidad: cantidad,
                unidad: item.querySelector('.item-unidad').value,
                precio_unitario: precio
            });
        });
        
        // Loading state
        btnEmitir.classList.add('loading');
        btnEmitir.disabled = true;
        
        try {
            const response = await fetch('/api/comprobantes/emitir', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });
            
            const data = await response.json();
            
            if (response.ok && data.exito) {
                showAlert('✓ Comprobante emitido correctamente. Redirigiendo...', 'success');
                
                // Redirigir a comprobantes después de 2 segundos
                setTimeout(() => {
                    window.location.href = '/comprobantes';
                }, 2000);
            } else {
                showAlert(data.mensaje || 'Error al emitir comprobante', 'error');
                btnEmitir.classList.remove('loading');
                btnEmitir.disabled = false;
            }
        } catch (error) {
            console.error('Error:', error);
            showAlert('Error de conexión. Intente nuevamente.', 'error');
            btnEmitir.classList.remove('loading');
            btnEmitir.disabled = false;
        }
    });
    
    // ========================================
    // HELPERS
    // ========================================
    function showAlert(message, type = 'info') {
        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.innerHTML = `
            <svg width="20" height="20" fill="currentColor" viewBox="0 0 20 20">
                ${type === 'success' ? '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>' : ''}
                ${type === 'error' ? '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>' : ''}
                ${type === 'info' ? '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>' : ''}
            </svg>
            <span>${message}</span>
        `;
        
        alertContainer.appendChild(alert);
        
        // Auto-remove después de 5 segundos
        setTimeout(() => {
            alert.remove();
        }, 5000);
    }
    
    // ========================================
    // INIT
    // ========================================
    btnAgregarItem.addEventListener('click', agregarItem);
    
    // Agregar primer item automáticamente
    agregarItem();
    
    console.log('✅ Formulario emitir inicializado');
});