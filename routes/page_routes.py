from flask import Blueprint, render_template, session, Response, request
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
    for mode in [1, 2, 3, 4, 5, 6]:
        trial_info_all_modes[mode] = check_trial_available(email, mode)
    
    return render_template('index.html', trial_info=trial_info_all_modes)

@page_bp.route('/mode/<int:mode_num>')
@login_required
def mode_page(mode_num):
    if mode_num not in [1, 2, 3, 4, 5, 6]:
        return "Invalid mode", 404
    
    # Get trial information
    email = session['user_email']
    trial_info = check_trial_available(email, mode_num)
    
    return render_template(f'mode{mode_num}.html', mode=mode_num, trial_info=trial_info)

@page_bp.route("/health")
def health():
    return "ok", 200


@page_bp.route('/sitemap.xml')
def sitemap():
    """Generate XML sitemap for search engines"""
    base_url = "https://shabdsetu.in"
    
    pages = [
        {'url': '/',              'priority': '1.0', 'changefreq': 'weekly'},
        {'url': '/features',      'priority': '0.9', 'changefreq': 'monthly'},
        {'url': '/pricing',       'priority': '0.8', 'changefreq': 'monthly'},
        {'url': '/contactus',     'priority': '0.6', 'changefreq': 'monthly'},
        {'url': '/tool',       'priority': '0.6', 'changefreq': 'monthly'},
        {'url': '/terms&amp;conditions', 'priority': '0.3', 'changefreq': 'yearly'},
    ]
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for page in pages:
        xml += f'  <url>\n'
        xml += f'    <loc>{base_url}{page["url"]}</loc>\n'
        xml += f'    <changefreq>{page["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{page["priority"]}</priority>\n'
        xml += f'  </url>\n'
    
    xml += '</urlset>'
    
    return Response(xml, mimetype='application/xml')

@page_bp.route('/robots.txt')
def robots():
    """Serve robots.txt for search engine crawlers"""
    content = """User-agent: *
Allow: /
Allow: /features
Allow: /pricing
Allow: /contactus
Disallow: /tool
Disallow: /login
Disallow: /send-otp
Disallow: /verify-otp
Disallow: /process
Disallow: /progress/
Disallow: /download/
Disallow: /mode/

Sitemap: {base_url}/sitemap.xml
""".format(base_url=request.url_root.rstrip('/'))
    
    return Response(content, mimetype='text/plain')
