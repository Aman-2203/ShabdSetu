// Index Page JavaScript
let selectedMode = null;
let uploadedFile = null;
let jobId = null;
let currentAcceptTypes = '.pdf,.docx';
let currentTrialInfo = null;

// Trial info passed from backend - this will be set from the HTML
let trialInfoAllModes = {};

// Initialize trial info from HTML data attribute
function initTrialInfo() {
    const trialInfoElement = document.getElementById('trial-info-data');
    if (trialInfoElement && trialInfoElement.dataset.trialInfo) {
        try {
            trialInfoAllModes = JSON.parse(trialInfoElement.dataset.trialInfo);
        } catch (e) {
            console.error('Error parsing trial info:', e);
            trialInfoAllModes = {};
        }
    }
}

// Trial status management
function updateTrialStatus(trialInfo) {
    if (!trialInfo) return;

    currentTrialInfo = trialInfo;
    const banner = document.getElementById('trialStatusBanner');
    const value = document.getElementById('trialStatusValue');
    const fill = document.getElementById('trialProgressFill');
    const info = document.getElementById('trialStatusInfo');

    // Update values
    value.textContent = `${trialInfo.pages_used} / ${trialInfo.limit} pages used`;
    const percentage = (trialInfo.pages_remaining / trialInfo.limit) * 100;
    fill.style.width = percentage + '%';

    // Update banner state
    banner.classList.remove('warning', 'exhausted');
    banner.classList.add('active');

    if (trialInfo.pages_remaining <= 0) {
        banner.classList.add('exhausted');
        info.textContent = '⚠️ Trial exhausted for this tool. Please upgrade to continue.';
    } else if (trialInfo.pages_remaining <= 1) {
        banner.classList.add('warning');
        info.textContent = `⚠️ Only ${trialInfo.pages_remaining.toFixed(1)} page(s) remaining!`;
    } else {
        info.textContent = `${trialInfo.pages_remaining.toFixed(1)} page(s) remaining for this tool.`;
    }
}

// Error Modal functions
function showErrorModal(errorData) {
    const modal = document.getElementById('errorModal');
    const message = document.getElementById('errorModalMessage');
    const details = document.getElementById('errorModalDetails');

    message.textContent = errorData.message || 'An error occurred.';

    // Show details if available
    if (errorData.pages_used !== undefined) {
        let detailsHTML = '';
        detailsHTML += `<div class="error-modal-detail-item">
    <span class="error-modal-detail-label">Trial Used:</span>
    <span class="error-modal-detail-value">${errorData.pages_used} / ${errorData.limit} pages</span>
</div>`;

        detailsHTML += `<div class="error-modal-detail-item">
    <span class="error-modal-detail-label">Remaining:</span>
    <span class="error-modal-detail-value">${errorData.pages_remaining.toFixed(2)} pages</span>
</div>`;

        if (errorData.document_pages) {
            detailsHTML += `<div class="error-modal-detail-item">
        <span class="error-modal-detail-label">Your Document:</span>
        <span class="error-modal-detail-value">${errorData.document_pages} pages (PDF)</span>
    </div>`;
        }

        if (errorData.document_chars) {
            detailsHTML += `<div class="error-modal-detail-item">
        <span class="error-modal-detail-label">Your Document:</span>
        <span class="error-modal-detail-value">${errorData.document_chars.toLocaleString()} characters</span>
    </div>`;
            detailsHTML += `<div class="error-modal-detail-item">
        <span class="error-modal-detail-label">Equivalent Pages:</span>
        <span class="error-modal-detail-value">≈${errorData.page_usage.toFixed(2)} pages</span>
    </div>`;
        }

        details.innerHTML = detailsHTML;
        details.style.display = 'block';
    } else {
        details.style.display = 'none';
    }

    modal.classList.add('active');
}

function hideErrorModal() {
    document.getElementById('errorModal').classList.remove('active');
}

// Payment Modal functions
let currentPaymentData = null;

