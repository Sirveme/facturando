/**
 * PRODUCTOS - LÓGICA
 */

let productosData = [];
let paginaActual = 1;
const ITEMS_POR_PAGINA = 50;

// =============================================
// INICIALIZACIÓN
// =============================================
document.addEventListener('DOMContentLoaded', function() {
    cargarProductos();
    cargarCategorias();
    initUploadArea();
    initManejaStock();
    console.log('✅ Productos JS cargado');
});

// =============================================
// CARGAR PRODUCTOS
// =============================================
async function cargarProductos() {
    const buscar = document.getElementById('buscar').value;
    const categoria = document.getElementById('filtro-categoria').value;
    const estado = document.getElementById('filtro-estado').value;
    
    let url = `/api/productos?page=${paginaActual}&limit=${ITEMS_POR_PAGINA}`;
    if (buscar) url += `&q=${encodeURIComponent(buscar)}`;
    if (categoria) url += `&categoria=${encodeURIComponent(categoria)}`;
    if (estado !== '') url += `&activo=${estado}`;
    
    try {
        const response = await fetch(url);
        const result = await response.json();
        
        if (result.exito) {
            productosData = result.datos;
            renderizarTabla(result.datos);
            renderizarPaginacion(result.total, result.pages);
            actualizarEstadisticas(result.total);
        }
    } catch (error) {
        console.error('Error cargando productos:', error);
        toast.error('Error', 'No se pudieron cargar los productos');
    }
}

