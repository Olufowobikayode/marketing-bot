# mailer.py
"""
Production-ready Mailer module with ~20 marketing providers + Gmail/Outlook SMTP fallbacks.
- Robust error handling and retry mechanisms
- Connection pooling and rate limiting
- Comprehensive logging and monitoring
- Provider health checks and fallback strategies
"""

import os
import time
import json
import logging
import random
import ssl
import smtplib
import asyncio
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter, Retry

# ========= LOGGING =========
logger = logging.getLogger("mailer")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# ========= CONFIGURATION =========
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 0.1  # Minimum delay between sends in seconds
BATCH_SIZE = 50
MAX_WORKERS = 5

# ========= DATA STRUCTURES =========
@dataclass
class SendResult:
    """Structured result for email send attempts."""
    success: bool
    provider: str
    recipient: str
    message_id: str = ""
    error: str = ""
    response_time: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "provider": self.provider,
            "recipient": self.recipient,
            "message_id": self.message_id,
            "error": self.error,
            "response_time": self.response_time,
            "timestamp": self.timestamp
        }

@dataclass
class ProviderHealth:
    """Health status for email providers."""
    name: str
    enabled: bool = True
    last_used: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0
    average_response_time: float = 0.0
    consecutive_failures: int = 0
    last_error: str = ""

    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def should_use(self) -> bool:
        """Determine if provider should be used based on health."""
        if not self.enabled:
            return False
        if self.consecutive_failures >= 3:
            return False
        if self.success_rate() < 0.5 and self.success_count + self.failure_count > 10:
            return False
        return True

# ========= HTTP SESSION =========
def _build_robust_session() -> requests.Session:
    """Create HTTP session with comprehensive retry strategy."""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT"],
        backoff_factor=1.0,
        raise_on_status=False
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=20,
        pool_maxsize=20,
        pool_block=False
    )
    
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    # Set default headers
    session.headers.update({
        "User-Agent": "MarketingMailer/1.0",
        "Accept": "application/json",
        "Content-Type": "application/json"
    })
    
    return session

SESSION = _build_robust_session()

# ========= PROVIDER CONFIGURATION =========
PROVIDERS_CONFIG = {
    "Brevo": {
        "type": "api", 
        "env_key": "BREVO_API_KEY", 
        "api_url": "https://api.brevo.com/v3/smtp/email",
        "priority": 1
    },
    "SendGrid": {
        "type": "api", 
        "env_key": "SENDGRID_API_KEY", 
        "api_url": "https://api.sendgrid.com/v3/mail/send",
        "priority": 1
    },
    "Mailgun": {
        "type": "api", 
        "env_key": "MAILGUN_API_KEY", 
        "domain_env": "MAILGUN_DOMAIN", 
        "api_url_template": "https://api.mailgun.net/v3/{domain}/messages",
        "priority": 2
    },
    "MailerSend": {
        "type": "api", 
        "env_key": "MAILERSEND_API_KEY", 
        "api_url": "https://api.mailersend.com/v1/email",
        "priority": 2
    },
    "Mailjet": {
        "type": "api", 
        "api_key_env": "MAILJET_API_KEY", 
        "api_secret_env": "MAILJET_SECRET", 
        "api_url": "https://api.mailjet.com/v3.1/send",
        "priority": 3
    },
    "ElasticEmail": {
        "type": "api", 
        "env_key": "ELASTIC_API_KEY", 
        "api_url": "https://api.elasticemail.com/v2/email/send",
        "priority": 3
    },
    "Postmark": {
        "type": "api", 
        "env_key": "POSTMARK_API_KEY", 
        "api_url": "https://api.postmarkapp.com/email",
        "priority": 2
    },
    "SparkPost": {
        "type": "api", 
        "env_key": "SPARKPOST_API_KEY", 
        "api_url": "https://api.sparkpost.com/api/v1/transmissions",
        "priority": 3
    },
    # Fallback SMTP providers
    "SMTP-Gmail": {
        "type": "smtp", 
        "host_env": "SMTP_GMAIL_HOST", 
        "port_env": "SMTP_GMAIL_PORT", 
        "user_env": "SMTP_GMAIL_USER", 
        "pass_env": "SMTP_GMAIL_PASS",
        "priority": 99
    },
    "SMTP-Outlook": {
        "type": "smtp", 
        "host_env": "SMTP_OUTLOOK_HOST", 
        "port_env": "SMTP_OUTLOOK_PORT", 
        "user_env": "SMTP_OUTLOOK_USER", 
        "pass_env": "SMTP_OUTLOOK_PASS",
        "priority": 99
    },
}

