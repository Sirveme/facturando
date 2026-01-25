// Toast Notification System
// Uso: toast.success("Mensaje") o toast.error("Error", "Descripción")

const toast = {
  container: null,
  
  init() {
    if (!this.container) {
      this.container = document.getElementById('toast-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        document.body.appendChild(this.container);
      }
    }
  },
  
  show(title, description = '', type = 'info', duration = 5000) {
    this.init();
    
    const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.id = id;
    
    // Icono según tipo
    const icons = {
      success: '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>',
      error: '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>',
      warning: '<path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>',
      info: '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>',
      loading: '<div class="toast-spinner"></div>'
    };
    
    toast.innerHTML = `
      <div class="toast-icon">
        ${type === 'loading' ? icons.loading : `<svg width="20" height="20" fill="currentColor" viewBox="0 0 20 20">${icons[type]}</svg>`}
      </div>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        ${description ? `<div class="toast-description">${description}</div>` : ''}
      </div>
      ${type !== 'loading' ? `
        <button class="toast-close" aria-label="Cerrar">
          <svg width="16" height="16" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>
      ` : ''}
      ${type !== 'loading' ? `<div class="toast-progress" style="animation-duration: ${duration}ms;"></div>` : ''}
    `;
    
    this.container.appendChild(toast);
    
    // Close button
    const closeBtn = toast.querySelector('.toast-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this.remove(id));
    }
    
    // Auto-remove
    if (type !== 'loading') {
      setTimeout(() => this.remove(id), duration);
    }
    
    return id;
  },
  
  remove(id) {
    const toast = document.getElementById(id);
    if (toast) {
      toast.classList.add('removing');
      setTimeout(() => toast.remove(), 200);
    }
  },
  
  success(title, description = '') {
    return this.show(title, description, 'success');
  },
  
  error(title, description = '') {
    return this.show(title, description, 'error', 7000);
  },
  
  warning(title, description = '') {
    return this.show(title, description, 'warning', 6000);
  },
  
  info(title, description = '') {
    return this.show(title, description, 'info');
  },
  
  loading(title, description = '') {
    return this.show(title, description, 'loading', 0);
  },
  
  promise(promiseFn, messages) {
    const id = this.loading(messages.loading || 'Procesando...');
    
    return promiseFn()
      .then(result => {
        this.remove(id);
        this.success(messages.success || 'Completado');
        return result;
      })
      .catch(error => {
        this.remove(id);
        this.error(messages.error || 'Error', error.message);
        throw error;
      });
  }
};

// Exponer globalmente
window.toast = toast;

console.log('🍞 Toast system loaded');