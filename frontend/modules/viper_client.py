# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""ViperGirls forum client: thread titles, login, replies, and scheduled posting.

Python owns the forum workflow; the Go sidecar only executes one resolved
request at a time (see docs/TRANSPORT_CONTRACT.md).
"""

from datetime import datetime, timezone
import functools
import re
import threading
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from modules.sidecar import SidecarBridge
from modules.transport import build_transport_spec, execute_transport_request
from modules.viper_storage import (
    clean_thread_title,
    VIPERGIRLS_BASE_URL,
    ViperPostError,
    _is_supported_vipergirls_url,
    _parse_scheduled_time,
    add_scheduled_post,
    cancel_scheduled_post,
    extract_thread_id,
    load_scheduled_posts,
    normalize_thread_input,
    normalize_thread_record,
    set_scheduled_post_status,
    unique_target_name,
)

THREAD_TITLE_TIMEOUT_SECONDS = 8


THREAD_TITLE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


VIPERGIRLS_RATE_LIMIT = {"requests_per_second": 1.0, "burst_size": 3}


THREAD_TITLE_SELECTORS = (
    ".threadtitle",
    "span.threadtitle",
    "#thread_title",
    "h1.threadtitle",
    "h1.p-title-value",
    ".p-title-value",
    "h1",
)


def parse_thread_title_from_html(html_text: str) -> str:
    """Parse the thread title from ViperGirls/vBulletin-style HTML."""
    soup = BeautifulSoup(html_text or "", "html.parser")

    for selector in (
        "meta[property='og:title']",
        "meta[name='twitter:title']",
    ):
        element = soup.select_one(selector)
        title = clean_thread_title(element.get("content", "") if element else "")
        if title:
            return title

    for selector in THREAD_TITLE_SELECTORS:
        element = soup.select_one(selector)
        title = clean_thread_title(element.get_text(" ", strip=True) if element else "")
        if title:
            return title

    if soup.title:
        title = clean_thread_title(soup.title.get_text(" ", strip=True))
        if title:
            return title

    return ""


def fetch_thread_title(
    url: str,
    timeout: int = THREAD_TITLE_TIMEOUT_SECONDS,
    bridge: Optional[Any] = None,
) -> str:
    """Fetch the current ViperGirls thread title through the sidecar transport."""
    if not url or not _is_supported_vipergirls_url(url):
        return ""

    spec = build_transport_spec(
        url,
        method="GET",
        headers={
            "User-Agent": THREAD_TITLE_USER_AGENT,
            "Referer": f"{VIPERGIRLS_BASE_URL}/forum.php",
        },
        use_cookies=True,
    )
    try:
        response = execute_transport_request(
            spec,
            service="vipergirls.to",
            timeout=timeout,
            bridge=bridge,
            rate_limits=VIPERGIRLS_RATE_LIMIT,
        )
    except Exception as exc:
        logger.warning(f"Could not fetch ViperGirls thread title for {url}: {exc}")
        return ""
    if not response.ok:
        logger.warning(
            f"Could not fetch ViperGirls thread title for {url}: {response.message or 'failed'}"
        )
        return ""
    return parse_thread_title_from_html(response.body or "")


def build_site_named_thread_record(
    fallback_name: str,
    target: str,
    existing: Optional[Dict[str, object]] = None,
    notes: Optional[str] = None,
    tags: Optional[object] = None,
    existing_names: Optional[Any] = None,
    exclude: Optional[str] = None,
    fetch_title: bool = True,
) -> Tuple[str, Dict[str, object], bool]:
    """Normalize a target and choose a saved name from the live thread title when possible."""
    url, thread_id = normalize_thread_input(target)
    existing = existing or {}
    site_title = fetch_thread_title(url) if fetch_title else ""
    previous_site_title = str(existing.get("site_title") or "").strip()
    display_name = site_title or previous_site_title or fallback_name or f"Thread {thread_id}"
    key_name = unique_target_name(display_name, thread_id, existing_names, exclude=exclude)
    record = normalize_thread_record(
        display_name,
        target,
        existing=existing,
        notes=notes,
        tags=tags,
        site_title=site_title or previous_site_title,
    )
    return key_name, record, bool(site_title)


def _vipergirls_login_succeeded(body: str, final_url: str = "") -> bool:
    lowered = (body or "").lower()
    if "thank you for logging in" in lowered or "logout.php" in lowered:
        return True
    token_match = re.search(r"SECURITYTOKEN\s*=\s*\"([^\"]+)\"", body or "")
    if token_match and token_match.group(1).strip().lower() != "guest":
        return True
    return bool(re.search(r"(?i)(?:forum\.php|/forums?|/threads?)", final_url or ""))


def _vipergirls_post_succeeded(body: str, final_url: str = "") -> bool:
    if re.search(r"(?i)thank you for posting|redirecting", body or ""):
        return True
    return bool(re.search(r"(?i)(?:/threads/\d+|showthread\.php\?t=\d+)", final_url or ""))


def _extract_form_value(element: Any) -> str:
    if element.name == "textarea":
        return element.get_text() or ""
    if element.name == "select":
        selected = element.select_one("option[selected]")
        if selected is None:
            selected = element.select_one("option")
        return str(selected.get("value", selected.get_text(strip=True)) if selected else "")
    return str(element.get("value", ""))


def _copy_reply_form_fields(form: Any) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for element in form.select("input, textarea, select"):
        name = str(element.get("name") or "").strip()
        if not name:
            continue
        tag_name = str(element.name or "").lower()
        field_type = str(element.get("type") or "").lower()
        if tag_name == "input" and field_type in {"submit", "button", "image", "file"}:
            continue
        if field_type in {"checkbox", "radio"} and not element.has_attr("checked"):
            continue
        fields[name] = _extract_form_value(element)
    return fields


def _summarize_vipergirls_page(soup: BeautifulSoup) -> str:
    title = clean_thread_title(soup.title.get_text(" ", strip=True) if soup.title else "")
    page_text = " ".join((soup.get_text(" ", strip=True) or "").split())
    lowered = page_text.lower()
    if "you are not logged in" in lowered or "log in" == title.lower():
        return "ViperGirls returned a login page."
    if "no permission" in lowered or "do not have permission" in lowered:
        return "ViperGirls reported that this account cannot reply to the thread."
    if "thread is closed" in lowered or "closed thread" in lowered:
        return "ViperGirls reported that the thread is closed."
    if "just a moment" in lowered:
        return "ViperGirls returned an interstitial page."
    if title:
        return f"Reply form was not found on page '{title}'."
    return "Reply form was not found on the ViperGirls page."


def build_vipergirls_reply_spec(thread_id: str, message: str, html_text: str) -> Dict[str, Any]:
    """Parse a live ViperGirls reply page and build a resolved POST spec."""
    clean_thread_id = extract_thread_id(str(thread_id or "")) or ""
    if not clean_thread_id:
        raise ViperPostError("Thread ID is missing or invalid.")
    if not str(message or "").strip():
        raise ViperPostError("Post message is empty.")

    reply_url = f"{VIPERGIRLS_BASE_URL}/newreply.php?do=newreply&t={clean_thread_id}"
    soup = BeautifulSoup(html_text or "", "html.parser")
    form = None
    for candidate in soup.select("form"):
        action = str(candidate.get("action") or "")
        input_names = {
            str(element.get("name") or "")
            for element in candidate.select("input, textarea, select")
        }
        if ("newreply.php" in action and "do=postreply" in action) or {
            "message",
            "securitytoken",
            "do",
        }.issubset(input_names):
            form = candidate
            break

    if form is None:
        raise ViperPostError(_summarize_vipergirls_page(soup))

    form_fields = _copy_reply_form_fields(form)
    required_fields = {"securitytoken", "do", "t", "loggedinuser"}
    missing = sorted(name for name in required_fields if name not in form_fields)
    if missing:
        raise ViperPostError(
            "ViperGirls reply form is missing required field(s): " + ", ".join(missing)
        )

    form_fields["message"] = str(message)
    form_fields["message_backup"] = ""
    form_fields["wysiwyg"] = form_fields.get("wysiwyg", "0") or "0"
    form_fields["iconid"] = form_fields.get("iconid", "0") or "0"
    form_fields["do"] = "postreply"
    form_fields["t"] = clean_thread_id
    form_fields["sbutton"] = "Submit Reply"
    form_fields.setdefault("signature", "1")
    form_fields.setdefault("parseurl", "1")
    form_fields.setdefault("emailupdate", "0")
    form_fields.setdefault("folderid", "0")
    form_fields.pop("preview", None)

    action = str(form.get("action") or f"newreply.php?do=postreply&t={clean_thread_id}")
    post_url = urljoin(VIPERGIRLS_BASE_URL + "/", action)
    return {
        "url": post_url,
        "method": "POST",
        "use_cookies": True,
        "form_fields": form_fields,
        "headers": {
            "Referer": reply_url,
        },
        "include_response_body": True,
        "include_transport_metadata": True,
        # The post body and copied form values are final text; Go must not
        # treat "{...}" inside them as template tokens.
        "literal_values": True,
    }


def _is_vipergirls_login_page(body: str) -> bool:
    """True when the forum answered with its login form instead of content."""
    lowered = (body or "").lower()
    return "vb_login_username" in lowered and "logout.php" not in lowered


class ViperGirlsPostScheduler:
    """Python-owned scheduled-post runner for ViperGirls."""

    def __init__(
        self,
        creds: Union[Mapping[str, str], Callable[[], Mapping[str, str]]],
        event_queue: Optional[Any] = None,
    ):
        self.creds = creds
        self.event_queue = event_queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ViperGirlsPostScheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _emit(self, post: Dict[str, str], status: str, msg: str) -> None:
        if self.event_queue is None:
            return
        try:
            self.event_queue.put_nowait(
                {
                    "type": "scheduled_post_completed",
                    "id": post.get("id"),
                    "status": status,
                    "msg": msg,
                    "data": post,
                }
            )
        except Exception:
            logger.debug("Could not emit scheduled post event.", exc_info=True)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.process_due_posts()
            except Exception as exc:
                logger.warning(f"Scheduled ViperGirls post check failed: {exc}")
            self._stop_event.wait(60.0)

    def _credentials(self) -> Dict[str, str]:
        source = self.creds
        try:
            values = source() if callable(source) else source
        except Exception as exc:
            logger.error(f"Scheduled posts: could not read credentials: {exc}")
            values = {}
        return {str(key): str(value or "") for key, value in dict(values or {}).items()}

    def _fail_due_posts(self, due_posts: List[Dict[str, str]], error: str) -> None:
        for post in due_posts:
            failed_post = set_scheduled_post_status(post["id"], "failed", error)
            if failed_post is not None:
                self._emit(failed_post, "failed", error)

    def process_due_posts(self, now: Optional[datetime] = None) -> List[Dict[str, str]]:
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        due_posts = [
            post
            for post in load_scheduled_posts()
            if post.get("status") == "pending"
            and (scheduled_at := _parse_scheduled_time(post.get("scheduled_time", "")))
            and scheduled_at <= now_utc
        ]
        if not due_posts:
            return []

        credentials = self._credentials()
        user = credentials.get("vg_user", "")
        pwd = credentials.get("vg_pass", "")
        if not user or not pwd:
            self._fail_due_posts(due_posts, "Missing ViperGirls credentials.")
            return due_posts

        api = ViperGirlsAPI()
        if not api.login(user, pwd):
            self._fail_due_posts(due_posts, "ViperGirls login failed.")
            return due_posts

        for post in due_posts:
            try:
                ok = api.post_reply(post["thread_id"], post["message"])
                status = "posted" if ok else "failed"
                error = "" if ok else "ViperGirls post failed."
            except Exception as exc:
                status = "failed"
                error = str(exc)
            # Update only this record so posts added or cancelled meanwhile survive.
            updated_post = set_scheduled_post_status(post["id"], status, error)
            if updated_post is not None:
                self._emit(updated_post, status, error or "Post successful")

        return due_posts


# The sidecar has one shared cookie jar, and login() resets it. The AutoPoster
# and the scheduler each hold a ViperGirlsAPI; this lock keeps one client's
# login from landing between another client's reply-form fetch and submit.
_SESSION_LOCK = threading.RLock()


def _serialized_session(method):
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        with _SESSION_LOCK:
            return method(*args, **kwargs)

    return wrapper


class ViperGirlsAPI:
    def __init__(self):
        self.bridge = SidecarBridge.get()
        self._credentials: Optional[Tuple[str, str]] = None

    @_serialized_session
    def login(self, username, login_value):
        logger.info("ViperAPI: Logging in...")
        import hashlib

        # ViperGirls/vBulletin expects legacy MD5 login fields; this is not
        # used for local password storage or security decisions.
        legacy_md5 = getattr(hashlib, "md5")
        md5_pass = legacy_md5(login_value.encode(), usedforsecurity=False).hexdigest()

        # Start from an empty cookie jar so an older session cannot make a
        # wrong password look like a successful login.
        seed_spec = build_transport_spec(
            f"{VIPERGIRLS_BASE_URL}/login.php?do=login",
            method="GET",
            use_cookies=True,
            reset_cookies=True,
        )
        seed_resp = execute_transport_request(
            seed_spec,
            service="vipergirls.to",
            timeout=30,
            bridge=self.bridge,
            rate_limits=VIPERGIRLS_RATE_LIMIT,
        )
        if not seed_resp.ok:
            logger.error(f"ViperAPI: Login seed failed: {seed_resp.message}")
            return False

        spec = build_transport_spec(
            f"{VIPERGIRLS_BASE_URL}/login.php?do=login",
            method="POST",
            use_cookies=True,
            form_fields={
                "vb_login_username": username,
                "vb_login_md5password": md5_pass,
                "vb_login_md5password_utf": md5_pass,
                "cookieuser": "1",
                "do": "login",
                "securitytoken": "guest",
            },
            headers={"Referer": f"{VIPERGIRLS_BASE_URL}/forum.php"},
            literal_values=True,
        )
        resp = execute_transport_request(
            spec,
            service="vipergirls.to",
            timeout=30,
            bridge=self.bridge,
            rate_limits=VIPERGIRLS_RATE_LIMIT,
        )

        if resp.ok and _vipergirls_login_succeeded(resp.body, resp.final_url):
            self._credentials = (username, login_value)
            logger.info("ViperAPI: Login Successful")
            return True

        logger.error(f"ViperAPI: Login Failed: {resp.message or 'unexpected page'}")
        return False

    def _relogin(self) -> bool:
        """Re-establish the forum session once after it was lost mid-run."""
        if not self._credentials:
            return False
        logger.warning("ViperAPI: session lost; logging in again.")
        username, login_value = self._credentials
        return self.login(username, login_value)

    @_serialized_session
    def post_reply(self, thread_id, message):
        logger.info(f"ViperAPI: Posting to thread {thread_id}...")
        clean_thread_id = extract_thread_id(str(thread_id or "")) or ""
        if not clean_thread_id:
            logger.error("ViperAPI: Post Failed: invalid thread ID")
            return False

        reply_url = f"{VIPERGIRLS_BASE_URL}/newreply.php?do=newreply&t={clean_thread_id}"
        relogin_allowed = True
        while True:
            fetch_spec = build_transport_spec(
                reply_url,
                method="GET",
                headers={"Referer": f"{VIPERGIRLS_BASE_URL}/forum.php"},
                use_cookies=True,
            )
            fetch_resp = execute_transport_request(
                fetch_spec,
                service="vipergirls.to",
                timeout=30,
                bridge=self.bridge,
                rate_limits=VIPERGIRLS_RATE_LIMIT,
            )
            if not fetch_resp.ok:
                logger.error(f"ViperAPI: Reply form fetch failed: {fetch_resp.message}")
                return False
            if _is_vipergirls_login_page(fetch_resp.body):
                if relogin_allowed and self._relogin():
                    relogin_allowed = False
                    continue
                logger.error("ViperAPI: Post Failed: ViperGirls returned a login page.")
                return False

            try:
                post_spec = build_vipergirls_reply_spec(clean_thread_id, message, fetch_resp.body)
            except ViperPostError as exc:
                logger.error(f"ViperAPI: Post Failed: {exc}")
                return False

            # A reply must never be retried by the transport: a repeated POST
            # whose first attempt actually landed would post twice.
            resp = execute_transport_request(
                post_spec,
                service="vipergirls.to",
                timeout=60,
                bridge=self.bridge,
                rate_limits=VIPERGIRLS_RATE_LIMIT,
                retry=False,
            )

            if resp.ok and _vipergirls_post_succeeded(resp.body, resp.final_url):
                logger.info("ViperAPI: Post Successful")
                return True
            if resp.ok and _is_vipergirls_login_page(resp.body) and relogin_allowed:
                if self._relogin():
                    relogin_allowed = False
                    continue

            logger.error(f"ViperAPI: Post Failed: {resp.message or 'unexpected page'}")
            return False

    def schedule_post(
        self, post_id, thread_id, thread_name, message, scheduled_time, cover_thumbnail=""
    ):
        logger.info(f"ViperAPI: Scheduling post to thread {thread_id} for {scheduled_time}...")
        try:
            add_scheduled_post(
                {
                    "id": post_id,
                    "thread_id": str(thread_id),
                    "thread_name": thread_name,
                    "message": message,
                    "scheduled_time": scheduled_time,
                    "cover_thumbnail": cover_thumbnail,
                }
            )
            return True
        except ViperPostError as exc:
            logger.error(f"ViperAPI: Schedule failed: {exc}")
            return False

    def cancel_scheduled_post(self, post_id):
        logger.info(f"ViperAPI: Cancelling scheduled post {post_id}...")
        return cancel_scheduled_post(post_id)

    def list_scheduled_posts(self):
        return load_scheduled_posts()
