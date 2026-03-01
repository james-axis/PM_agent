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
CODEBASE_REPO = os.getenv("CODEBASE_REPO", "james-axis/axis-crm")  # Main CRM codebase
GITHUB_API = "https://api.github.com"

_gh_headers = None

def _get_headers():
    global _gh_headers
    if _gh_headers is None:
        _gh_headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    return _gh_headers


# ── Codebase Exploration ─────────────────────────────────────────────────────

def list_repo_tree(repo=None, path="", depth=2):
    """
    List directory contents recursively up to a given depth.
    Returns list of {path, type, size} dicts.
    """
    repo = repo or CODEBASE_REPO
    if not GITHUB_TOKEN:
        return []

    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    try:
        r = requests.get(url, headers=_get_headers(), timeout=15)
        if r.status_code != 200:
            log.warning(f"GitHub list failed for {repo}/{path}: {r.status_code}")
            return []

        items = []
        for entry in r.json():
            items.append({
                "path": entry["path"],
                "type": entry["type"],  # "file" or "dir"
                "size": entry.get("size", 0),
            })
            # Recurse into directories (up to depth)
            if entry["type"] == "dir" and depth > 1:
                items.extend(list_repo_tree(repo, entry["path"], depth - 1))

        return items
    except Exception as e:
        log.error(f"GitHub tree error for {repo}/{path}: {e}")
        return []


def read_file_content(filepath, repo=None, max_size=50000):
    """
    Read a single file from a GitHub repo. Returns text content or None.
    Skips files larger than max_size bytes.
    """
    repo = repo or CODEBASE_REPO
    if not GITHUB_TOKEN:
        return None

    url = f"{GITHUB_API}/repos/{repo}/contents/{filepath}"
    try:
        r = requests.get(url, headers=_get_headers(), timeout=15)
        if r.status_code != 200:
            return None

        data = r.json()
        size = data.get("size", 0)
        if size > max_size:
            log.warning(f"Skipping {filepath}: {size} bytes exceeds max {max_size}")
            return f"(File too large: {size} bytes)"

        content_b64 = data.get("content", "")
        return base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except Exception as e:
        log.error(f"GitHub read error for {filepath}: {e}")
        return None


def search_code(query, repo=None, max_results=10):
    """
    Search for code in a repo using GitHub Code Search.
    Returns list of {path, snippet} dicts.
    """
    repo = repo or CODEBASE_REPO
    if not GITHUB_TOKEN:
        return []

    url = f"{GITHUB_API}/search/code"
    params = {"q": f"{query} repo:{repo}", "per_page": max_results}
    try:
        r = requests.get(url, headers=_get_headers(), params=params, timeout=15)
        if r.status_code != 200:
            log.warning(f"GitHub search failed: {r.status_code}")
            return []

        return [
            {"path": item["path"], "name": item["name"]}
            for item in r.json().get("items", [])
        ]
    except Exception as e:
        log.error(f"GitHub search error: {e}")
        return []


def get_repo_structure(repo=None):
    """
    Get a high-level directory structure (top 2 levels) as a formatted string.
    Cached for repeated calls within one session.
    """
    items = list_repo_tree(repo, "", depth=2)
    if not items:
        return "(Codebase structure unavailable)"

    lines = []
    for item in items:
        prefix = "📁" if item["type"] == "dir" else "📄"
        lines.append(f"  {prefix} {item['path']}")

    return "\n".join(lines[:100])  # Cap at 100 entries


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
