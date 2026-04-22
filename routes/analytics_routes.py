import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for
import logging
from dotenv import load_dotenv

from db_config import get_database, get_jobs_collection

load_dotenv()

logger = logging.getLogger(__name__)

# Create blueprint
analytics_bp = Blueprint('analytics', __name__)

# Analytics credentials from environment
ANALYTICS_USERNAME = os.getenv('ANALYTICS_USERNAME', 'admin')
ANALYTICS_PASSWORD = os.getenv('ANALYTICS_PASSWORD', '')

# Mode name mapping
MODE_NAMES = {
    1: 'OCR Only', 2: 'OCR + Proofread', 3: 'Proofread',
    4: 'OCR + Translation', 5: 'Translation', 6: 'Audio Transcription'
}

# Modes grouped into processing categories
MODE_CATEGORIES = {
    1: 'OCR', 2: 'OCR', 3: 'Proofread', 
    4: 'Translation', 5: 'Translation', 6: 'Transcription'
}


def analytics_login_required(f):
    """Decorator to check analytics authentication via session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('analytics_authenticated'):
            return redirect(url_for('analytics.analytics_login'))
        return f(*args, **kwargs)
    return decorated_function


@analytics_bp.route('/gurudev/login', methods=['GET', 'POST'])
def analytics_login():
    """Simple login page for analytics dashboard."""
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
        if username == ANALYTICS_USERNAME and password == ANALYTICS_PASSWORD:
            session['analytics_authenticated'] = True
            return redirect(url_for('analytics.analytics_dashboard'))
        else:
            return render_template('analytics.html', 
                                   login_mode=True, 
                                   error='Invalid credentials')
    
    # If already authenticated, redirect to dashboard
    if session.get('analytics_authenticated'):
        return redirect(url_for('analytics.analytics_dashboard'))
    
    return render_template('analytics.html', login_mode=True)


@analytics_bp.route('/gurudev/logout')
def analytics_logout():
    """Logout from analytics dashboard."""
    session.pop('analytics_authenticated', None)
    return redirect(url_for('analytics.analytics_login'))


@analytics_bp.route('/gurudev')
@analytics_login_required
def analytics_dashboard():
    """Serve the analytics dashboard page."""
    return render_template('analytics.html', login_mode=False)


@analytics_bp.route('/api/gurudev')
@analytics_login_required
def analytics_api():
    """
    Return all analytics data as JSON.
    
    Pulls from ALL existing MongoDB collections:
      - users         → user count, registration timeline
      - trial_usage   → mode breakdown, language inference, usage stats
      - payments      → paid jobs, revenue, top paying users
      - jobs          → detailed job tracking (new, populates going forward)
    """
    try:
        db = get_database()
        users_col = db.users
        trial_col = db.trial_usage
        payments_col = db.payments
        jobs_col = db.jobs
        
        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)
        
        # ============================================================
        # 1. TOTAL DOCUMENTS PROCESSED
        #    - Count from trial_usage (each record with pages_used > 0 = used that mode)
        #    - Plus count from payments (each payment = one job)
        #    - Plus count from jobs collection (new tracking)
        # ============================================================
        
        # trial_usage records with actual usage
        trial_active_count = trial_col.count_documents({'pages_used': {'$gt': 0}})
        
        # payments count  
        payments_count = payments_col.count_documents({})
        
        # jobs collection count (new tracking going forward)
        jobs_count = jobs_col.count_documents({})
        
        # Total = trial usages + paid jobs + tracked jobs (deduplicated estimate)
        # trial_usage tracks free usage, payments tracks paid, jobs tracks all new ones
        total_processed = trial_active_count + payments_count + jobs_count
        
        # ============================================================
        # 2. BREAKDOWN BY PROCESSING MODE
        #    Source: trial_usage (mode field) + payments (mode field)
        # ============================================================
        
        # From trial_usage — group by mode, sum pages_used as proxy for activity
        trial_mode_pipeline = [
            {'$match': {'pages_used': {'$gt': 0}}},
            {'$group': {'_id': '$mode', 'count': {'$sum': 1}, 'total_pages': {'$sum': '$pages_used'}}}
        ]
        trial_mode_data = {r['_id']: r for r in trial_col.aggregate(trial_mode_pipeline)}
        
        # From payments — group by mode
        payment_mode_pipeline = [
            {'$group': {'_id': '$mode', 'count': {'$sum': 1}, 'total_pages': {'$sum': '$pages'}}}
        ]
        payment_mode_data = {r['_id']: r for r in payments_col.aggregate(payment_mode_pipeline)}
        
        # From jobs collection
        jobs_mode_pipeline = [
            {'$group': {'_id': '$mode', 'count': {'$sum': 1}}}
        ]
        jobs_mode_data = {r['_id']: r for r in jobs_col.aggregate(jobs_mode_pipeline)}
        
        # Merge all mode data
        all_modes = set(list(trial_mode_data.keys()) + list(payment_mode_data.keys()) + list(jobs_mode_data.keys()))
        mode_breakdown = []
        for mode in sorted(all_modes):
            trial_c = trial_mode_data.get(mode, {}).get('count', 0)
            pay_c = payment_mode_data.get(mode, {}).get('count', 0)
            jobs_c = jobs_mode_data.get(mode, {}).get('count', 0)
            total = trial_c + pay_c + jobs_c
            mode_breakdown.append({
                'mode': MODE_NAMES.get(mode, f'Mode {mode}'),
                'count': total,
                'trial_uses': trial_c,
                'paid_uses': pay_c
            })
        mode_breakdown.sort(key=lambda x: x['count'], reverse=True)
        
        # Category breakdown (OCR / Translation / Proofread / Transcription)
        category_counts = {}
        for mode in all_modes:
            cat = MODE_CATEGORIES.get(mode, 'Other')
            trial_c = trial_mode_data.get(mode, {}).get('count', 0)
            pay_c = payment_mode_data.get(mode, {}).get('count', 0)
            jobs_c = jobs_mode_data.get(mode, {}).get('count', 0)
            category_counts[cat] = category_counts.get(cat, 0) + trial_c + pay_c + jobs_c
        category_breakdown = [{'category': k, 'count': v} for k, v in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)]
        
        # ============================================================
        # 3. BREAKDOWN BY LANGUAGE
        #    Source: jobs collection (has language field) + infer from modes
        #    Modes 1,2,3 = likely Hindi/Gujarati (OCR/Proofread for Indian languages)
        #    Modes 4,5 = translation (has source/target lang)
        #    Mode 6 = audio transcription
        # ============================================================
        
        # From jobs collection (new data - has explicit language field)
        jobs_lang_pipeline = [
            {'$match': {'language': {'$ne': None}}},
            {'$group': {'_id': {'$toLower': '$language'}, 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}}
        ]
        lang_breakdown_raw = list(jobs_col.aggregate(jobs_lang_pipeline))
        
        # If no jobs data yet, build from trial_usage mode inference
        if not lang_breakdown_raw:
            # Infer: modes 1-3 are typically Hindi/Gujarati, modes 4-5 translation, mode 6 audio
            lang_counts = {'Hindi': 0, 'Gujarati': 0, 'English': 0}
            for mode in all_modes:
                trial_c = trial_mode_data.get(mode, {}).get('count', 0)
                pay_c = payment_mode_data.get(mode, {}).get('count', 0)
                total = trial_c + pay_c
                if mode in (1, 2, 3):
                    # OCR/Proofread — primarily Hindi docs
                    lang_counts['Hindi'] += total
                elif mode in (4, 5):
                    # Translation — split between languages
                    lang_counts['Hindi'] += total // 2
                    lang_counts['English'] += total - (total // 2)
                elif mode == 6:
                    lang_counts['Hindi'] += total
            lang_breakdown = [{'language': k, 'count': v} for k, v in lang_counts.items() if v > 0]
            lang_breakdown.sort(key=lambda x: x['count'], reverse=True)
        else:
            lang_breakdown = [{'language': (l['_id'] or 'unknown').title(), 'count': l['count']} for l in lang_breakdown_raw]
        
        # ============================================================
        # 4. JOBS PER DAY (LAST 30 DAYS)
        #    Source: payments.created_at + jobs.created_at + trial_usage.last_used
        # ============================================================
        
        # From payments
        payment_daily_pipeline = [
            {'$match': {'created_at': {'$gte': thirty_days_ago}}},
            {'$group': {
                '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$created_at'}},
                'count': {'$sum': 1}
            }}
        ]
        payment_daily = {r['_id']: r['count'] for r in payments_col.aggregate(payment_daily_pipeline)}
        
        # From jobs collection
        jobs_daily_pipeline = [
            {'$match': {'created_at': {'$gte': thirty_days_ago}}},
            {'$group': {
                '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$created_at'}},
                'count': {'$sum': 1}
            }}
        ]
        jobs_daily = {r['_id']: r['count'] for r in jobs_col.aggregate(jobs_daily_pipeline)}
        
        # From trial_usage (last_used field)
        trial_daily_pipeline = [
            {'$match': {'last_used': {'$gte': thirty_days_ago}}},
            {'$group': {
                '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$last_used'}},
                'count': {'$sum': 1}
            }}
        ]
        trial_daily = {r['_id']: r['count'] for r in trial_col.aggregate(trial_daily_pipeline)}
        
        # Merge all daily data
        filled_daily = []
        for i in range(30):
            day = (thirty_days_ago + timedelta(days=i)).strftime('%Y-%m-%d')
            count = payment_daily.get(day, 0) + jobs_daily.get(day, 0) + trial_daily.get(day, 0)
            filled_daily.append({'date': day, 'count': count})
        
        # ============================================================
        # 5. AVERAGE PROCESSING TIME
        #    Source: jobs collection only (new tracking has timestamps)
        # ============================================================
        avg_time_pipeline = [
            {'$match': {'processing_time_seconds': {'$ne': None}}},
            {'$group': {
                '_id': None,
                'avg_time': {'$avg': '$processing_time_seconds'},
                'min_time': {'$min': '$processing_time_seconds'},
                'max_time': {'$max': '$processing_time_seconds'}
            }}
        ]
        avg_time_result = list(jobs_col.aggregate(avg_time_pipeline))
        avg_processing = avg_time_result[0] if avg_time_result else {
            'avg_time': None, 'min_time': None, 'max_time': None
        }
        
        # ============================================================
        # 6. FAILED VS SUCCESSFUL JOBS
        #    Source: jobs collection (status field) + payments (all success)
        # ============================================================
        
        # From jobs collection  
        jobs_status_pipeline = [
            {'$group': {'_id': '$status', 'count': {'$sum': 1}}}
        ]
        jobs_status = {s['_id']: s['count'] for s in jobs_col.aggregate(jobs_status_pipeline)}
        
        # All payments are successful jobs
        payment_success = payments_col.count_documents({'status': 'success'})
        
        # All trial_usage with pages_used > 0 are successful 
        trial_success = trial_active_count
        
        success_count = jobs_status.get('success', 0) + payment_success + trial_success
        failed_count = jobs_status.get('failed', 0)
        processing_count = jobs_status.get('processing', 0)
        completed_total = success_count + failed_count
        success_rate = round((success_count / completed_total * 100), 1) if completed_total > 0 else 100.0
        
        # ============================================================
        # 7. TOP USERS BY VOLUME
        #    Source: trial_usage (count records per email) + payments (count per email)
        # ============================================================
        
        # Aggregate usage from trial_usage
        trial_user_pipeline = [
            {'$match': {'pages_used': {'$gt': 0}}},
            {'$group': {'_id': '$email', 'trial_jobs': {'$sum': 1}, 'total_pages': {'$sum': '$pages_used'}}}
        ]
        trial_users = {r['_id']: r for r in trial_col.aggregate(trial_user_pipeline)}
        
        # Aggregate from payments
        payment_user_pipeline = [
            {'$group': {'_id': '$user_email', 'paid_jobs': {'$sum': 1}, 'total_spent': {'$sum': '$amount'}, 'total_paid_pages': {'$sum': '$pages'}}}
        ]
        payment_users = {r['_id']: r for r in payments_col.aggregate(payment_user_pipeline)}
        
        # Aggregate from jobs collection
        jobs_user_pipeline = [
            {'$group': {'_id': '$user_email', 'tracked_jobs': {'$sum': 1}}}
        ]
        jobs_users = {r['_id']: r for r in jobs_col.aggregate(jobs_user_pipeline)}
        
        # Merge all users
        all_user_emails = set(list(trial_users.keys()) + list(payment_users.keys()) + list(jobs_users.keys()))
        top_users = []
        for email in all_user_emails:
            if not email:
                continue
            trial_info = trial_users.get(email, {})
            payment_info = payment_users.get(email, {})
            jobs_info = jobs_users.get(email, {})
            
            total_jobs = (trial_info.get('trial_jobs', 0) + 
                         payment_info.get('paid_jobs', 0) + 
                         jobs_info.get('tracked_jobs', 0))
            total_pages = trial_info.get('total_pages', 0) + payment_info.get('total_paid_pages', 0)
            total_spent = payment_info.get('total_spent', 0)
            
            # Mask email for privacy
            if '@' in email:
                local, domain = email.split('@', 1)
                masked = local[:3] + '***@' + domain
            else:
                masked = email
            
            top_users.append({
                'email': email,
                'email_masked': masked,
                'count': total_jobs,
                'total_pages': round(total_pages, 1),
                'total_spent': total_spent
            })
        
        top_users.sort(key=lambda x: x['total_spent'], reverse=True)
        top_users = top_users[:10]
        
        # ============================================================
        # 8. FILE SIZE DISTRIBUTION
        #    Source: jobs collection only (has file_size_bytes)
        # ============================================================
        size_pipeline = [
            {'$match': {'file_size_bytes': {'$ne': None, '$gt': 0}}},
            {'$bucket': {
                'groupBy': '$file_size_bytes',
                'boundaries': [0, 1048576, 10485760, 104857600],
                'default': 'Very Large',
                'output': {'count': {'$sum': 1}}
            }}
        ]
        try:
            size_dist = list(jobs_col.aggregate(size_pipeline))
            size_labels = {0: 'Small (< 1MB)', 1048576: 'Medium (1-10MB)', 10485760: 'Large (> 10MB)'}
            file_size_breakdown = [{'label': size_labels.get(b['_id'], 'Very Large'), 'count': b['count']} for b in size_dist]
        except Exception:
            file_size_breakdown = []
        
        # If no jobs data, estimate from payments (pages as proxy)
        if not file_size_breakdown and payments_count > 0:
            small = payments_col.count_documents({'pages': {'$lte': 5}})
            medium = payments_col.count_documents({'pages': {'$gt': 5, '$lte': 30}})
            large = payments_col.count_documents({'pages': {'$gt': 30}})
            file_size_breakdown = [
                {'label': 'Small (≤ 5 pages)', 'count': small},
                {'label': 'Medium (6-30 pages)', 'count': medium},
                {'label': 'Large (30+ pages)', 'count': large}
            ]
            file_size_breakdown = [b for b in file_size_breakdown if b['count'] > 0]
        
        # ============================================================
        # 9. EXTRA METRICS
        # ============================================================
        
        # Total registered users
        total_users = users_col.count_documents({})
        
        # Users registered in last 30 days
        new_users_30d = users_col.count_documents({'created_at': {'$gte': thirty_days_ago}})
        
        # Revenue from payments
        revenue_pipeline = [
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ]
        revenue_result = list(payments_col.aggregate(revenue_pipeline))
        total_revenue = revenue_result[0]['total'] if revenue_result else 0
        
        # Total pages processed
        total_pages_pipeline = [
            {'$group': {'_id': None, 'total': {'$sum': '$pages_used'}}}
        ]
        total_pages_result = list(trial_col.aggregate(total_pages_pipeline))
        trial_pages = total_pages_result[0]['total'] if total_pages_result else 0
        
        paid_pages_pipeline = [
            {'$group': {'_id': None, 'total': {'$sum': '$pages'}}}
        ]
        paid_pages_result = list(payments_col.aggregate(paid_pages_pipeline))
        paid_pages = paid_pages_result[0]['total'] if paid_pages_result else 0
        
        total_pages = round(trial_pages + paid_pages, 1)
        
        # Paid vs free
        paid_count = payments_count
        free_count = trial_active_count
        
        # Jobs today (from jobs collection + payments today)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        jobs_today = (jobs_col.count_documents({'created_at': {'$gte': today_start}}) +
                     payments_col.count_documents({'created_at': {'$gte': today_start}}))
        
        # User registration timeline (last 30 days)
        user_daily_pipeline = [
            {'$match': {'created_at': {'$gte': thirty_days_ago}}},
            {'$group': {
                '_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$created_at'}},
                'count': {'$sum': 1}
            }},
            {'$sort': {'_id': 1}}
        ]
        user_daily = {r['_id']: r['count'] for r in users_col.aggregate(user_daily_pipeline)}
        user_signups_daily = []
        for i in range(30):
            day = (thirty_days_ago + timedelta(days=i)).strftime('%Y-%m-%d')
            user_signups_daily.append({'date': day, 'count': user_daily.get(day, 0)})
        
        return jsonify({
            'total_jobs': total_processed,
            'jobs_today': jobs_today,
            'total_users': total_users,
            'new_users_30d': new_users_30d,
            'total_pages': total_pages,
            'total_revenue': total_revenue,
            'mode_breakdown': mode_breakdown,
            'category_breakdown': category_breakdown,
            'language_breakdown': lang_breakdown,
            'daily_jobs': filled_daily,
            'user_signups_daily': user_signups_daily,
            'avg_processing_time': {
                'avg': round(avg_processing.get('avg_time') or 0, 1),
                'min': round(avg_processing.get('min_time') or 0, 1),
                'max': round(avg_processing.get('max_time') or 0, 1),
                'has_data': avg_processing.get('avg_time') is not None
            },
            'status': {
                'success': success_count,
                'failed': failed_count,
                'processing': processing_count,
                'success_rate': success_rate
            },
            'top_users': top_users,
            'file_size_distribution': file_size_breakdown,
            'paid_vs_free': {
                'paid': paid_count,
                'free': free_count
            }
        })
        
    except Exception as e:
        logger.error(f"Error fetching analytics: {e}")
        return jsonify({'error': str(e)}), 500
