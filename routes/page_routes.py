from flask import Blueprint, render_template, session, Response, request, abort
import logging

from auth import check_trial_available, login_required

logger = logging.getLogger(__name__)

# Create blueprint
page_bp = Blueprint('pages', __name__)

# ==================== BLOG DATA ====================
BLOG_POSTS = [
    {
        "slug": "digitize-old-hindi-gujarati-books",
        "title": "How to Digitize Old Hindi/Gujarati Books Without Retyping a Single Word",
        "category": "Document Digitization",
        "read_time": "5 min read",
        "excerpt": "You have a shelf full of old Hindi or Gujarati books — yellowing, fragile, and existing nowhere digitally. Typing them out manually takes weeks. There's a smarter way that doesn't involve typing a single word.",
        "tags": ["Hindi OCR", "Gujarati digitization", "document digitization", "Hindi book scanning", "regional language OCR", "Hindi to Word conversion", "Gujarati text extraction"],
        "featured": True,
        "img_class": "",
        "cat_class": "",
        "article_cat_class": "blog-article-category--blue",
    },
    {
        "slug": "hindi-gujarati-audio-transcription",
        "title": "From Recording to Ready: How to Turn Hindi & Gujarati Audio Into Publish-Ready Documents",
        "category": "Audio Transcription",
        "read_time": "5 min read",
        "excerpt": "The recording went well. But converting spoken Hindi or Gujarati into a clean, usable document is where hours disappear. Manual transcription of one hour of audio takes four to six hours — there's a better way.",
        "tags": ["Hindi audio transcription", "Gujarati speech to text", "Hindi interview transcription", "audio to Word document", "regional language transcription", "Gujarati audio to text", "Hindi recording to document"],
        "featured": False,
        "img_class": "blog-card-img--amber",
        "cat_class": "blog-card-category--amber",
        "article_cat_class": "blog-article-category--amber",
    },
    {
        "slug": "faithful-hindi-gujarati-translation",
        "title": "The Translator Gave You a Document Back. But Is It Still Your Author's Voice?",
        "category": "Translation",
        "read_time": "5 min read",
        "excerpt": "The translation reads smoothly in English. But a paragraph that took the author twelve lines has been condensed into four. A Sanskrit term carrying centuries of meaning has been replaced with a generic word. The translation is technically correct — but it isn't the author's document anymore.",
        "tags": ["Hindi document translation", "Gujarati translation", "religious text translation", "Hindi to English translation", "author voice translation", "Gujarati to English", "faithful translation", "cultural translation"],
        "featured": False,
        "img_class": "blog-card-img--purple",
        "cat_class": "blog-card-category--purple",
        "article_cat_class": "blog-article-category--purple",
    },
]


@page_bp.route("/")
def homepage():
    return render_template('homepage.html')


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

# ==================== BLOG ROUTES ====================
@page_bp.route('/blog')
def blog_listing():
    """Blog listing page with all posts"""
    return render_template('blog.html', posts=BLOG_POSTS)


@page_bp.route('/blog/<slug>')
def blog_post(slug):
    """Individual blog article page"""
    post = next((p for p in BLOG_POSTS if p['slug'] == slug), None)
    if not post:
        abort(404)
    # Get related posts (all posts except the current one)
    related = [p for p in BLOG_POSTS if p['slug'] != slug]
    return render_template('blog_post.html', post=post, related_posts=related)


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
        {'url': '/blog',          'priority': '0.8', 'changefreq': 'weekly'},
        {'url': '/contactus',     'priority': '0.6', 'changefreq': 'monthly'},
        {'url': '/tool',          'priority': '0.6', 'changefreq': 'monthly'},
        {'url': '/terms&amp;conditions', 'priority': '0.3', 'changefreq': 'yearly'},
    ]
    
    # Add individual blog post URLs
    for post in BLOG_POSTS:
        pages.append({'url': f'/blog/{post["slug"]}', 'priority': '0.7', 'changefreq': 'monthly'})
    
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
Allow: /blog
Disallow: /tool
Disallow: /login

Sitemap: {base_url}/sitemap.xml
""".format(base_url=request.url_root.rstrip('/'))
    
    return Response(content, mimetype='text/plain')
