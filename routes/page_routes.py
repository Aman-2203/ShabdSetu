from flask import Blueprint, render_template, session
import logging

from auth import check_trial_available, login_required

logger = logging.getLogger(__name__)

# Create blueprint
page_bp = Blueprint('pages', __name__)


@page_bp.route("/")
def initialize():
    return render_template('feature.html')


@page_bp.route("/terms&conditions")
def tc():
    return render_template("tc.html")


@page_bp.route('/features')
def feature():
    return render_template('feature.html')


@page_bp.route('/pricing')
def pricing():
    return render_template('pricing.html')


@page_bp.route('/contactus')
def contactus():
    return render_template('contactus.html')


@page_bp.route('/tool')
@login_required
def index_redirect():
    # Get trial info for all modes to display on the page
    email = session['user_email']
    trial_info_all_modes = {}
    for mode in range(1, 6):
        trial_info_all_modes[mode] = check_trial_available(email, mode)
    
    return render_template('index.html', trial_info=trial_info_all_modes)


@page_bp.route('/mode/<int:mode_num>')
@login_required
def mode_page(mode_num):
    if mode_num not in range(1, 6):
        return "Invalid mode", 404
    
    # Get trial information
    email = session['user_email']
    trial_info = check_trial_available(email, mode_num)
    
    return render_template(f'mode{mode_num}.html', mode=mode_num, trial_info=trial_info)

@page_bp.route("/health")
def health():
    return "ok", 200
