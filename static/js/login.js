  // Theme Toggle
        const themeToggle = document.getElementById('themeToggle');
        const htmlElement = document.documentElement;

        // Check saved theme
        const savedTheme = localStorage.getItem('theme') || 'light';
        htmlElement.setAttribute('data-theme', savedTheme);

        themeToggle.addEventListener('click', () => {
            const currentTheme = htmlElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            htmlElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        });

        // Login Logic
        const emailSection = document.getElementById('emailSection');
        const otpSection = document.getElementById('otpSection');
        const emailInput = document.getElementById('email');
        const otpInput = document.getElementById('otp');
        const sendOtpBtn = document.getElementById('sendOtpBtn');
        const verifyOtpBtn = document.getElementById('verifyOtpBtn');
        const resendBtn = document.getElementById('resendBtn');
        const changeEmailBtn = document.getElementById('changeEmailBtn');
        const alertBox = document.getElementById('alertBox');

        let currentEmail = '';

        function showAlert(message, type) {
            alertBox.textContent = message;
            alertBox.className = `alert alert-${type}`;
            alertBox.style.display = 'block';
            setTimeout(() => {
                alertBox.style.display = 'none';
            }, 5000);
        }

        async function sendOtp() {
            const email = emailInput.value.trim();
            if (!email || !email.includes('@')) {
                showAlert('Please enter a valid email address', 'error');
                return;
            }

            sendOtpBtn.disabled = true;
            sendOtpBtn.innerHTML = 'Sending...';

            try {
                const response = await fetch('/send-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                const data = await response.json();

                if (data.success) {
                    currentEmail = email;
                    emailSection.style.display = 'none';
                    otpSection.classList.add('active');
                    showAlert('OTP sent successfully!', 'success');
                    otpInput.focus();
                } else {
                    showAlert(data.message || 'Failed to send OTP', 'error');
                }
            } catch (error) {
                showAlert('An error occurred. Please try again.', 'error');
            } finally {
                sendOtpBtn.disabled = false;
                sendOtpBtn.innerHTML = `Send OTP <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" width="20"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>`;
            }
        }

        async function verifyOtp() {
            const otp = otpInput.value.trim();
            if (otp.length < 4) {
                showAlert('Please enter a valid OTP', 'error');
                return;
            }

            verifyOtpBtn.disabled = true;
            verifyOtpBtn.innerHTML = 'Verifying...';

            try {
                const response = await fetch('/verify-otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: currentEmail, otp })
                });
                const data = await response.json();

                if (data.success) {
                    showAlert('Login successful! Redirecting...', 'success');
                    setTimeout(() => {
                        window.location.href = '/tool'; // Redirect to main tool page
                    }, 1000);
                } else {
                    showAlert(data.message || 'Invalid OTP', 'error');
                    verifyOtpBtn.disabled = false;
                    verifyOtpBtn.innerHTML = `Verify & Login <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" width="20"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
                }
            } catch (error) {
                showAlert('An error occurred. Please try again.', 'error');
                verifyOtpBtn.disabled = false;
                verifyOtpBtn.innerHTML = `Verify & Login <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" width="20"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
            }
        }

        sendOtpBtn.addEventListener('click', sendOtp);

        verifyOtpBtn.addEventListener('click', verifyOtp);

        resendBtn.addEventListener('click', sendOtp);

        changeEmailBtn.addEventListener('click', () => {
            otpSection.classList.remove('active');
            emailSection.style.display = 'block';
            emailInput.focus();
        });

        // Enter key support
        emailInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendOtp();
        });
        otpInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') verifyOtp();
        });