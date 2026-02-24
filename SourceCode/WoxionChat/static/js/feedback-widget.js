/**
 * WoxionChat Feedback Widget
 * Tích hợp feedback system vào bất kỳ trang web nào
 * 
 * Cách sử dụng:
 * 1. Include script này vào trang web
 * 2. Gọi WoxionFeedback.init() để khởi tạo
 * 3. Sử dụng WoxionFeedback.show() để hiển thị popup feedback
 */

class WoxionFeedback {
    constructor() {
        this.apiUrl = '/api/feedback/submit/';
        this.isInitialized = false;
        this.isVisible = false;
        this.currentUser = null;
    }

    /**
     * Khởi tạo feedback widget
     */
    async init(options = {}) {
        if (this.isInitialized) return;

        // Cấu hình mặc định
        this.config = {
            position: 'bottom-right', // bottom-right, bottom-left, top-right, top-left
            theme: 'light', // light, dark
            showButton: true, // Hiển thị nút feedback floating
            buttonText: '📝 Feedback',
            autoShow: false, // Tự động hiện popup khi load trang
            triggerAfter: 30000, // Hiện popup sau 30 giây (nếu autoShow = true)
            ...options
        };

        // Lấy thông tin user hiện tại
        await this.getCurrentUser();

        // Tạo CSS styles
        this.injectStyles();

        // Tạo HTML elements
        this.createElements();

        // Gắn event listeners
        this.attachEventListeners();

        this.isInitialized = true;

        // Auto show nếu được cấu hình
        if (this.config.autoShow) {
            setTimeout(() => this.show(), this.config.triggerAfter);
        }

        console.log('🔗 WoxionFeedback Widget initialized');
    }

