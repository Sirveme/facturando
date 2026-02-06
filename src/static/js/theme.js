/**
 * THEME.JS - Modo día/noche
 */
console.log('🌙 Theme JS cargado');

// Aplicar tema INMEDIATAMENTE antes de que cargue la página
(function() {
    const savedTheme = localStorage.getItem('theme');
    const currentTheme = savedTheme || 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);
    
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
        // Toggle theme al hacer click
        themeToggle.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            
            console.log('🔄 Cambiando tema de', currentTheme, 'a', newTheme);
            
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            
            console.log('✅ Tema cambiado a:', newTheme);
        });
        
        console.log('✅ Theme toggle initialized');
    }
});