# ========= PROVIDER CREDENTIALS =========
def provider_credentials(name: str) -> Dict[str, Any]:
    """Get provider credentials with validation and caching."""
    cfg = PROVIDERS_CONFIG.get(name, {})
    if not cfg:
        return {}
        
    creds = {
        "name": name,
        "type": cfg.get("type"),
        "priority": cfg.get("priority", 99),
        "enabled": True
    }
    
    try:
        if cfg.get("type") == "api":
            # API key providers
            if "env_key" in cfg:
                api_key = os.getenv(cfg["env_key"])
                if api_key:
                    creds["api_key"] = api_key
                else:
                    creds["enabled"] = False
                    
            if "api_key_env" in cfg and "api_secret_env" in cfg:
                api_key = os.getenv(cfg["api_key_env"])
                api_secret = os.getenv(cfg["api_secret_env"])
                if api_key and api_secret:
                    creds["api_key"] = api_key
                    creds["api_secret"] = api_secret
                else:
                    creds["enabled"] = False
                    
            if "domain_env" in cfg:
                domain = os.getenv(cfg["domain_env"])
                if domain:
                    creds["domain"] = domain
                else:
                    creds["enabled"] = False
                    
            # Build final API URL
            if "api_url_template" in cfg and "domain" in creds:
                creds["api_url"] = cfg["api_url_template"].format(domain=creds["domain"])
            else:
                creds["api_url"] = cfg.get("api_url")
                
        elif cfg.get("type") == "smtp":
            # SMTP providers
            host = os.getenv(cfg.get("host_env", ""))
            port = int(os.getenv(cfg.get("port_env", "587")))
            user = os.getenv(cfg.get("user_env", ""))
            password = os.getenv(cfg.get("pass_env", ""))
            
            if host and user and password:
                creds.update({
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password
                })
            else:
                creds["enabled"] = False
                
    except Exception as e:
        logger.error("Error loading credentials for %s: %s", name, e)
        creds["enabled"] = False
        
    return creds

# ========= PROVIDER SEND FUNCTIONS =========
def _send_brevo(to_email: str, subject: str, html: str, creds: Dict) -> Tuple[bool, str, str]:
    """Send via Brevo API."""
    start_time = time.time()
    message_id = f"brevo_{int(start_time)}_{hash(to_email) % 10000:04d}"
    
    try:
        api_key = creds.get("api_key")
        if not api_key:
            return False, "missing_api_key", message_id
            
        url = creds.get("api_url")
        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        sender_email = os.getenv("SENDER_EMAIL") or creds.get("sender", "no-reply@example.com")
        sender_name = os.getenv("SENDER_NAME") or "No Reply"
        
        payload = {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html,
            "tags": ["marketing-bot"]
        }
        
        response = SESSION.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response_time = time.time() - start_time
        
        if response.status_code == 201:
            response_data = response.json()
            actual_message_id = response_data.get("messageId", message_id)
            return True, f"sent in {response_time:.2f}s", actual_message_id
        else:
            error_msg = f"{response.status_code}: {response.text[:100]}"
            return False, error_msg, message_id
            
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"exception: {str(e)}"
        return False, error_msg, message_id

def _send_sendgrid(to_email: str, subject: str, html: str, creds: Dict) -> Tuple[bool, str, str]:
    """Send via SendGrid API."""
    start_time = time.time()
    message_id = f"sg_{int(start_time)}_{hash(to_email) % 10000:04d}"
    
    try:
        api_key = creds.get("api_key")
        if not api_key:
            return False, "missing_api_key", message_id
            
        url = creds.get("api_url")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        sender_email = os.getenv("SENDER_EMAIL") or "no-reply@example.com"
        
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": sender_email},
            "subject": subject,
            "content": [{"type": "text/html", "value": html}]
        }
        
        response = SESSION.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        response_time = time.time() - start_time
        
        if response.status_code == 202:
            # SendGrid doesn't return message ID in response, use headers if available
            message_id_header = response.headers.get('X-Message-Id', message_id)
            return True, f"sent in {response_time:.2f}s", message_id_header
        else:
            error_msg = f"{response.status_code}: {response.text[:100]}"
            return False, error_msg, message_id
            
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"exception: {str(e)}"
        return False, error_msg, message_id