    /**
     * Lấy thông tin user hiện tại từ Django
     */
    async getCurrentUser() {
        try {
            const response = await fetch('/api/profile/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                }
            });

            if (response.ok) {
                this.currentUser = await response.json();
                console.log('👤 Current user:', this.currentUser.username);
            } else {
                console.warn('⚠️ User not authenticated - feedback will be anonymous');
                this.currentUser = null;
            }
        } catch (error) {
            console.warn('⚠️ Could not get user info:', error);
            this.currentUser = null;
        }
    }

    /**
     * Thêm CSS styles vào trang
     */
    injectStyles() {
        const css = `
            .woxion-feedback-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                z-index: 10000;
                display: none;
                justify-content: center;
                align-items: center;
            }
            
            .woxion-feedback-popup {
                background: white;
                border-radius: 12px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                width: 90%;
                max-width: 500px;
                max-height: 80vh;
                overflow-y: auto;
                position: relative;
                animation: fadeInUp 0.3s ease;
            }
            
            @keyframes fadeInUp {
                from {
                    opacity: 0;
                    transform: translateY(30px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }
            
            .woxion-feedback-header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                border-radius: 12px 12px 0 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .woxion-feedback-close {
                background: none;
                border: none;
                color: white;
                font-size: 24px;
                cursor: pointer;
                padding: 0;
                width: 30px;
                height: 30px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                transition: background 0.3s ease;
            }
            
            .woxion-feedback-close:hover {
                background: rgba(255, 255, 255, 0.2);
            }
            
            .woxion-feedback-content {
                padding: 20px;
            }
            
            .woxion-feedback-button {
                position: fixed;
                ${this.config.position.includes('bottom') ? 'bottom: 20px;' : 'top: 20px;'}
                ${this.config.position.includes('right') ? 'right: 20px;' : 'left: 20px;'}
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 25px;
                cursor: pointer;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
                z-index: 9999;
                font-weight: bold;
                transition: all 0.3s ease;
                font-size: 14px;
            }
            
            .woxion-feedback-button:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
            }
            
            .woxion-feedback-form {
                display: flex;
                flex-direction: column;
                gap: 15px;
            }
            
            .woxion-feedback-field {
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            
            .woxion-feedback-label {
                font-weight: bold;
                color: #333;
            }
            
            .woxion-feedback-rating {
                display: flex;
                gap: 5px;
                justify-content: center;
            }
            
            .woxion-feedback-star {
                font-size: 24px;
                cursor: pointer;
                color: #ddd;
                transition: color 0.2s ease;
                user-select: none;
            }
            
            .woxion-feedback-star.active,
            .woxion-feedback-star:hover {
                color: #ffc107;
            }
            
            .woxion-feedback-textarea {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
                font-family: inherit;
                font-size: 14px;
                resize: vertical;
                min-height: 80px;
                transition: border-color 0.3s ease;
            }
            
            .woxion-feedback-textarea:focus {
                outline: none;
                border-color: #667eea;
            }
            
            .woxion-feedback-submit {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
                font-size: 16px;
                transition: all 0.3s ease;
            }
            
            .woxion-feedback-submit:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
            }
            
            .woxion-feedback-submit:disabled {
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }
            
            .woxion-feedback-user-info {
                background: #f8f9fa;
                padding: 12px;
                border-radius: 8px;
                margin-bottom: 15px;
                font-size: 14px;
                color: #6c757d;
            }
            
            .woxion-feedback-success {
                text-align: center;
                padding: 40px 20px;
                color: #28a745;
            }
            
            .woxion-feedback-success h3 {
                margin: 0 0 10px 0;
                color: #28a745;
            }
        `;

        const style = document.createElement('style');
        style.textContent = css;
        document.head.appendChild(style);
    }

    /**
     * Tạo các HTML elements
     */
    createElements() {
        // Floating button
        if (this.config.showButton) {
            this.button = document.createElement('button');
            this.button.className = 'woxion-feedback-button';
            this.button.textContent = this.config.buttonText;
            document.body.appendChild(this.button);
        }

        // Overlay và popup
        this.overlay = document.createElement('div');
        this.overlay.className = 'woxion-feedback-overlay';
        
        this.popup = document.createElement('div');
        this.popup.className = 'woxion-feedback-popup';
        
        this.popup.innerHTML = `
            <div class="woxion-feedback-header">
                <h3>📝 Đánh giá Chatbot</h3>
                <button class="woxion-feedback-close">&times;</button>
            </div>
            <div class="woxion-feedback-content">
                <div id="woxion-feedback-form-container">
                    ${this.currentUser ? `
                        <div class="woxion-feedback-user-info">
                            👤 Feedback từ: <strong>${this.currentUser.first_name} ${this.currentUser.last_name}</strong> (${this.currentUser.username})
                        </div>
                    ` : `
                        <div class="woxion-feedback-user-info">
                            ℹ️ Bạn chưa đăng nhập. Feedback sẽ được gửi ẩn danh.
                        </div>
                    `}
                    
                    <form class="woxion-feedback-form" id="woxion-feedback-form">
                        <div class="woxion-feedback-field">
                            <label class="woxion-feedback-label">Bạn hài lòng với chatbot đến mức độ nào?</label>
                            <div class="woxion-feedback-rating" id="overall-rating">
                                <span class="woxion-feedback-star" data-rating="1">★</span>
                                <span class="woxion-feedback-star" data-rating="2">★</span>
                                <span class="woxion-feedback-star" data-rating="3">★</span>
                                <span class="woxion-feedback-star" data-rating="4">★</span>
                                <span class="woxion-feedback-star" data-rating="5">★</span>
                            </div>
                        </div>
                        
                        <div class="woxion-feedback-field">
                            <label class="woxion-feedback-label">Chatbot có hữu ích với bạn không?</label>
                            <div class="woxion-feedback-rating" id="usefulness-rating">
                                <span class="woxion-feedback-star" data-rating="1">★</span>
                                <span class="woxion-feedback-star" data-rating="2">★</span>
                                <span class="woxion-feedback-star" data-rating="3">★</span>
                                <span class="woxion-feedback-star" data-rating="4">★</span>
                                <span class="woxion-feedback-star" data-rating="5">★</span>
                            </div>
                        </div>
                        
                        <div class="woxion-feedback-field">
                            <label class="woxion-feedback-label">Chia sẻ thêm ý kiến của bạn:</label>
                            <textarea 
                                class="woxion-feedback-textarea" 
                                id="feedback-comment"
                                placeholder="Hãy cho chúng tôi biết trải nghiệm của bạn với chatbot..."
                            ></textarea>
                        </div>
                        
                        <button type="submit" class="woxion-feedback-submit">
                            Gửi đánh giá
                        </button>
                    </form>
                </div>
            </div>
        `;
        
        this.overlay.appendChild(this.popup);
        document.body.appendChild(this.overlay);
    }

    /**
     * Gắn event listeners
     */
    attachEventListeners() {
        // Floating button click
        if (this.button) {
            this.button.addEventListener('click', () => this.show());
        }

        // Close button
        const closeBtn = this.popup.querySelector('.woxion-feedback-close');
        closeBtn.addEventListener('click', () => this.hide());

        // Overlay click (close when clicking outside)
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) {
                this.hide();
            }
        });

        // Star ratings
        this.setupStarRatings();

        // Form submit
        const form = this.popup.querySelector('#woxion-feedback-form');
        form.addEventListener('submit', (e) => this.handleSubmit(e));

        // ESC key to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isVisible) {
                this.hide();
            }
        });
    }

    /**
     * Thiết lập star ratings
     */
    setupStarRatings() {
        const ratingContainers = this.popup.querySelectorAll('.woxion-feedback-rating');
        
        ratingContainers.forEach(container => {
            const stars = container.querySelectorAll('.woxion-feedback-star');
            
            stars.forEach(star => {
                star.addEventListener('click', () => {
                    const rating = parseInt(star.dataset.rating);
                    container.dataset.rating = rating;
                    
                    // Update visual state
                    stars.forEach((s, index) => {
                        if (index < rating) {
                            s.classList.add('active');
                        } else {
                            s.classList.remove('active');
                        }
                    });
                });
                
                star.addEventListener('mouseenter', () => {
                    const rating = parseInt(star.dataset.rating);
                    stars.forEach((s, index) => {
                        if (index < rating) {
                            s.style.color = '#ffc107';
                        } else {
                            s.style.color = '#ddd';
                        }
                    });
                });
            });
            
            container.addEventListener('mouseleave', () => {
                const currentRating = parseInt(container.dataset.rating) || 0;
                stars.forEach((s, index) => {
                    if (index < currentRating) {
                        s.style.color = '#ffc107';
                    } else {
                        s.style.color = '#ddd';
                    }
                });
            });
        });
    }

    /**
     * Hiển thị popup feedback
     */
    show() {
        if (!this.isInitialized) {
            console.warn('WoxionFeedback chưa được khởi tạo. Gọi init() trước.');
            return;
        }

        this.overlay.style.display = 'flex';
        this.isVisible = true;
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
    }

    /**
     * Ẩn popup feedback
     */
    hide() {
        this.overlay.style.display = 'none';
        this.isVisible = false;
        document.body.style.overflow = ''; // Restore scrolling
    }

    /**
     * Xử lý submit form
     */
    async handleSubmit(e) {
        e.preventDefault();
        
        const submitBtn = e.target.querySelector('.woxion-feedback-submit');
        const originalText = submitBtn.textContent;
        
        try {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Đang gửi...';
            
            // Collect form data
            const overallRating = parseInt(document.getElementById('overall-rating').dataset.rating) || 0;
            const usefulnessRating = parseInt(document.getElementById('usefulness-rating').dataset.rating) || 0;
            const comment = document.getElementById('feedback-comment').value.trim();
            
            if (overallRating === 0) {
                alert('Vui lòng đánh giá mức độ hài lòng!');
                return;
            }
            
            const feedbackData = {
                user_id: this.currentUser ? this.currentUser.id : `anonymous_${Date.now()}`,
                session_id: `widget_${Date.now()}`,
                answers: {
                    overall_satisfaction: overallRating,
                    problem_solving_usefulness: usefulnessRating,
                    widget_comment: comment,
                    submitted_via: 'widget',
                    page_url: window.location.href,
                    timestamp: new Date().toISOString()
                }
            };
            
            const response = await fetch(this.apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                },
                body: JSON.stringify(feedbackData)
            });
            
            const result = await response.json();
            
            if (response.ok && result.status === 'success') {
                this.showSuccess();
            } else {
                throw new Error(result.message || 'Lỗi không xác định');
            }
            
        } catch (error) {
            console.error('Error submitting feedback:', error);
            alert('Có lỗi xảy ra khi gửi feedback: ' + error.message);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    }

    /**
     * Hiển thị thông báo thành công
     */
    showSuccess() {
        const container = document.getElementById('woxion-feedback-form-container');
        container.innerHTML = `
            <div class="woxion-feedback-success">
                <h3>🎉 Cảm ơn bạn!</h3>
                <p>Đánh giá của bạn đã được gửi thành công.</p>
                <p>Chúng tôi sẽ sử dụng phản hồi này để cải thiện chatbot.</p>
                <button class="woxion-feedback-submit" onclick="WoxionFeedbackWidget.hide()" style="margin-top: 20px;">
                    Đóng
                </button>
            </div>
        `;
    }

    /**
     * Lấy CSRF token
     */
    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || 
               document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || 
               this.getCookie('csrftoken');
    }

    /**
     * Lấy cookie value
     */
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
}

// Tạo instance global
window.WoxionFeedbackWidget = new WoxionFeedback();

// Auto-init khi DOM ready (nếu muốn)
document.addEventListener('DOMContentLoaded', () => {
    if (window.WOXION_FEEDBACK_AUTO_INIT !== false) {
        window.WoxionFeedbackWidget.init();
    }
}); 