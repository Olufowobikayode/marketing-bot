# ai.py
import os
import json
import logging
import time
import requests
from typing import Optional, Dict, Any
from requests.adapters import HTTPAdapter, Retry

# ========= CONFIG =========
try:
    from config import GEMINI_API_KEY
except Exception:
    from dotenv import load_dotenv
    load_dotenv()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("❌ GEMINI_API_KEY not set in .env")

# ========= LOGGING =========
logger = logging.getLogger("ai")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# ========= HTTP SESSION WITH RETRIES =========
def _build_robust_session() -> requests.Session:
    """Create HTTP session with retry strategy."""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        backoff_factor=1,
        raise_on_status=False
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session

# Global session for connection reuse
SESSION = _build_robust_session()

# ========= RATE LIMITING =========
class RateLimiter:
    """Simple rate limiter for API calls."""
    def __init__(self, calls_per_minute: int = 15):
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call_time = 0
        
    def wait_if_needed(self):
        """Wait if needed to respect rate limits."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            logger.debug("Rate limiting: sleeping for %.2f seconds", sleep_time)
            time.sleep(sleep_time)
        self.last_call_time = time.time()

# Global rate limiter (Gemini free tier: 15 RPM)
RATE_LIMITER = RateLimiter(calls_per_minute=15)

# ========= LOW LEVEL API CALL =========
def call_gemini(
    prompt: str, 
    max_tokens: int = 1200, 
    temperature: float = 0.4,
    timeout: int = 45,
    max_retries: int = 3
) -> Optional[str]:
    """
    Send a prompt to Gemini Pro with retries and robust error handling.
    Returns None on failure.
    """
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}

    body = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "topP": 0.8,
            "topK": 40
        },
        "safetySettings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH", 
                "threshold": "BLOCK_MEDIUM_AND_ABOVE"
            }
        ]
    }

    last_exception = None
    
    for attempt in range(max_retries):
        try:
            # Respect rate limits
            RATE_LIMITER.wait_if_needed()
            
            logger.info("Gemini API call attempt %d/%d", attempt + 1, max_retries)
            
            response = SESSION.post(
                url, 
                headers=headers, 
                params=params, 
                json=body, 
                timeout=timeout
            )
            
            # Log rate limit headers for debugging
            if 'X-RateLimit-Remaining' in response.headers:
                remaining = response.headers['X-RateLimit-Remaining']
                logger.debug("Rate limit remaining: %s", remaining)
            
            response.raise_for_status()
            data = response.json()
            
            # Validate response structure
            if not data.get("candidates"):
                logger.warning("Gemini returned no candidates in response")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.info("Retrying in %d seconds...", wait_time)
                    time.sleep(wait_time)
                    continue
                return None
            
            candidate = data["candidates"][0]
            
            # Check for content filtering
            if candidate.get("finishReason") == "SAFETY":
                logger.warning("Gemini blocked content for safety reasons")
                return None
                
            if "content" not in candidate:
                logger.warning("Gemini candidate missing content")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None
                
            parts = candidate["content"].get("parts", [])
            if not parts:
                logger.warning("Gemini returned empty parts")
                return None
                
            text = parts[0].get("text", "").strip()
            
            if not text:
                logger.warning("Gemini returned empty text")
                return None
                
            logger.info("Gemini API call successful")
            return text
            
        except requests.exceptions.Timeout:
            logger.warning("Gemini API timeout on attempt %d", attempt + 1)
            last_exception = "Timeout"
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5  # 5, 10, 15 seconds
                logger.info("Retrying after timeout in %d seconds...", wait_time)
                time.sleep(wait_time)
                continue
                
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "Unknown"
            logger.warning("Gemini API HTTP error %s on attempt %d", status_code, attempt + 1)
            
            if e.response.status_code == 429:  # Rate limited
                retry_after = e.response.headers.get('Retry-After', 60)
                wait_time = int(retry_after) + 5
                logger.warning("Rate limited, waiting %d seconds", wait_time)
                time.sleep(wait_time)
                continue
            elif e.response.status_code >= 500:  # Server error
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info("Server error, retrying in %d seconds...", wait_time)
                    time.sleep(wait_time)
                    continue
            else:
                # Client errors (4xx) won't be retried
                logger.error("Gemini API client error: %s", e)
                break
                
        except requests.exceptions.ConnectionError:
            logger.warning("Gemini API connection error on attempt %d", attempt + 1)
            last_exception = "ConnectionError"
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info("Retrying connection in %d seconds...", wait_time)
                time.sleep(wait_time)
                continue
                
        except json.JSONDecodeError as e:
            logger.error("Gemini API JSON decode error: %s", e)
            last_exception = "JSONDecodeError"
            break  # Don't retry JSON errors
            
        except Exception as e:
            logger.exception("Unexpected Gemini API error on attempt %d: %s", attempt + 1, e)
            last_exception = str(e)
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info("Retrying after unexpected error in %d seconds...", wait_time)
                time.sleep(wait_time)
                continue
    
    logger.error("All Gemini API attempts failed. Last error: %s", last_exception)
    return None

# ========= PROMPT TEMPLATES =========
MJML_TEMPLATE_PROMPT = """You are an expert email designer. Generate a valid, responsive MJML email template.

