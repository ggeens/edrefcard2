#!/usr/bin/env python3
"""
EDRefCard Admin Authentication

HTTP Basic Authentication for the admin panel.
Credentials are read from environment variables.
"""

import os
import hmac
import logging
from functools import wraps
from flask import request, Response, session, redirect, url_for
from scripts.models import Config


# Default credentials (override with environment variables)
ADMIN_USERNAME = os.environ.get('EDREFCARD_ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('EDREFCARD_ADMIN_PASS', 'changeme')

# Configure admin access logging (use persistent configs directory)
log_dir = Config.configsPath()
# Note: mkdir should be handled by app startup, but safe to allow existing
try:
    log_dir.mkdir(parents=True, exist_ok=True)
except Exception:
    pass # Assume exists or permission issue will be caught later

log_file = log_dir / 'admin_access.log'

admin_logger = logging.getLogger('admin_access')
admin_logger.setLevel(logging.INFO)

try:
    # Try to log to file
    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
except PermissionError:
    # Fallback to stderr if file is not writable
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[ADMIN-AUTH] %(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    print(f"Warning: Could not write to {log_file}. Logging to stderr instead.")
except Exception as e:
    # Fallback for other errors
    handler = logging.StreamHandler()
    print(f"Warning: Failed to setup admin log file: {e}. Logging to stderr instead.")

admin_logger.addHandler(handler)


def _sanitize_log(value, max_len=200):
    """Strip CR/LF and control chars from a value before logging (anti log-injection)."""
    text = str(value or '')
    text = text.replace('\r', ' ').replace('\n', ' ')
    text = ''.join(ch for ch in text if ch >= ' ')
    return text[:max_len]


def check_auth(username, password):
    """Check if username/password combination is valid.

    Args:
        username: Provided username
        password: Provided password

    Returns:
        True if valid, False otherwise
    """
    # Constant-time comparison to avoid leaking credential length/prefix via timing.
    # Compute both halves before AND-ing so the check doesn't short-circuit.
    user_ok = hmac.compare_digest(username or '', ADMIN_USERNAME)
    pass_ok = hmac.compare_digest(password or '', ADMIN_PASSWORD)
    is_valid = user_ok and pass_ok

    # Log authentication attempts (values sanitized: IP/UA/username are attacker-controlled)
    ip_address = _sanitize_log(request.headers.get('X-Forwarded-For', request.remote_addr))
    user_agent = _sanitize_log(request.headers.get('User-Agent', 'Unknown'))
    username = _sanitize_log(username)

    if is_valid:
        admin_logger.info(
            f"SUCCESS - User: {username} | IP: {ip_address} | UA: {user_agent}"
        )
    else:
        admin_logger.warning(
            f"FAILED - User: {username} | IP: {ip_address} | UA: {user_agent}"
        )
    
    return is_valid


def authenticate():
    """Send a 401 response that enables basic auth."""
    return Response(
        'Authentication required.\n'
        'Please provide valid admin credentials.',
        401,
        {'WWW-Authenticate': 'Basic realm="EDRefCard Admin"'}
    )


def _session_user():
    """Return the session-auth user dict ({'name', 'role'}) or None."""
    u = session.get('edrc_user')
    if isinstance(u, dict) and u.get('name') and u.get('role') in ('admin', 'mapper'):
        return u
    return None


def login_session_user(username, password):
    """DB-backed (or env-admin) login. On success stores the user in the
    session and returns its dict; on failure returns None. Attempts logged."""
    from werkzeug.security import check_password_hash
    from scripts import database

    ip_address = _sanitize_log(request.headers.get('X-Forwarded-For', request.remote_addr))
    safe_name = _sanitize_log(username)

    user = None
    # Env-configured admin can also use the login form (no DB row needed)
    user_ok = hmac.compare_digest(username or '', ADMIN_USERNAME)
    pass_ok = hmac.compare_digest(password or '', ADMIN_PASSWORD)
    if user_ok and pass_ok:
        user = {'name': ADMIN_USERNAME, 'role': 'admin'}
    else:
        try:
            row = database.get_user_by_username(username or '')
        except Exception:
            row = None
        if row and check_password_hash(row['password_hash'], password or ''):
            user = {'name': row['username'], 'role': row['role']}
            try:
                database.touch_user_login(row['id'])
            except Exception:
                pass

    if user:
        session['edrc_user'] = user
        session.permanent = True
        admin_logger.info(f"SESSION LOGIN - User: {safe_name} ({user['role']}) | IP: {ip_address}")
    else:
        admin_logger.warning(f"SESSION LOGIN FAILED - User: {safe_name} | IP: {ip_address}")
    return user


def logout_session_user():
    session.pop('edrc_user', None)


def current_user():
    """Resolve the request's (name, role): session first, then HTTP Basic
    against the env admin credentials. (None, None) when unauthenticated."""
    su = _session_user()
    if su:
        return su['name'], su['role']
    auth = request.authorization
    if auth and check_auth(auth.username, auth.password):
        return auth.username, 'admin'
    return None, None


def _require(roles):
    """Decorator factory: allow the request only for the given roles."""
    def deco(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            name, role = current_user()
            if role in roles:
                return f(*args, **kwargs)
            if name:
                return Response('Forbidden: your role does not allow this page.', 403)
            # Unauthenticated: browsers go to the login form; API/tools that
            # sent (bad) Basic credentials keep getting the Basic challenge.
            if request.authorization:
                return authenticate()
            return redirect(url_for('admin.login', next=request.full_path.rstrip('?')))
        return decorated
    return deco


def require_admin(f):
    """Full admin panel access (role 'admin' via session, or env HTTP Basic)."""
    return _require(('admin',))(f)


def require_mapper(f):
    """Controller-mapping access: role 'mapper' or 'admin'."""
    return _require(('admin', 'mapper'))(f)
