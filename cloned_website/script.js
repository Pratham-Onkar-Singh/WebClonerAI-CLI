// Scroll Animation Observer
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const animateOnScroll = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('animate-fade-in');
            animateOnScroll.unobserve(entry.target);
        }
    });
}, observerOptions);

// Observe elements for animation
document.querySelectorAll('.program-card, .why-card, .testimonial-card').forEach(el => {
    el.style.opacity = '0';
    animateOnScroll.observe(el);
});

// Navbar scroll effect
let lastScroll = 0;
const navbar = document.querySelector('.navbar');

window.addEventListener('scroll', () => {
    const currentScroll = window.pageYOffset;
    
    if (currentScroll > 100) {
        navbar.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)';
    } else {
        navbar.style.boxShadow = 'none';
    }
    
    lastScroll = currentScroll;
});

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Button hover effects
const buttons = document.querySelectorAll('button');
buttons.forEach(button => {
    button.addEventListener('mouseenter', function() {
        this.style.transform = 'translateY(-2px)';
    });
    
    button.addEventListener('mouseleave', function() {
        this.style.transform = 'translateY(0)';
    });
});

// Play button click handler
const playButtons = document.querySelectorAll('.play-button, .play-circle');
playButtons.forEach(button => {
    button.addEventListener('click', function() {
        // Animation pulse effect
        this.classList.add('animate-pulse');
        setTimeout(() => {
            this.classList.remove('animate-pulse');
        }, 500);
        
        // In a real implementation, this would open a video modal
        console.log('Video play clicked');
    });
});

// Program cards hover animation
const programCards = document.querySelectorAll('.program-card');
programCards.forEach(card => {
    card.addEventListener('mouseenter', function() {
        this.style.transition = 'all 0.3s ease';
    });
    
    card.addEventListener('mouseleave', function() {
        this.style.transition = 'all 0.3s ease';
    });
});

// Why cards stagger animation
const whyCards = document.querySelectorAll('.why-card');
whyCards.forEach((card, index) => {
    card.style.animationDelay = `${index * 0.1}s`;
});

// Testimonial cards animation
const testimonialCards = document.querySelectorAll('.testimonial-card');
testimonialCards.forEach((card, index) => {
    card.style.animationDelay = `${index * 0.2}s`;
});

// People images parallax effect
const peopleImages = document.querySelectorAll('.people-img');
window.addEventListener('scroll', () => {
    const scrolled = window.pageYOffset;
    peopleImages.forEach((img, index) => {
        const speed = 0.05;
        const yPos = -(scrolled * speed * (index + 1));
        img.style.transform = `translateY(${yPos}px)`;
    });
});

// CTA button click handler
const ctaButtons = document.querySelectorAll('.cta-final-btn, .cta-btn-primary');
ctaButtons.forEach(button => {
    button.addEventListener('click', function() {
        // Add ripple effect
        const ripple = document.createElement('span');
        ripple.style.cssText = `
            position: absolute;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.3);
            transform: scale(0);
            animation: ripple 0.6s linear;
            pointer-events: none;
        `;
        
        this.style.position = 'relative';
        this.style.overflow = 'hidden';
        this.appendChild(ripple);
        
        setTimeout(() => ripple.remove(), 600);
    });
});

// Add ripple animation keyframes dynamically
const style = document.createElement('style');
style.textContent = `
    @keyframes ripple {
        to {
            transform: scale(4);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// Nav link active state on scroll
const sections = document.querySelectorAll('section');
const navLinks = document.querySelectorAll('.nav-link');

window.addEventListener('scroll', () => {
    let current = '';
    
    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;
        if (pageYOffset >= sectionTop - 200) {
            current = section.getAttribute('id');
        }
    });
    
    navLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href').includes(current)) {
            link.classList.add('active');
        }
    });
});

// Lazy loading images
const lazyImages = document.querySelectorAll('img[data-src]');
const imageObserver = new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const img = entry.target;
            img.src = img.dataset.src;
            img.removeAttribute('data-src');
            observer.unobserve(img);
        }
    });
});

lazyImages.forEach(img => imageObserver.observe(img));

// Keyboard navigation support
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        // Close any modals or dropdowns
        console.log('Escape pressed');
    }
});

// Footer links hover effect
const footerLinks = document.querySelectorAll('.footer-column a');
footerLinks.forEach(link => {
    link.addEventListener('mouseenter', function() {
        this.style.paddingLeft = '8px';
        this.style.transition = 'padding-left 0.2s ease';
    });
    
    link.addEventListener('mouseleave', function() {
        this.style.paddingLeft = '0';
    });
});

// Add loading state for page
window.addEventListener('load', () => {
    document.body.classList.add('loaded');
    
    // Fade in hero section
    const hero = document.querySelector('.hero');
    if (hero) {
        hero.style.opacity = '1';
        hero.style.transition = 'opacity 0.5s ease';
    }
});

// Console info for debugging
console.log('Scaler Clone - Interactive script loaded successfully');
console.log('All animations and interactions initialized');