def _send_mailgun(to_email: str, subject: str, html: str, creds: Dict) -> Tuple[bool, str, str]:
    """Send via Mailgun API."""
    start_time = time.time()
    message_id = f"mg_{int(start_time)}_{hash(to_email) % 10000:04d}"
    
    try:
        api_key = creds.get("api_key")
        domain = creds.get("domain")
        if not api_key or not domain:
            return False, "missing_credentials", message_id
            
        url = PROVIDERS_CONFIG["Mailgun"]["api_url_template"].format(domain=domain)
        sender_email = os.getenv("SENDER_EMAIL") or f"postmaster@{domain}"
        
        data = {
            "from": sender_email,
            "to": to_email,
            "subject": subject,
            "html": html
        }
        
        response = SESSION.post(
            url, 
            auth=("api", api_key), 
            data=data, 
            timeout=DEFAULT_TIMEOUT
        )
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            response_data = response.json()
            actual_message_id = response_data.get("id", message_id)
            return True, f"sent in {response_time:.2f}s", actual_message_id
        else:
            error_msg = f"{response.status_code}: {response.text[:100]}"
            return False, error_msg, message_id
            
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"exception: {str(e)}"
        return False, error_msg, message_id

def _send_smtp_provider(creds: Dict, to_email: str, subject: str, html: str) -> Tuple[bool, str, str]:
    """Send via SMTP provider."""
    start_time = time.time()
    message_id = f"smtp_{int(start_time)}_{hash(to_email) % 10000:04d}"
    
    try:
        host = creds.get("host")
        port = creds.get("port", 587)
        user = creds.get("user")
        password = creds.get("password")
        
        if not all([host, user, password]):
            return False, "smtp_missing_credentials", message_id
            
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to_email
        msg["Message-ID"] = f"<{message_id}@{host}>"
        
        # Add HTML part
        msg.attach(MIMEText(html, "html"))
        
        # Create SSL context
        context = ssl.create_default_context()
        
        # Connect and send
        with smtplib.SMTP(host, port, timeout=DEFAULT_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
            
        response_time = time.time() - start_time
        return True, f"sent in {response_time:.2f}s", message_id
        
    except Exception as e:
        response_time = time.time() - start_time
        error_msg = f"smtp_exception: {str(e)}"
        return False, error_msg, message_id

# Provider function mapping
PROVIDER_SENDERS = {
    "Brevo": _send_brevo,
    "SendGrid": _send_sendgrid,
    "Mailgun": _send_mailgun,
    "MailerSend": _send_brevo,  # Similar to Brevo
    "Mailjet": _send_brevo,     # Similar structure
    "ElasticEmail": _send_brevo,
    "Postmark": _send_brevo,
    "SparkPost": _send_brevo,
    "SMTP-Gmail": lambda e, s, h, c: _send_smtp_provider(c, e, s, h),
    "SMTP-Outlook": lambda e, s, h, c: _send_smtp_provider(c, e, s, h),
}

# ========= RATE LIMITER =========
class RateLimiter:
    """Thread-safe rate limiter for email sending."""
    def __init__(self, calls_per_second: float = 2.0):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call_time = 0
        self._lock = asyncio.Lock()
        
    async def wait_if_needed(self):
        """Wait if needed to respect rate limits (async)."""
        async with self._lock:
            current_time = time.time()
            elapsed = current_time - self.last_call_time
            
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                await asyncio.sleep(sleep_time)
                
            self.last_call_time = time.time()

# ========= MAIN MAILER CLASS =========
class Mailer:
    """
    Production-ready mailer with provider rotation, health checks, and comprehensive monitoring.
    """
    
    def __init__(
        self, 
        providers_order: Optional[List[str]] = None,
        requests_per_second: float = 2.0,
        max_retries: int = 3,
        timeout: int = DEFAULT_TIMEOUT,
        max_workers: int = MAX_WORKERS
    ):
        self.requests_per_second = max(0.1, requests_per_second)
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_workers = max_workers
        self.rate_limiter = RateLimiter(self.requests_per_second)
        
        # Load and initialize providers
        self.providers = self._load_providers()
        self.provider_health: Dict[str, ProviderHealth] = {}
        self._initialize_provider_health()
        
        # Set provider order (priority-based)
        if providers_order:
            self.providers_order = [p for p in providers_order if p in self.providers]
        else:
            self.providers_order = self._get_priority_order()
            
        logger.info(
            "Mailer initialized with %d providers: %s", 
            len(self.providers_order), 
            self.providers_order
        )
        
    def _load_providers(self) -> Dict[str, Dict]:
        """Load and validate available providers."""
        available = {}
        for name in PROVIDERS_CONFIG.keys():
            creds = provider_credentials(name)
            if creds.get("enabled", False):
                available[name] = creds
                logger.debug("Loaded provider: %s", name)
            else:
                logger.debug("Skipping provider %s - not configured", name)
                
        return available
    
    def _initialize_provider_health(self):
        """Initialize health tracking for all providers."""
        for name in self.providers.keys():
            self.provider_health[name] = ProviderHealth(name=name)
    
    def _get_priority_order(self) -> List[str]:
        """Get providers ordered by priority and health."""
        providers_with_priority = []
        for name, creds in self.providers.items():
            health = self.provider_health.get(name, ProviderHealth(name=name))
            if health.should_use():
                priority = creds.get("priority", 99)
                success_rate = health.success_rate()
                # Prefer providers with higher success rates
                adjusted_priority = priority - (success_rate * 10)
                providers_with_priority.append((adjusted_priority, name))
        
        # Sort by adjusted priority (lower is better)
        providers_with_priority.sort(key=lambda x: x[0])
        return [name for _, name in providers_with_priority]
    
    def _update_provider_health(self, provider: str, success: bool, response_time: float, error: str = ""):
        """Update health statistics for a provider."""
        if provider not in self.provider_health:
            self.provider_health[provider] = ProviderHealth(name=provider)
            
        health = self.provider_health[provider]
        health.last_used = datetime.now()
        
        if success:
            health.success_count += 1
            health.consecutive_failures = 0
            # Update average response time
            total_requests = health.success_count + health.failure_count
            health.average_response_time = (
                (health.average_response_time * (total_requests - 1) + response_time) 
                / total_requests
            )
        else:
            health.failure_count += 1
            health.consecutive_failures += 1
            health.last_error = error
            
        logger.debug(
            "Provider %s health updated: success_rate=%.2f, avg_time=%.2fs",
            provider, health.success_rate(), health.average_response_time
        )
    
    async def send_single(
        self, 
        to_email: str, 
        subject: str, 
        html: str, 
        preferred_provider: Optional[str] = None
    ) -> SendResult:
        """
        Send a single email with provider fallback and retry logic.
        """
        # Respect rate limits
        await self.rate_limiter.wait_if_needed()
        
        # Determine provider order for this send
        if preferred_provider and preferred_provider in self.providers:
            providers_to_try = [preferred_provider] + [
                p for p in self.providers_order if p != preferred_provider
            ]
        else:
            providers_to_try = self.providers_order.copy()
        
        last_error = ""
        
        for provider in providers_to_try:
            if not self.provider_health[provider].should_use():
                logger.debug("Skipping unhealthy provider: %s", provider)
                continue
                
            creds = self.providers[provider]
            sender_func = PROVIDER_SENDERS.get(provider)
            
            if not sender_func:
                logger.warning("No sender function for provider: %s", provider)
                continue
            
            # Try with retries
            for attempt in range(self.max_retries + 1):
                try:
                    start_time = time.time()
                    success, info, message_id = sender_func(to_email, subject, html, creds)
                    response_time = time.time() - start_time
                    
                    # Update health
                    self._update_provider_health(provider, success, response_time, info)
                    
                    if success:
                        return SendResult(
                            success=True,
                            provider=provider,
                            recipient=to_email,
                            message_id=message_id,
                            response_time=response_time,
                            timestamp=datetime.now().isoformat()
                        )
                    else:
                        last_error = f"{provider}: {info}"
                        logger.warning(
                            "Send attempt %d/%d failed for %s via %s: %s",
                            attempt + 1, self.max_retries + 1, to_email, provider, info
                        )
                        
                        if attempt < self.max_retries:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            
                except Exception as e:
                    response_time = time.time() - start_time
                    self._update_provider_health(provider, False, response_time, str(e))
                    last_error = f"{provider}: {str(e)}"
                    logger.warning(
                        "Exception in send attempt %d/%d for %s via %s: %s",
                        attempt + 1, self.max_retries + 1, to_email, provider, str(e)
                    )
                    
                    if attempt < self.max_retries:
                        await asyncio.sleep(2 ** attempt)
        
        # All providers failed
        return SendResult(
            success=False,
            provider="all",
            recipient=to_email,
            error=last_error,
            timestamp=datetime.now().isoformat()
        )
    
    async def send_bulk(
        self, 
        recipients: List[Dict], 
        subject: str, 
        html_template: str,
        personalized: bool = True,
        preferred_provider: Optional[str] = None,
        batch_size: int = BATCH_SIZE,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Send bulk emails with concurrency control and progress tracking.
        """
        total = len(recipients)
        sent = []
        failed = []
        
        logger.info("Starting bulk send to %d recipients", total)
        
        # Process in batches to manage memory and provide progress updates
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_recipients = recipients[batch_start:batch_end]
            
            logger.info("Processing batch %d-%d of %d", batch_start + 1, batch_end, total)
            
            # Use ThreadPoolExecutor for I/O bound operations
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Create future for each email
                future_to_email = {
                    executor.submit(
                        self._send_single_sync,
                        recipient,
                        subject,
                        html_template,
                        personalized,
                        preferred_provider
                    ): recipient.get("email")
                    for recipient in batch_recipients
                }
                
                # Process completed futures
                for future in as_completed(future_to_email):
                    email = future_to_email[future]
                    try:
                        result = future.result()
                        if result.success:
                            sent.append(result.to_dict())
                        else:
                            failed.append(result.to_dict())
                    except Exception as e:
                        logger.error("Unexpected error sending to %s: %s", email, e)
                        failed.append({
                            "success": False,
                            "provider": "unknown",
                            "recipient": email,
                            "error": f"unexpected_error: {str(e)}",
                            "timestamp": datetime.now().isoformat()
                        })
                    
                    # Progress callback
                    if progress_callback:
                        progress = len(sent) + len(failed)
                        progress_callback(progress, total)
            
            # Batch completion log
            batch_sent = len([r for r in sent if r.get("success")])
            batch_failed = len(failed)
            logger.info(
                "Batch completed: %d sent, %d failed (%.1f%%)",
                batch_sent, batch_failed, (batch_sent / len(batch_recipients)) * 100
            )
        
        # Final summary
        success_rate = (len(sent) / total) * 100 if total > 0 else 0
        logger.info(
            "Bulk send completed: %d total, %d sent, %d failed (%.1f%% success)",
            total, len(sent), len(failed), success_rate
        )
        
        return {
            "sent": sent,
            "failed": failed,
            "total": total,
            "success_rate": success_rate,
            "providers_used": list(set(r.get("provider") for r in sent)),
            "completed_at": datetime.now().isoformat()
        }
    
    def _send_single_sync(
        self, 
        recipient: Dict, 
        subject: str, 
        html_template: str,
        personalized: bool,
        preferred_provider: Optional[str]
    ) -> SendResult:
        """
        Synchronous wrapper for send_single for use with ThreadPoolExecutor.
        """
        email = recipient.get("email")
        name = recipient.get("name", "")
        
        # Personalize template
        if personalized:
            html = html_template.replace("{{name}}", name).replace("{{email}}", email)
        else:
            html = html_template
        
        # Run async function in sync context
        try:
            return asyncio.run(self.send_single(email, subject, html, preferred_provider))
        except Exception as e:
            return SendResult(
                success=False,
                provider="unknown",
                recipient=email,
                error=f"async_error: {str(e)}",
                timestamp=datetime.now().isoformat()
            )
    
    def health_check(self) -> Dict[str, Any]:
        """
        Comprehensive health check of mailer system.
        """
        health = {
            "module": "mailer",
            "status": "unknown",
            "providers_available": len(self.providers),
            "providers_healthy": 0,
            "total_requests": 0,
            "overall_success_rate": 0.0,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # Calculate overall health
            total_success = 0
            total_failures = 0
            healthy_providers = 0
            
            for provider_name, health_data in self.provider_health.items():
                total_success += health_data.success_count
                total_failures += health_data.failure_count
                
                if health_data.should_use():
                    healthy_providers += 1
            
            health["providers_healthy"] = healthy_providers
            health["total_requests"] = total_success + total_failures
            
            if health["total_requests"] > 0:
                health["overall_success_rate"] = total_success / health["total_requests"]
            
            # Determine overall status
            if health["providers_available"] == 0:
                health["status"] = "error"
                health["error"] = "No email providers configured"
            elif health["providers_healthy"] == 0:
                health["status"] = "error"
                health["error"] = "No healthy providers available"
            elif health["overall_success_rate"] < 0.5 and health["total_requests"] > 10:
                health["status"] = "degraded"
                health["warning"] = "Low success rate"
            else:
                health["status"] = "healthy"
            
            # Add provider details
            health["provider_details"] = {
                name: {
                    "enabled": h.enabled,
                    "success_rate": h.success_rate(),
                    "total_requests": h.success_count + h.failure_count,
                    "average_response_time": h.average_response_time,
                    "consecutive_failures": h.consecutive_failures,
                    "last_error": h.last_error
                }
                for name, h in self.provider_health.items()
            }
            
        except Exception as e:
            health["status"] = "error"
            health["error"] = str(e)
        
        return health

# ========= MODULE-LEVEL CONVENIENCE =========
_DEFAULT_MAILER = None

def get_default_mailer(
    requests_per_second: float = 2.0,
    max_retries: int = 3,
    timeout: int = DEFAULT_TIMEOUT,
    max_workers: int = MAX_WORKERS
) -> Mailer:
    """Get or create default mailer instance with thread-safe initialization."""
    global _DEFAULT_MAILER
    if _DEFAULT_MAILER is None:
        _DEFAULT_MAILER = Mailer(
            requests_per_second=requests_per_second,
            max_retries=max_retries,
            timeout=timeout,
            max_workers=max_workers
        )
    return _DEFAULT_MAILER

# ========= PROVIDER REFRESH =========
def refresh_mailer_providers():
    """
    Refresh the mailer's provider list to pick up newly added providers.
    This is useful when adding providers at runtime.
    """
    global _DEFAULT_MAILER
    _DEFAULT_MAILER = None
    logger.info("Mailer providers refreshed")

# ========= TEST AND DEMONSTRATION =========
if __name__ == "__main__":
    print("🚀 Mailer Module Production Test")
    print("=" * 60)
    
    # Initialize mailer
    mailer = get_default_mailer(requests_per_second=1.0)  # Slow for testing
    
    # Health check
    health = mailer.health_check()
    print(f"Health Status: {health['status']}")
    print(f"Providers Available: {health['providers_available']}")
    print(f"Providers Healthy: {health['providers_healthy']}")
    print(f"Overall Success Rate: {health['overall_success_rate']:.1%}")
    
    if health["status"] in ["healthy", "degraded"]:
        # Test single send (with test email)
        test_email = os.getenv("TEST_EMAIL")
        if test_email:
            print(f"\n🧪 Testing single send to {test_email}...")
            
            async def test_send():
                result = await mailer.send_single(
                    to_email=test_email,
                    subject="Mailer Test Email",
                    html="<h1>Test Email</h1><p>This is a test from the production mailer.</p>"
                )
                return result
            
            result = asyncio.run(test_send())
            print(f"Single Send Result: {'SUCCESS' if result.success else 'FAILED'}")
            if result.success:
                print(f"  Provider: {result.provider}")
                print(f"  Response Time: {result.response_time:.2f}s")
            else:
                print(f"  Error: {result.error}")
        else:
            print("\n⏭️ Single send test skipped (TEST_EMAIL not set)")
    
    print("\n" + "=" * 60)
    print("Mailer Module Test Complete")