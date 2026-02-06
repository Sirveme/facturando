/**
 * APP.JS - Menú móvil y funcionalidades globales
 */
console.log('📱 App JS cargado');

document.addEventListener('DOMContentLoaded', function() {
    console.log('🔄 DOM cargado, inicializando...');
    
    // =============================================
    // MENÚ MÓVIL
    // =============================================
    const menuToggle = document.getElementById('menu-toggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobile-overlay');
    
    console.log('Elementos menú:', {
        menuToggle: !!menuToggle,
        sidebar: !!sidebar,
        overlay: !!overlay
    });
    
    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log('🍔 Menu toggle clicked');
            
            const isActive = sidebar.classList.toggle('active');
            menuToggle.classList.toggle('active');
            
            if (overlay) {
                overlay.classList.toggle('active');
            }
            
            document.body.classList.toggle('menu-open');
            console.log('Sidebar active:', isActive);
        });
        
        // Cerrar al hacer clic en overlay
        if (overlay) {
            overlay.addEventListener('click', function() {
                console.log('🔲 Overlay clicked');
                cerrarMenu();
            });
        }
        
        // Cerrar con Escape
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && sidebar.classList.contains('active')) {
                cerrarMenu();
            }
        });
        
        function cerrarMenu() {
            sidebar.classList.remove('active');
            menuToggle.classList.remove('active');
            if (overlay) overlay.classList.remove('active');
            document.body.classList.remove('menu-open');
        }
        
        console.log('✅ Mobile menu initialized');
    } else {
        console.log('❌ Mobile menu elements not found');
    }
});