Title: {title}
Brief: {brief}

Requirements:
- Output ONLY valid MJML code, wrapped in <mjml>...</mjml>
- Include these sections: preheader, headline, hero image, content blocks, CTA button
- Use placeholders like {{name}}, {{cta_url}} where appropriate
- Make it responsive and mobile-friendly
- Use modern, clean design
- Include inline CSS fallbacks where needed
- Ensure proper spacing and typography

Important: Only output the MJML code, no explanations."""

EDIT_TEMPLATE_PROMPT = """You are an expert email designer. Edit the following MJML template according to this instruction: {instruction}

Current MJML template:
{existing_html}

Requirements:
- Return ONLY valid MJML code, wrapped in <mjml>...</mjml>
- Maintain all existing functionality and placeholders
- Ensure the output remains responsive and valid

Important: Only output the edited MJML code, no explanations."""

COPYWRITE_PROMPT = """You are a professional marketing copywriter. Write compelling email copy based on the following prompt.

Prompt: {prompt_text}

Requirements:
- Return strictly in JSON format with keys: "subject" and "body"
- Subject should be engaging and under 60 characters
- Body should be concise but persuasive, 2-3 paragraphs max
- Include a clear call-to-action
- Tone should be professional but friendly

Important: Only output valid JSON, no other text."""

# ========= HIGH LEVEL HELPERS =========
def generate_template(title: str, brief: str) -> Optional[str]:
    """
    Generate a valid MJML email template with robust error handling.
    """
    if not title or not brief:
        logger.error("generate_template called with empty title or brief")
        return None
        
    prompt = MJML_TEMPLATE_PROMPT.format(title=title, brief=brief)
    
    try:
        logger.info("Generating template: '%s'", title)
        result = call_gemini(prompt, max_tokens=1600, temperature=0.7)
        
        if not result:
            logger.error("Failed to generate template for '%s'", title)
            return None
            
        mjml_code = _extract_mjml(result)
        
        if not mjml_code:
            logger.error("No valid MJML extracted for template '%s'", title)
            return None
            
        # Basic validation
        if not _validate_mjml_structure(mjml_code):
            logger.warning("Generated MJML structure validation failed for '%s'", title)
            # Still return it, but log warning
            
        logger.info("Successfully generated template: '%s'", title)
        return mjml_code
        
    except Exception as e:
        logger.exception("Unexpected error in generate_template: %s", e)
        return None

def edit_template(existing_html: str, instruction: str) -> Optional[str]:
    """
    Edit a template based on user instruction with robust error handling.
    """
    if not existing_html or not instruction:
        logger.error("edit_template called with empty html or instruction")
        return None
        
    prompt = EDIT_TEMPLATE_PROMPT.format(
        instruction=instruction, 
        existing_html=existing_html
    )
    
    try:
        logger.info("Editing template with instruction: '%s'", instruction[:50])
        result = call_gemini(prompt, max_tokens=1600, temperature=0.3)
        
        if not result:
            logger.error("Failed to edit template")
            return None
            
        mjml_code = _extract_mjml(result)
        
        if not mjml_code:
            logger.error("No valid MJML extracted from edit result")
            return None
            
        logger.info("Successfully edited template")
        return mjml_code
        
    except Exception as e:
        logger.exception("Unexpected error in edit_template: %s", e)
        return None

def ai_copywrite(prompt_text: str) -> Dict[str, str]:
    """
    Generate subject + body copy for marketing email with robust error handling.
    Returns a dict with subject, body.
    """
    if not prompt_text:
        logger.error("ai_copywrite called with empty prompt")
        return _get_fallback_copy("Empty prompt")
        
    prompt = COPYWRITE_PROMPT.format(prompt_text=prompt_text)
    
    try:
        logger.info("Generating copy for prompt: '%s'", prompt_text[:50])
        result = call_gemini(prompt, max_tokens=800, temperature=0.8)
        
        if not result:
            logger.warning("AI copywrite returned no result, using fallback")
            return _get_fallback_copy(prompt_text)
            
        # Try to parse JSON
        try:
            copy_data = json.loads(result.strip())
            
            # Validate structure
            if not isinstance(copy_data, dict):
                logger.warning("AI copywrite returned non-dict JSON")
                return _get_fallback_copy(prompt_text)
                
            subject = copy_data.get("subject", "").strip()
            body = copy_data.get("body", "").strip()
            
            if not subject or not body:
                logger.warning("AI copywrite returned empty subject or body")
                return _get_fallback_copy(prompt_text)
                
            logger.info("Successfully generated copy")
            return {"subject": subject, "body": body}
            
        except json.JSONDecodeError:
            logger.warning("AI copywrite returned non-JSON, trying to extract text")
            return _extract_copy_from_text(result, prompt_text)
            
    except Exception as e:
        logger.exception("Unexpected error in ai_copywrite: %s", e)
        return _get_fallback_copy(prompt_text)

# ========= INTERNAL HELPERS =========
def _extract_mjml(text: Optional[str]) -> Optional[str]:
    """
    Extract MJML code from AI response with robust parsing.
    Ensures it is wrapped in <mjml>...</mjml>.
    """
    if not text:
        return None
        
    # Clean the text
    text = text.strip()
    
    # Look for MJML tags
    start_tag = text.find("<mjml>")
    end_tag = text.rfind("</mjml>")
    
    if start_tag != -1 and end_tag != -1 and end_tag > start_tag:
        mjml = text[start_tag:end_tag + 7]  # +7 for </mjml>
        logger.debug("Extracted MJML with tags")
        return mjml
    else:
        # Check if it might be MJML without proper tags
        if any(tag in text for tag in ["<mj-", "<mjml"]):
            logger.warning("MJML-like content found but missing proper tags, wrapping")
            return f"<mjml>{text}</mjml>"
        else:
            logger.warning("No MJML content found in AI response")
            return None

def _validate_mjml_structure(mjml_code: str) -> bool:
    """
    Basic validation of MJML structure.
    """
    required_elements = ["<mjml>", "<mj-body>", "</mjml>"]
    return all(element in mjml_code for element in required_elements)

def _get_fallback_copy(prompt_text: str) -> Dict[str, str]:
    """Generate fallback copy when AI fails."""
    subject = f"Update: {prompt_text[:30]}..." if len(prompt_text) > 30 else f"Update: {prompt_text}"
    body = f"Hello! We wanted to share this update with you:\n\n{prompt_text}\n\nThank you for your attention."
    
    return {
        "subject": subject,
        "body": body
    }

def _extract_copy_from_text(text: str, original_prompt: str) -> Dict[str, str]:
    """
    Extract subject and body from non-JSON AI response.
    """
    lines = text.strip().split('\n')
    subject = ""
    body_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        lower_line = line.lower()
        if any(keyword in lower_line for keyword in ["subject:", "title:"]):
            # Extract subject
            subject = line.split(':', 1)[1].strip() if ':' in line else line
        else:
            body_lines.append(line)
    
    body = '\n'.join(body_lines).strip()
    
    if not subject:
        subject = f"Update: {original_prompt[:30]}..."
    if not body:
        body = f"Hello! Here's an update regarding: {original_prompt}"
    
    return {
        "subject": subject,
        "body": body
    }

# ========= HEALTH CHECK =========
def health_check() -> Dict[str, Any]:
    """
    Perform health check on AI module.
    Returns status and diagnostics.
    """
    status = {
        "module": "ai",
        "status": "unknown",
        "gemini_configured": bool(GEMINI_API_KEY),
        "timestamp": time.time()
    }
    
    if not GEMINI_API_KEY:
        status["status"] = "error"
        status["error"] = "GEMINI_API_KEY not configured"
        return status
    
    # Test with a simple prompt
    test_prompt = "Respond with only: OK"
    try:
        result = call_gemini(test_prompt, max_tokens=10, max_retries=1, timeout=10)
        if result and "OK" in result:
            status["status"] = "healthy"
            status["response_time"] = "normal"
        else:
            status["status"] = "degraded"
            status["error"] = "Unexpected response from Gemini"
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
    
    return status

# ========= CLI TEST =========
if __name__ == "__main__":
    print("🤖 AI Module Production Test")
    print("=" * 50)
    
    # Health check
    health = health_check()
    print(f"Health Status: {health['status']}")
    print(f"Gemini Configured: {health['gemini_configured']}")
    
    if health["status"] == "healthy":
        # Test template generation
        print("\n🧪 Testing template generation...")
        mjml = generate_template("Welcome Email", "A friendly welcome email for new subscribers")
        if mjml:
            print("✅ Template generation: SUCCESS")
            print(f"   MJML length: {len(mjml)} characters")
            print(f"   Valid structure: {_validate_mjml_structure(mjml)}")
        else:
            print("❌ Template generation: FAILED")
        
        # Test copywriting
        print("\n📝 Testing copywriting...")
        copy = ai_copywrite("Promote our new product launch")
        if copy and copy.get("subject") and copy.get("body"):
            print("✅ Copywriting: SUCCESS")
            print(f"   Subject: {copy['subject']}")
            print(f"   Body preview: {copy['body'][:50]}...")
        else:
            print("❌ Copywriting: FAILED")
            
        # Test editing
        print("\n✏️ Testing template editing...")
        if mjml:
            edited = edit_template(mjml, "Change the button color to blue")
            if edited:
                print("✅ Template editing: SUCCESS")
            else:
                print("❌ Template editing: FAILED")
        else:
            print("⏭️ Template editing: SKIPPED (no template to edit)")
    
    print("\n" + "=" * 50)
    print("AI Module Test Complete")