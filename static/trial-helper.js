async function checkTrialStatus(mode) {
    try {
        const response = await fetch('/check-trial', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ mode: mode })
        });

        const trialInfo = await response.json();

        // Display trial information
        displayTrialInfo(trialInfo);

        return trialInfo;
    } catch (error) {
        console.error('Error checking trial status:', error);
        return null;
    }
}

// Display trial information on the page
function displayTrialInfo(trialInfo) {
    // Create or update trial status element
    let trialStatusDiv = document.getElementById('trial-status');

    if (!trialStatusDiv) {
        trialStatusDiv = document.createElement('div');
        trialStatusDiv.id = 'trial-status';
        trialStatusDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            border-radius: 10px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            z-index: 1000;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        `;
        document.body.appendChild(trialStatusDiv);
    }

    if (trialInfo.available) {
        trialStatusDiv.innerHTML = `
            <div style="font-size: 14px; font-weight: 600;">Free Trial</div>
            <div style="font-size: 12px; margin-top: 5px;">
                ${trialInfo.pages_remaining} of ${trialInfo.limit} pages remaining
            </div>
            <div style="background: rgba(255,255,255,0.3); height: 4px; border-radius: 2px; margin-top: 8px; overflow: hidden;">
                <div style="background: white; height: 100%; width: ${(trialInfo.pages_remaining / trialInfo.limit) * 100}%; transition: width 0.3s;"></div>
            </div>
        `;
    } else {
        trialStatusDiv.innerHTML = `
            <div style="font-size: 14px; font-weight: 600;">⚠️ Trial Expired</div>
            <div style="font-size: 12px; margin-top: 5px;">
                You've used all ${trialInfo.limit} free pages for this tool
            </div>
        `;
        trialStatusDiv.style.background = 'linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%)';
    }
}

// Handle form submission with trial check
async function handleProcessWithTrial(formData, mode) {
    try {
        // Check trial before processing
        const trialInfo = await checkTrialStatus(mode);

        if (!trialInfo || !trialInfo.available) {
            alert(`Trial limit exceeded! You have used all ${trialInfo ? trialInfo.limit : 3} free pages for this tool.`);
            return null;
        }

        // Proceed with processing
        const response = await fetch('/process', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        // Update trial info if included in response
        if (result.trial_info) {
            displayTrialInfo(result.trial_info);
        }

        return result;

    } catch (error) {
        console.error('Error processing file:', error);

        // Check if it's a trial limit error
        if (error.message && error.message.includes('Trial limit exceeded')) {
            alert('You have exhausted your free trial for this tool. Please upgrade to continue.');
        }

        throw error;
    }
}

// Add logout button
function addLogoutButton() {
    const logoutBtn = document.createElement('a');
    logoutBtn.href = '/logout';
    logoutBtn.innerHTML = '🚪 Logout';
    logoutBtn.style.cssText = `
        position: fixed;
        margin-top:45px;
        top: 20px;
        left: 20px;
        background: rgba(255, 255, 255, 0.9);
        color: #333;
        padding: 10px 20px;
        border-radius: 10px;
        text-decoration: none;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        font-size: 14px;
        font-weight: 600;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        z-index: 1000;
        transition: all 0.3s ease;
    `;

    logoutBtn.onmouseover = function () {
        this.style.background = 'white';
        this.style.boxShadow = '0 6px 20px rgba(0, 0, 0, 0.15)';
    };

    logoutBtn.onmouseout = function () {
        this.style.background = 'rgba(255, 255, 255, 0.9)';
        this.style.boxShadow = '0 4px 15px rgba(0, 0, 0, 0.1)';
    };

    document.body.appendChild(logoutBtn);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function () {
    // Get mode from page (you may need to adjust this based on your template)
    const modeMatch = window.location.pathname.match(/\/mode\/(\d+)/);
    if (modeMatch) {
        const mode = parseInt(modeMatch[1]);
        checkTrialStatus(mode);
    }

    // Add logout button
    addLogoutButton();
});

