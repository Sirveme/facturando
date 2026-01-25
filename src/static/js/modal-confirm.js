// Modal de confirmación elegante
// Uso: await confirmModal("¿Título?", "Descripción") → true/false

window.confirmModal = function(title, description = '', confirmText = 'Confirmar', cancelText = 'Cancelar') {
    return new Promise((resolve) => {
        // Crear modal
        const modal = document.createElement('div');
        modal.className = 'modal active';
        modal.id = 'modal-confirm-temp';
        
        modal.innerHTML = `
            <div class="modal-backdrop"></div>
            <div class="modal-content" style="max-width: 480px;">
                <div class="modal-header">
                    <h3 class="modal-title">${title}</h3>
                </div>
                <div class="modal-body">
                    <p style="color: var(--text-secondary); line-height: 1.6;">
                        ${description}
                    </p>
                </div>
                <div class="modal-footer" style="justify-content: flex-end; gap: var(--space-3);">
                    <button class="btn btn-ghost" id="modal-confirm-cancel">
                        ${cancelText}
                    </button>
                    <button class="btn btn-primary" id="modal-confirm-ok">
                        ${confirmText}
                    </button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        document.body.style.overflow = 'hidden';
        
        // Focus en botón confirmar
        setTimeout(() => {
            document.getElementById('modal-confirm-ok').focus();
        }, 100);
        
        // Handlers
        function cleanup(result) {
            modal.remove();
            document.body.style.overflow = '';
            resolve(result);
        }
        
        document.getElementById('modal-confirm-ok').addEventListener('click', () => cleanup(true));
        document.getElementById('modal-confirm-cancel').addEventListener('click', () => cleanup(false));
        modal.querySelector('.modal-backdrop').addEventListener('click', () => cleanup(false));
        
        // ESC para cancelar
        function handleEsc(e) {
            if (e.key === 'Escape') {
                cleanup(false);
                document.removeEventListener('keydown', handleEsc);
            }
        }
        document.addEventListener('keydown', handleEsc);
    });
};

console.log('✅ Modal confirm loaded');