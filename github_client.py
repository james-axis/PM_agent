"""
PM Agent — GitHub Client
Pushes prototype HTML files to the prototypes repo via GitHub API.
"""

import os
import base64
import requests
from config import log

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PROTOTYPES_REPO = "james-axis/prototypes"
GITHUB_API = "https://api.github.com"


def push_prototype(filename, html_content, commit_message=None):
    """
    Push an HTML file to the prototypes repo.
    Returns the public GitHub Pages URL on success, None on failure.

    Uses GitHub Contents API: PUT /repos/{owner}/{repo}/contents/{path}
    """
    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN not set — cannot push prototype")
        return None

    path = filename  # e.g., "AR-123.html"
    url = f"{GITHUB_API}/repos/{PROTOTYPES_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Check if file already exists (need SHA to update)
    sha = None
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    # Create or update
    payload = {
        "message": commit_message or f"Add prototype: {filename}",
        "content": base64.b64encode(html_content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
        payload["message"] = commit_message or f"Update prototype: {filename}"

    try:
        r = requests.put(url, headers=headers, json=payload, timeout=30)
        if r.status_code in (200, 201):
            pages_url = f"https://james-axis.github.io/prototypes/{filename}"
            log.info(f"Pushed prototype: {pages_url}")
            return pages_url
        log.error(f"GitHub push failed: {r.status_code} {r.text[:500]}")
    except Exception as e:
        log.error(f"GitHub push error: {e}")

    return None


def fetch_prototype_html(issue_key):
    """
    Fetch the HTML content of a prototype file from the repo.
    Returns HTML string or None.
    """
    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN not set — cannot fetch prototype")
        return None

    filename = f"{issue_key.lower()}.html"
    url = f"{GITHUB_API}/repos/{PROTOTYPES_REPO}/contents/{filename}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            content_b64 = r.json().get("content", "")
            return base64.b64decode(content_b64).decode("utf-8")
        log.error(f"GitHub fetch failed for {filename}: {r.status_code}")
    except Exception as e:
        log.error(f"GitHub fetch error for {filename}: {e}")

    return None
