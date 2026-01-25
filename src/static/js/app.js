// App JS - Funcionalidad del dashboard
console.log('📱 App JS cargado');

// ========================================
// MOBILE MENU
// ========================================
// Mobile menu
document.addEventListener('DOMContentLoaded', function() {
  console.log('🔄 DOM cargado, inicializando...');
  
  const menuToggle = document.getElementById('mobile-menu-toggle');
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.getElementById('mobile-overlay');
  
  console.log('Elementos encontrados:', {
    menuToggle: !!menuToggle,
    sidebar: !!sidebar,
    overlay: !!overlay
  });
  
  if (menuToggle && sidebar && overlay) {
    // Toggle menú
    menuToggle.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();
      
      console.log('🍔 Toggle menu clicked');
      
      const isActive = sidebar.classList.contains('active');
      
      if (isActive) {
        sidebar.classList.remove('active');
        overlay.classList.remove('active');
        document.body.style.overflow = '';
      } else {
        sidebar.classList.add('active');
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden'; // Prevenir scroll
      }
      
      console.log('Sidebar active:', sidebar.classList.contains('active'));
    });
    
    // Cerrar con overlay
    overlay.addEventListener('click', function() {
      console.log('📱 Overlay clicked - closing');
      sidebar.classList.remove('active');
      overlay.classList.remove('active');
      document.body.style.overflow = '';
    });
    
    // Cerrar con links (solo móvil)
    const sidebarLinks = sidebar.querySelectorAll('.sidebar-link');
    sidebarLinks.forEach(link => {
      link.addEventListener('click', function() {
        if (window.innerWidth <= 768) {
          console.log('🔗 Link clicked - closing mobile menu');
          sidebar.classList.remove('active');
          overlay.classList.remove('active');
          document.body.style.overflow = '';
        }
      });
    });
    
    console.log('✅ Mobile menu initialized');
  } else {
    console.error('❌ Mobile menu elements not found');
  }
});