// =============================================
// RENDERIZAR TABLA
// =============================================
function renderizarTabla(productos) {
    const tbody = document.getElementById('tabla-productos');
    
    if (productos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="text-center" style="padding: var(--space-8);">
                    <div class="empty-state">
                        <div class="empty-state-icon">📦</div>
                        <p style="color: var(--text-primary);">No hay productos</p>
                        <p class="text-secondary">Agrega tu primer producto o importa desde un archivo</p>
                    </div>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = productos.map(p => `
        <tr>
            <td>
                <button class="btn-favorito ${p.es_favorito ? 'activo' : ''}" onclick="toggleFavorito('${p.id}')">
                    ${p.es_favorito ? '⭐' : '☆'}
                </button>
            </td>
            <td><strong>${p.codigo_interno || '-'}</strong></td>
            <td>
                ${p.descripcion}
                ${p.marca ? `<br><span class="text-secondary" style="font-size: 11px;">${p.marca}</span>` : ''}
            </td>
            <td><span class="text-secondary">${p.categoria || '-'}</span></td>
            <td class="text-right">
                <strong>S/ ${p.precio_venta.toFixed(2)}</strong>
            </td>
            <td class="text-right">
                ${p.maneja_stock ? 
                    `<span class="${p.stock_actual <= p.stock_minimo ? 'text-danger' : ''}">${p.stock_actual}</span>` : 
                    '<span class="text-secondary">-</span>'}
            </td>
            <td class="text-center">
                <span class="badge-${p.activo ? 'activo' : 'inactivo'}">
                    ${p.activo ? 'Activo' : 'Inactivo'}
                </span>
            </td>
            <td>
                <div class="acciones-fila">
                    <button class="btn-accion" onclick="editarProducto('${p.id}')" title="Editar">✏️</button>
                    <button class="btn-accion danger" onclick="eliminarProducto('${p.id}')" title="Eliminar">🗑️</button>
                </div>
            </td>
        </tr>
    `).join('');
}

// =============================================
// PAGINACIÓN
// =============================================
function renderizarPaginacion(total, totalPaginas) {
    const container = document.getElementById('paginacion');
    
    if (totalPaginas <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = `
        <button onclick="cambiarPagina(${paginaActual - 1})" ${paginaActual === 1 ? 'disabled' : ''}>
            ← Anterior
        </button>
    `;
    
    for (let i = 1; i <= totalPaginas; i++) {
        if (i === 1 || i === totalPaginas || (i >= paginaActual - 2 && i <= paginaActual + 2)) {
            html += `<button class="${i === paginaActual ? 'active' : ''}" onclick="cambiarPagina(${i})">${i}</button>`;
        } else if (i === paginaActual - 3 || i === paginaActual + 3) {
            html += `<span style="padding: 0 8px;">...</span>`;
        }
    }
    
    html += `
        <button onclick="cambiarPagina(${paginaActual + 1})" ${paginaActual === totalPaginas ? 'disabled' : ''}>
            Siguiente →
        </button>
    `;
    
    container.innerHTML = html;
}

function cambiarPagina(pagina) {
    paginaActual = pagina;
    cargarProductos();
}

// =============================================
// BÚSQUEDA
// =============================================
let timeoutBusqueda;
function buscarProductos() {
    clearTimeout(timeoutBusqueda);
    timeoutBusqueda = setTimeout(() => {
        paginaActual = 1;
        cargarProductos();
    }, 300);
}

// =============================================
// CATEGORÍAS
// =============================================
async function cargarCategorias() {
    try {
        const response = await fetch('/api/productos/categorias/lista');
        const result = await response.json();
        
        if (result.exito) {
            const select = document.getElementById('filtro-categoria');
            const datalist = document.getElementById('categorias-list');
            
            result.datos.forEach(cat => {
                select.innerHTML += `<option value="${cat}">${cat}</option>`;
                if (datalist) {
                    datalist.innerHTML += `<option value="${cat}">`;
                }
            });
        }
    } catch (error) {
        console.error('Error cargando categorías:', error);
    }
}

// =============================================
// ESTADÍSTICAS
// =============================================
function actualizarEstadisticas(total) {
    document.getElementById('stat-total').textContent = total;
    
    const favoritos = productosData.filter(p => p.es_favorito).length;
    document.getElementById('stat-favoritos').textContent = favoritos;
    
    const stockBajo = productosData.filter(p => p.maneja_stock && p.stock_actual <= p.stock_minimo).length;
    document.getElementById('stat-stock-bajo').textContent = stockBajo;
}

// =============================================
// MODAL PRODUCTO
// =============================================
function abrirModalProducto() {
    document.getElementById('modal-producto-titulo').textContent = 'Nuevo Producto';
    document.getElementById('form-producto').reset();
    document.getElementById('producto-id').value = '';
    document.getElementById('campos-stock').style.display = 'none';
    document.getElementById('modal-producto').classList.add('active');
}

function cerrarModalProducto() {
    document.getElementById('modal-producto').classList.remove('active');
}

async function editarProducto(id) {
    try {
        const response = await fetch(`/api/productos/${id}`);
        const result = await response.json();
        
        if (result.exito) {
            const p = result.datos;
            
            document.getElementById('modal-producto-titulo').textContent = 'Editar Producto';
            document.getElementById('producto-id').value = p.id;
            document.getElementById('codigo_interno').value = p.codigo_interno || '';
            document.getElementById('codigo_barras').value = p.codigo_barras || '';
            document.getElementById('descripcion').value = p.descripcion || '';
            document.getElementById('categoria').value = p.categoria || '';
            document.getElementById('marca').value = p.marca || '';
            document.getElementById('precio_venta').value = p.precio_venta || 0;
            document.getElementById('precio_compra').value = p.precio_compra || 0;
            document.getElementById('unidad_medida').value = p.unidad_medida || 'NIU';
            document.getElementById('afecto_igv').value = p.afecto_igv ? 'true' : 'false';
            document.getElementById('maneja_stock').checked = p.maneja_stock;
            document.getElementById('stock_actual').value = p.stock_actual || 0;
            document.getElementById('stock_minimo').value = p.stock_minimo || 0;
            
            document.getElementById('campos-stock').style.display = p.maneja_stock ? 'grid' : 'none';
            
            document.getElementById('modal-producto').classList.add('active');
        }
    } catch (error) {
        toast.error('Error', 'No se pudo cargar el producto');
    }
}

async function guardarProducto() {
    const id = document.getElementById('producto-id').value;
    
    const data = {
        codigo_interno: document.getElementById('codigo_interno').value,
        codigo_barras: document.getElementById('codigo_barras').value,
        descripcion: document.getElementById('descripcion').value,
        categoria: document.getElementById('categoria').value,
        marca: document.getElementById('marca').value,
        precio_venta: parseFloat(document.getElementById('precio_venta').value) || 0,
        precio_compra: parseFloat(document.getElementById('precio_compra').value) || 0,
        unidad_medida: document.getElementById('unidad_medida').value,
        afecto_igv: document.getElementById('afecto_igv').value === 'true',
        maneja_stock: document.getElementById('maneja_stock').checked,
        stock_actual: parseFloat(document.getElementById('stock_actual').value) || 0,
        stock_minimo: parseFloat(document.getElementById('stock_minimo').value) || 0
    };
    
    // Validaciones
    if (!data.codigo_interno) {
        toast.warning('Campo requerido', 'El código interno es obligatorio');
        return;
    }
    if (!data.descripcion) {
        toast.warning('Campo requerido', 'La descripción es obligatoria');
        return;
    }
    if (data.precio_venta <= 0) {
        toast.warning('Campo requerido', 'El precio de venta debe ser mayor a 0');
        return;
    }
    
    const url = id ? `/api/productos/${id}` : '/api/productos';
    const method = id ? 'PUT' : 'POST';
    
    try {
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (response.ok && result.exito) {
            toast.success('¡Guardado!', result.mensaje);
            cerrarModalProducto();
            cargarProductos();
            cargarCategorias();
        } else {
            toast.error('Error', result.detail || result.mensaje || 'Error al guardar');
        }
    } catch (error) {
        toast.error('Error', 'Error de conexión');
    }
}

// =============================================
// ELIMINAR
// =============================================
async function eliminarProducto(id) {
    if (!confirm('¿Estás seguro de eliminar este producto?')) return;
    
    try {
        const response = await fetch(`/api/productos/${id}`, { method: 'DELETE' });
        const result = await response.json();
        
        if (result.exito) {
            toast.success('Eliminado', result.mensaje);
            cargarProductos();
        } else {
            toast.error('Error', result.detail || 'Error al eliminar');
        }
    } catch (error) {
        toast.error('Error', 'Error de conexión');
    }
}

// =============================================
// FAVORITOS
// =============================================
async function toggleFavorito(id) {
    try {
        const response = await fetch(`/api/productos/${id}/favorito`, { method: 'POST' });
        const result = await response.json();
        
        if (result.exito) {
            cargarProductos();
        }
    } catch (error) {
        console.error('Error toggle favorito:', error);
    }
}

// =============================================
// MANEJA STOCK
// =============================================
function initManejaStock() {
    const checkbox = document.getElementById('maneja_stock');
    if (checkbox) {
        checkbox.addEventListener('change', function() {
            document.getElementById('campos-stock').style.display = this.checked ? 'grid' : 'none';
        });
    }
}

// =============================================
// IMPORTAR
// =============================================
function abrirModalImportar() {
    document.getElementById('archivo-seleccionado-importar').style.display = 'none';
    document.getElementById('resultado-importacion').style.display = 'none';
    document.getElementById('archivo-importar').value = '';
    document.getElementById('modal-importar').classList.add('active');
}

function cerrarModalImportar() {
    document.getElementById('modal-importar').classList.remove('active');
}

function initUploadArea() {
    const area = document.getElementById('upload-area-importar');
    const input = document.getElementById('archivo-importar');
    
    if (!area || !input) return;
    
    area.addEventListener('click', () => input.click());
    
    area.addEventListener('dragover', (e) => {
        e.preventDefault();
        area.classList.add('dragover');
    });
    
    area.addEventListener('dragleave', () => {
        area.classList.remove('dragover');
    });
    
    area.addEventListener('drop', (e) => {
        e.preventDefault();
        area.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            input.files = e.dataTransfer.files;
            mostrarArchivoSeleccionado(e.dataTransfer.files[0]);
        }
    });
    
    input.addEventListener('change', () => {
        if (input.files.length) {
            mostrarArchivoSeleccionado(input.files[0]);
        }
    });
}

function mostrarArchivoSeleccionado(file) {
    document.getElementById('nombre-archivo-importar').textContent = file.name;
    document.getElementById('archivo-seleccionado-importar').style.display = 'block';
}

async function importarProductos() {
    const input = document.getElementById('archivo-importar');
    if (!input.files.length) {
        toast.warning('Sin archivo', 'Selecciona un archivo para importar');
        return;
    }
    
    const formData = new FormData();
    formData.append('archivo', input.files[0]);
    
    const btn = document.getElementById('btn-importar');
    btn.disabled = true;
    btn.textContent = 'Importando...';
    
    try {
        const response = await fetch('/api/productos/importar', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        const resultDiv = document.getElementById('resultado-importacion');
        resultDiv.style.display = 'block';
        
        if (response.ok && result.exito) {
            resultDiv.innerHTML = `
                <div class="info-message" style="background: rgba(34, 197, 94, 0.1); border-color: rgba(34, 197, 94, 0.3);">
                    ✅ ${result.mensaje}<br>
                    <strong>${result.importados}</strong> nuevos, 
                    <strong>${result.actualizados}</strong> actualizados
                    ${result.errores.length ? `<br><small>⚠️ ${result.errores.length} errores</small>` : ''}
                </div>
            `;
            cargarProductos();
            cargarCategorias();
        } else {
            resultDiv.innerHTML = `
                <div class="info-message" style="background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3);">
                    ❌ ${result.detail || 'Error al importar'}
                </div>
            `;
        }
    } catch (error) {
        toast.error('Error', 'Error de conexión');
    } finally {
        btn.disabled = false;
        btn.textContent = '📥 Importar';
    }
}