function showPaymentModal(data) {
    const modal = document.getElementById('paymentModal');
    const details = document.getElementById('paymentDetails');
    currentPaymentData = data;

    let html = '';
    html += `<div class="error-modal-detail-item">
        <span class="error-modal-detail-label">Billable Pages:</span>
        <span class="error-modal-detail-value">${data.billable_pages} pages</span>
    </div>`;

    if (data.word_count) {
        html += `<div class="error-modal-detail-item">
            <span class="error-modal-detail-label">Word Count:</span>
            <span class="error-modal-detail-value">${data.word_count.toLocaleString()} words</span>
        </div>`;
    }

    html += `<div class="error-modal-detail-item">
        <span class="error-modal-detail-label">Rate:</span>
        <span class="error-modal-detail-value">₹${(data.estimated_cost / data.billable_pages).toFixed(2)} / page</span>
    </div>`;

    html += `<div class="error-modal-detail-item" style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border);">
        <span class="error-modal-detail-label" style="font-size: 1.1rem; font-weight: 600;">Total Cost:</span>
        <span class="error-modal-detail-value" style="font-size: 1.25rem; color: var(--accent-green);">₹${data.estimated_cost.toFixed(2)}</span>
    </div>`;

    details.innerHTML = html;
    modal.classList.add('active');
}

function hidePaymentModal() {
    document.getElementById('paymentModal').classList.remove('active');
    currentPaymentData = null;
}

// File handling functions
async function handleFileSelect(file) {
    const fileExt = '.' + file.name.split('.').pop().toLowerCase();
    if (!currentAcceptTypes.includes(fileExt)) {
        alert(`Invalid file type. Please upload ${currentAcceptTypes === '.pdf' ? 'PDF files only' : 'PDF or DOCX files'}.`);
        return;
    }

    if (file.size > 50 * 1024 * 1024) {
        alert('File size exceeds 50MB limit.');
        return;
    }

    uploadedFile = file;

    const fileUpload = document.getElementById('fileUpload');
    const filePreview = document.getElementById('filePreview');
    const processBtn = document.getElementById('processBtn');
    const fileName = document.getElementById('fileName');

    fileUpload.classList.add('has-file');
    filePreview.classList.add('active');
    processBtn.disabled = false;

    fileName.textContent = file.name;
    document.getElementById('fileFormat').textContent = file.name.split('.').pop().toUpperCase();
    document.getElementById('fileSize').textContent = formatFileSize(file.size);

    if (file.type === 'application/pdf') {
        await generatePDFThumbnail(file);

        try {
            const arrayBuffer = await file.arrayBuffer();
            const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
            const pageCount = pdf.numPages;
            document.getElementById('filePages').textContent = `${pageCount} page${pageCount !== 1 ? 's' : ''}`;
            document.getElementById('filePagesItem').style.display = 'flex';
        } catch (error) {
            console.error('Error getting page count:', error);
            document.getElementById('filePagesItem').style.display = 'none';
        }
    } else {
        document.getElementById('fileThumbnail').innerHTML = `
    <div class="file-thumbnail-icon">
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
    </div>
`;
        document.getElementById('filePagesItem').style.display = 'none';
    }
}

async function generatePDFThumbnail(file) {
    try {
        const arrayBuffer = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        const page = await pdf.getPage(1);

        const scale = 0.5;
        const viewport = page.getViewport({ scale });

        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        await page.render({
            canvasContext: context,
            viewport: viewport
        }).promise;

        const imgData = canvas.toDataURL();
        document.getElementById('fileThumbnail').innerHTML = `<img src="${imgData}" alt="PDF Preview">`;
    } catch (error) {
        console.error('Error generating thumbnail:', error);
    }
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function removeFile() {
    uploadedFile = null;
    const fileInput = document.getElementById('fileInput');
    const fileUpload = document.getElementById('fileUpload');
    const filePreview = document.getElementById('filePreview');
    const processBtn = document.getElementById('processBtn');
    const fileName = document.getElementById('fileName');

    fileInput.value = '';
    fileUpload.classList.remove('has-file');
    filePreview.classList.remove('active');
    processBtn.disabled = true;
    fileName.textContent = '';
}

// Progress and processing functions
function pollProgress(pollJobId) {
    const interval = setInterval(async () => {
        try {
            const response = await fetch(`/progress/${pollJobId}`);
            const data = await response.json();

            const progressFill = document.getElementById('progressFill');
            progressFill.style.width = data.percentage + '%';

            if (data.percentage === 100) {
                progressFill.classList.add('success');
            }

            document.getElementById('progressText').textContent = `${data.status} ${data.percentage}%`;

            if (data.percentage === 100 && data.output_file) {
                clearInterval(interval);
                showSuccess(data.output_file);
            }

            if (data.error) {
                clearInterval(interval);
                alert('Processing failed: ' + data.status);
                resetProgress();
            }
        } catch (error) {
            clearInterval(interval);
            alert('Error checking progress: ' + error.message);
            resetProgress();
        }
    }, 1000);
}

function showSuccess(outputFile) {
    document.getElementById('successMessage').classList.add('active');
    document.getElementById('downloadBtn').onclick = () => {
        window.location.href = `/download/${outputFile}`;
    };
}

function resetForm() {
    removeFile();
    selectedMode = null;
    jobId = null;
    document.getElementById('processingPanel').classList.remove('active');
    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('active'));
    resetProgress();
}

