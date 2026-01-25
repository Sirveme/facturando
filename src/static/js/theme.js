// Theme switcher - Dark mode POR DEFECTO
console.log('🌙 Theme JS cargado');

(function() {
  // Aplicar tema INMEDIATAMENTE antes de que cargue la página
  const savedTheme = localStorage.getItem('theme');
  const currentTheme = savedTheme || 'dark';
  document.documentElement.setAttribute('data-theme', currentTheme);
  
  // Si no hay tema guardado, guardar dark
  if (!savedTheme) {
    localStorage.setItem('theme', 'dark');
  }
  
  console.log('🎨 Tema aplicado:', currentTheme);
})();

// Después de que cargue el DOM
document.addEventListener('DOMContentLoaded', function() {
  const themeToggle = document.getElementById('theme-toggle');
  
  console.log('Theme toggle encontrado:', !!themeToggle);
  
  if (themeToggle) {
    // Actualizar icono según tema actual
    function updateThemeIcon() {
      const theme = document.documentElement.getAttribute('data-theme');
      const icon = themeToggle.querySelector('svg');
      
      if (theme === 'dark') {
        // Icono de sol (cambiar a light)
        icon.innerHTML = `
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/>
        `;
      } else {
        // Icono de luna (cambiar a dark)
        icon.innerHTML = `
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/>
        `;
      }
    }
    
    // Actualizar icono inicial
    updateThemeIcon();
    
    // Toggle theme al hacer click
    themeToggle.addEventListener('click', function(e) {
      e.preventDefault();
      const currentTheme = document.documentElement.getAttribute('data-theme');
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      
      console.log('🔄 Cambiando tema de', currentTheme, 'a', newTheme);
      
      document.documentElement.setAttribute('data-theme', newTheme);
      localStorage.setItem('theme', newTheme);
      
      // Actualizar icono
      updateThemeIcon();
      
      console.log('✅ Tema cambiado a:', newTheme);
    });
    
    console.log('✅ Theme toggle initialized');
  } else {
    console.error('❌ Theme toggle button not found');
  }
});