// === Modal Control ===
function abrirModalConfig(tab) {
    document.getElementById('modal-config').classList.add('active');
    document.body.style.overflow = 'hidden';
    if (tab) switchTab(tab);
}

function cerrarModalConfig() {
    document.getElementById('modal-config').classList.remove('active');
    document.body.style.overflow = '';
}

// Cerrar con ESC y click fuera
document.getElementById('modal-config').addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) cerrarModalConfig();
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') cerrarModalConfig();
});

// === Tabs ===
function switchTab(tabId) {
    document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');
    document.getElementById(tabId).classList.add('active');
}

document.querySelectorAll('.modal-tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

// === Toast ===
function showToast(msg, type = 'success') {
    const t = document.getElementById('cfg-toast');
    t.textContent = msg;
    t.className = `cfg-toast ${type} show`;
    setTimeout(() => t.classList.remove('show'), 3500);
}

// === Certificado: Drag & Drop + File Select ===
const dropzone = document.getElementById('cert-dropzone');
const fileInput = document.getElementById('archivo-cert');
const fileName = document.getElementById('cert-file-name');

['dragenter', 'dragover'].forEach(ev => {
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
});
['dragleave', 'drop'].forEach(ev => {
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove('dragover'); });
});
dropzone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files[0];
    if (file && (file.name.endsWith('.pfx') || file.name.endsWith('.p12'))) {
        fileInput.files = e.dataTransfer.files;
        mostrarArchivo(file.name);
    }
});
fileInput.addEventListener('change', () => {
    if (fileInput.files.length) mostrarArchivo(fileInput.files[0].name);
});

function mostrarArchivo(name) {
    fileName.querySelector('span').textContent = name;
    fileName.classList.add('visible');
}

// === Subir Certificado ===
async function subirCertificado() {
    const archivo = fileInput.files[0];
    const password = document.getElementById('password-cert').value;

    if (!archivo) return showToast('Selecciona un archivo .pfx o .p12', 'error');
    if (!password) return showToast('Ingresa la contraseña del certificado', 'error');

    const btn = document.getElementById('btn-subir-cert');
    btn.disabled = true;
    btn.textContent = 'Cargando...';

    const formData = new FormData();
    formData.append('archivo', archivo);
    formData.append('password', password);

    try {
        const res = await fetch('/api/configuracion/certificado', 
            { 
                method: 'POST',
                body: formData,
                credentials: 'same-origin' 
            });
        const data = await res.json();

        if (res.ok && data.exito) {
            showToast(data.mensaje, 'success');
            document.getElementById('cert-status').className = 'cfg-status cfg-status-ok';
            document.getElementById('cert-status').textContent = '✅ Vigente hasta ' + data.datos.fecha_vencimiento;
            // Actualizar paso 3 del onboarding
            actualizarPasoOnboarding(3);
        } else {
            showToast(data.detail || data.mensaje || 'Error al cargar', 'error');
        }
    } catch (err) {
        showToast('Error de conexión', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '🔐 Cargar Certificado';
    }
}

// === Guardar Credenciales SOL ===
async function guardarCredencialesSOL() {
    const usuario = document.getElementById('usuario-sol').value;
    const clave = document.getElementById('clave-sol').value;

    if (!usuario) return showToast('Ingresa el usuario SOL', 'error');

    const btn = document.getElementById('btn-guardar-sol');
    btn.disabled = true;
    btn.textContent = 'Guardando...';

    try {
        const res = await fetch('/api/configuracion/credenciales-sol', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json',
            credentials: 'same-origin' },
            body: JSON.stringify({ usuario_sol: usuario, clave_sol: clave })
        });
        const data = await res.json();

        if (res.ok && data.exito) {
            showToast(data.mensaje, 'success');
            document.getElementById('sol-status').className = 'cfg-status cfg-status-ok';
            document.getElementById('sol-status').textContent = '✅ Configurado';
            actualizarPasoOnboarding(4);
        } else {
            showToast(data.detail || data.mensaje || 'Error al guardar', 'error');
        }
    } catch (err) {
        showToast('Error de conexión', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '💾 Guardar Credenciales';
    }
}

// === Guardar Formato ===
async function guardarFormato() {
    const data = {
        formato_factura: document.querySelector('input[name="formato_factura"]:checked').value,
        formato_boleta: document.querySelector('input[name="formato_boleta"]:checked').value,
        formato_nc_nd: document.querySelector('input[name="formato_nc_nd"]:checked').value
    };

    const btn = document.getElementById('btn-guardar-formato');
    btn.disabled = true;
    btn.textContent = 'Guardando...';

    try {
        const res = await fetch('/api/configuracion/formato', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
            credentials: 'same-origin'
        });
        const result = await res.json();

        if (res.ok && result.exito) {
            showToast(result.mensaje, 'success');
        } else {
            showToast(result.detail || result.mensaje || 'Error al guardar', 'error');
        }
    } catch (err) {
        showToast('Error de conexión', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '💾 Guardar Formatos';
    }
}

// === Formato: Toggle visual ===
document.querySelectorAll('.formato-option input').forEach(input => {
    input.addEventListener('change', () => {
        const grid = input.closest('.formato-grid');
        grid.querySelectorAll('.formato-option').forEach(opt => opt.classList.remove('active'));
        input.closest('.formato-option').classList.add('active');
    });
});

// === Actualizar paso onboarding (visual) ===
function actualizarPasoOnboarding(paso) {
    const stepEl = document.querySelector(`.step:nth-child(${paso}) .step-number`);
    if (stepEl) {
        stepEl.classList.remove('pending');
        stepEl.classList.add('done');
        stepEl.textContent = '✓';
    }
}