function resetProgress() {
    const processBtn = document.getElementById('processBtn');
    document.getElementById('progressContainer').classList.remove('active');
    document.getElementById('successMessage').classList.remove('active');
    const progressFill = document.getElementById('progressFill');
    progressFill.style.width = '0%';
    progressFill.classList.remove('success');
    document.getElementById('progressText').textContent = 'Initializing... 0%';
    processBtn.disabled = uploadedFile ? false : true;
}

// Payment processing
async function handlePayment(userEmail) {
    if (!currentPaymentData) return;

    const btn = document.getElementById('payNowBtn');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = 'Creating Order...';

    try {
        // 1. Create Razorpay Order
        const orderResponse = await fetch('/create-payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mode: selectedMode,
                pages: currentPaymentData.billable_pages
            })
        });

        const orderData = await orderResponse.json();

        if (!orderData.success) {
            throw new Error(orderData.error || 'Failed to create order');
        }

        btn.innerHTML = 'Opening Payment Gateway...';

        // 2. Open Razorpay Checkout
        const options = {
            key: orderData.key_id,
            amount: orderData.amount_paise,
            currency: orderData.currency,
            name: 'ShabdSetu',
            description: `Process ${orderData.pages} pages - Mode ${selectedMode}`,
            order_id: orderData.order_id,
            handler: async function (response) {
                // Payment successful - verify on backend
                try {
                    btn.innerHTML = 'Verifying Payment...';

                    // Save billable_pages before hiding modal (which sets currentPaymentData to null)
                    const billablePages = currentPaymentData.billable_pages;
                    hidePaymentModal();

                    const verifyResponse = await fetch('/verify-payment', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            razorpay_order_id: response.razorpay_order_id,
                            razorpay_payment_id: response.razorpay_payment_id,
                            razorpay_signature: response.razorpay_signature,
                            mode: selectedMode,
                            pages: billablePages,
                            amount: orderData.amount
                        })
                    });

                    const verifyData = await verifyResponse.json();

                    if (!verifyData.success) {
                        throw new Error(verifyData.error || 'Payment verification failed');
                    }

                    // 3. Process File with Payment ID
                    const formData = new FormData();
                    formData.append('file', uploadedFile);
                    formData.append('mode', selectedMode);
                    formData.append('language', document.getElementById('language').value);
                    formData.append('source_lang', document.getElementById('sourceLang').value);
                    formData.append('target_lang', document.getElementById('targetLang').value);
                    formData.append('payment_id', response.razorpay_payment_id);

                    document.getElementById('progressContainer').classList.add('active');
                    document.getElementById('processBtn').disabled = true;

                    const processResponse = await fetch('/process', {
                        method: 'POST',
                        body: formData
                    });

                    const processData = await processResponse.json();

                    if (processResponse.ok && processData.job_id) {
                        jobId = processData.job_id;
                        pollProgress(jobId);
                    } else {
                        alert('Error processing after payment: ' + (processData.error || 'Unknown error'));
                        resetProgress();
                    }

                } catch (error) {
                    alert('Error after payment: ' + error.message);
                    resetProgress();
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }
            },
            prefill: {
                email: userEmail || ''
            },
            theme: {
                color: '#3b82f6'
            },
            modal: {
                ondismiss: function () {
                    // User closed the payment modal
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                    alert('Payment cancelled. Please try again.');
                }
            }
        };

        const razorpay = new Razorpay(options);

        razorpay.on('payment.failed', function (response) {
            // Payment failed
            btn.disabled = false;
            btn.innerHTML = originalText;
            alert('Payment failed: ' + response.error.description);
        });

        razorpay.open();

    } catch (error) {
        alert('Payment initialization failed: ' + error.message);
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// Process document
async function processDocument() {
    const processBtn = document.getElementById('processBtn');
    if (!uploadedFile || !selectedMode) return;

    const formData = new FormData();
    formData.append('file', uploadedFile);
    formData.append('mode', selectedMode);
    formData.append('language', document.getElementById('language').value);
    formData.append('source_lang', document.getElementById('sourceLang').value);
    formData.append('target_lang', document.getElementById('targetLang').value);

    document.getElementById('progressContainer').classList.add('active');
    processBtn.disabled = true;

    try {
        const response = await fetch('/process', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok && data.job_id) {
            jobId = data.job_id;
            // Update trial info if provided
            if (data.trial_info) {
                updateTrialStatus(data.trial_info);
            }
            pollProgress(jobId);
        } else if (data.error === 'Trial limit exceeded') {
            // Check if we can offer payment
            if (data.estimated_cost && data.estimated_cost > 0) {
                showPaymentModal(data);
            } else {
                // Show standard error modal
                showErrorModal(data);
            }
            resetProgress();
        } else {
            alert('Error: ' + (data.error || data.message || 'Unknown error'));
            resetProgress();
        }
    } catch (error) {
        alert('Error: ' + error.message);
        resetProgress();
    }
}

// Initialize event listeners
function initEventListeners(userEmail) {
    const fileUpload = document.getElementById('fileUpload');
    const fileInput = document.getElementById('fileInput');

    // Error modal close
    document.getElementById('errorModalClose').addEventListener('click', hideErrorModal);
    document.getElementById('errorModal').addEventListener('click', function (e) {
        if (e.target === this) {
            hideErrorModal();
        }
    });

    // Payment modal
    document.getElementById('paymentModalClose').addEventListener('click', hidePaymentModal);
    document.getElementById('payNowBtn').addEventListener('click', () => handlePayment(userEmail));
    document.getElementById('paymentModal').addEventListener('click', function (e) {
        if (e.target === this) {
            hidePaymentModal();
        }
    });

    // Mode selection
    document.querySelectorAll('.mode-card').forEach(card => {
        card.addEventListener('click', function () {
            document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('active'));
            this.classList.add('active');
            selectedMode = this.dataset.mode;

            // Update trial status for selected mode
            if (trialInfoAllModes[selectedMode]) {
                updateTrialStatus(trialInfoAllModes[selectedMode]);
            }

            currentAcceptTypes = this.dataset.accept;
            document.getElementById('fileInput').accept = currentAcceptTypes;

            const fileTypeText = document.getElementById('fileTypeText');
            if (currentAcceptTypes === '.pdf') {
                fileTypeText.textContent = 'PDF files only (Max 50MB)';
            } else {
                fileTypeText.textContent = 'DOCX files (Max 50MB)';
            }

            document.getElementById('processingPanel').classList.add('active');

            const needsLang = this.dataset.needsLang === 'true';
            const needsTranslate = this.dataset.needsTranslate === 'true';

            document.getElementById('languageGroup').style.display = needsLang ? 'block' : 'none';
            document.getElementById('translationGroup').style.display = needsTranslate ? 'block' : 'none';

            setTimeout(() => {
                document.getElementById('processingPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 100);
        });
    });

    // File upload
    fileUpload.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', function (e) {
        if (this.files.length > 0) {
            handleFileSelect(this.files[0]);
        }
    });

    document.getElementById('fileRemove').addEventListener('click', (e) => {
        e.stopPropagation();
        removeFile();
    });

    // Drag and drop
    fileUpload.addEventListener('dragover', (e) => {
        e.preventDefault();
        fileUpload.style.borderColor = 'var(--accent-blue)';
    });

    fileUpload.addEventListener('dragleave', () => {
        fileUpload.style.borderColor = 'var(--border)';
    });

    fileUpload.addEventListener('drop', (e) => {
        e.preventDefault();
        fileUpload.style.borderColor = 'var(--border)';

        if (e.dataTransfer.files.length > 0) {
            const file = e.dataTransfer.files[0];
            fileInput.files = e.dataTransfer.files;
            handleFileSelect(file);
        }
    });

    // Navigation buttons
    document.getElementById('backBtn').addEventListener('click', () => {
        document.getElementById('processingPanel').classList.remove('active');
        document.getElementById('trialStatusBanner').classList.remove('active');
        document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('active'));
        resetForm();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    document.getElementById('newDocBtn').addEventListener('click', () => {
        resetForm();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Process button
    document.getElementById('processBtn').addEventListener('click', processDocument);
}

// Main initialization function - call this from the HTML
function initIndexPage(userEmail) {
    initTrialInfo();
    initEventListeners(userEmail);
}
