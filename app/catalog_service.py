from __future__ import annotations

import copy
import hashlib
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .disk_service import DiskError


DEFAULT_SOURCES = json.loads((Path(__file__).with_name("catalog_sources.json")).read_text("utf-8"))


@dataclass
class CachedPage:
    expires: float
    body: bytes


class CatalogueService:
    """Configurable, cached catalogue discovery with server-side download tokens."""

    def __init__(self, work_dir: Path):
        self.config_path = Path(work_dir) / "catalog-sources.json"
        self._pages: dict[str, CachedPage] = {}
        self._items: dict[str, tuple[float, dict]] = {}
        self._catalogues: dict[str, tuple[float, list[dict]]] = {}

    def sources(self) -> list[dict]:
        if not self.config_path.exists():
            return copy.deepcopy(DEFAULT_SOURCES)
        try:
            rows = json.loads(self.config_path.read_text("utf-8"))
            if not isinstance(rows, list):
                raise ValueError
            defaults_by_id = {row["id"]: row for row in DEFAULT_SOURCES}
            migrated = []
            for row in rows:
                default = defaults_by_id.get(str(row.get("id") or "")) if isinstance(row, dict) else None
                if default and row.get("type") not in {"configured", "links"}:
                    replacement = copy.deepcopy(default)
                    for key in ("name", "url", "machines", "enabled", "direct"):
                        replacement[key] = row.get(key, replacement[key])
                    replacement["options"] = _merge_settings(default.get("options", {}), row.get("options", {}))
                    migrated.append(replacement)
                else:
                    migrated.append(row)
            cleaned = [self._clean_source(row) for row in migrated]
            by_id = {row["id"]: row for row in cleaned}
            for default in DEFAULT_SOURCES:
                existing = by_id.get(default["id"])
                if existing and existing["type"] == default["type"]:
                    existing["options"] = _merge_settings(default.get("options", {}), existing.get("options", {}))
                elif existing:
                    replacement = copy.deepcopy(default)
                    for key in ("name", "url", "machines", "enabled", "direct"):
                        replacement[key] = existing.get(key, replacement[key])
                    replacement["options"] = _merge_settings(default.get("options", {}), existing.get("options", {}))
                    by_id[default["id"]] = replacement
                else:
                    by_id.setdefault(default["id"], copy.deepcopy(default))
            return list(by_id.values())
        except (OSError, ValueError, json.JSONDecodeError):
            return copy.deepcopy(DEFAULT_SOURCES)

    def save_sources(self, rows: list[dict]) -> list[dict]:
        if not isinstance(rows, list) or len(rows) > 30:
            raise DiskError("Online sources must be a list containing at most 30 sites.")
        cleaned = [self._clean_source(row) for row in rows]
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(cleaned, indent=2) + "\n", "utf-8")
        temporary.replace(self.config_path)
        self._pages.clear()
        return cleaned

    @staticmethod
    def _clean_source(row: dict) -> dict:
        if not isinstance(row, dict):
            raise DiskError("Each online source must be an object.")
        source_id = re.sub(r"[^a-z0-9_-]", "-", str(row.get("id") or row.get("name") or "source").lower())[:40]
        url = str(row.get("url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DiskError(f"{row.get('name') or source_id} needs an HTTP or HTTPS URL.")
        source_type = str(row.get("type") or "links")
        if source_type not in {"configured", "links"}:
            raise DiskError(f"Unsupported online source parser: {source_type}")
        return {
            "id": source_id or "source", "name": str(row.get("name") or source_id)[:100],
            "type": source_type, "url": url, "machines": [str(item)[:30] for item in row.get("machines", [])][:12],
            "enabled": bool(row.get("enabled", True)), "direct": bool(row.get("direct", source_type != "links")),
            "options": dict(row.get("options") or {}) if isinstance(row.get("options") or {}, dict) else {},
        }

    def _fetch(self, url: str, *, limit: int = 32 * 1024 * 1024, ttl: int = 900) -> bytes:
        cached = self._pages.get(url)
        if cached and cached.expires > time.time():
            return cached.body
        request = urllib.request.Request(url, headers={"User-Agent": "AcornFileForge/1.0 (+local archival tool)", "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                length = int(response.headers.get("Content-Length") or 0)
                if length > limit:
                    raise DiskError(f"The remote file is larger than the {limit // (1024 * 1024)} MB safety limit.")
                body = response.read(limit + 1)
        except DiskError:
            raise
        except Exception as exc:
            raise DiskError(f"Could not contact {urllib.parse.urlparse(url).netloc}: {exc}") from exc
        if len(body) > limit:
            raise DiskError(f"The remote file is larger than the {limit // (1024 * 1024)} MB safety limit.")
        self._pages[url] = CachedPage(time.time() + ttl, body)
        return body

    def search(self, query: str, machine: str, source_ids: set[str] | None = None) -> tuple[list[dict], list[dict]]:
        query = query.strip().casefold()
        results, failures = [], []
        sources = [
            source for source in self.sources()
            if source["enabled"]
            and (not source_ids or source["id"] in source_ids)
            and (not machine or machine == "all" or machine in source["machines"] or "all" in source["machines"])
        ]

        def load(source):
            try:
                return source, self._load_catalogue(source, query, machine), None
            except (DiskError, OSError, ValueError) as exc:
                return source, [], str(exc)

        with ThreadPoolExecutor(max_workers=min(6, len(sources) or 1)) as pool:
            loaded = list(pool.map(load, sources))
        for source, rows, error in loaded:
            if error:
                failures.append({"source": source["name"], "error": error})
                continue
            candidates = []
            for row in rows:
                haystack = " ".join(str(row.get(key, "")) for key in ("title", "publisher", "description", "year")).casefold()
                if query and query not in haystack:
                    continue
                if not row.get("downloadable"):
                    continue
                candidates.append(row)
            if any(row.get("resolver") for row in candidates):
                # Some indexes contain thousands of records but do not promise
                # downloadable media. Resolve only a bounded result window.
                candidates = candidates[:max(1, int(source["options"].get("resultValidationLimit", 120)))]
                threads = max(1, min(16, int(source["options"].get("detailThreads", 8))))
                with ThreadPoolExecutor(max_workers=min(threads, len(candidates) or 1)) as pool:
                    candidates = [
                        row for row in pool.map(lambda item: self._resolve_row(item) if item.get("resolver") else item, candidates)
                        if row
                    ]
            for row in candidates:
                row.update(sourceId=source["id"], sourceName=source["name"], machines=row.get("machines") or source["machines"])
                token = hashlib.sha256(f"{source['id']}\0{row.get('downloadUrl')}\0{row.get('pageUrl')}\0{row.get('title')}".encode()).hexdigest()[:32]
                row["id"] = token
                self._items[token] = (time.time() + 3600, dict(row))
                row.pop("downloadUrl", None)
                results.append(row)
        results.sort(key=lambda item: (str(item.get("title", "")).casefold(), str(item.get("publisher", "")).casefold()))
        return results[:1000], failures

    def _load_catalogue(self, source: dict, query: str, machine: str) -> list[dict]:
        options = source.get("options", {})
        loader_name = str(options.get("loader") or "page")
        loaders = {
            "page": self._load_page,
            "category-crawl": self._load_category_crawl,
            "machine-index": self._load_machine_index,
        }
        loader = loaders.get(loader_name)
        if loader is None:
            raise DiskError(f"Unsupported catalogue loading strategy: {loader_name}")
        return loader(source, query, machine)

    def _load_page(self, source: dict, query: str, _machine: str) -> list[dict]:
        options = source.get("options", {})
        url = source["url"]
        template = str(options.get("queryTemplate") or "")
        if query and template:
            url = urllib.parse.urljoin(url, template.replace("{query}", urllib.parse.quote_plus(query)))
        body = self._fetch(
            url,
            limit=max(1, int(options.get("pageLimitMb", 8))) * 1024 * 1024,
            ttl=max(60, int(options.get("cacheSeconds", 900))),
        ).decode(str(options.get("encoding") or "utf-8"), "replace")
        return self._parse_rows(source, body, str(options.get("parser") or "links"), {"url": url})

    def _parse_rows(self, source: dict, body: str, parser_name: str, context: dict | None = None) -> list[dict]:
        parsers = {
            "thumbnail-cards": self._parse_thumbnail_cards,
            "section-catalogue": self._parse_section_catalogue,
            "function-calls": self._parse_function_calls,
            "item-rows": self._parse_item_rows,
            "zip-links": self._parse_zip_links,
            "package-paragraphs": self._parse_package_paragraphs,
            "links": self._parse_links,
        }
        parser = parsers.get(parser_name)
        if parser is None:
            raise DiskError(f"Unsupported catalogue parser: {parser_name}")
        return parser(source, body, context or {})

    def _resolve_row(self, row: dict) -> dict | None:
        try:
            body = self._fetch(row["pageUrl"], limit=2 * 1024 * 1024, ttl=86400).decode("utf-8", "replace")
        except DiskError:
            return None
        choices = [
            urllib.parse.urljoin(row["pageUrl"], href)
            for href in re.findall(r'href\s*=\s*["\']([^"\']+)', body, re.I)
            if re.search(r'\.(?:zip|uef|ssd|dsd|adf|hfe)(?:$|[?#])', href, re.I)
            and str(row.get("resolverOptions", {}).get("downloadPathContains") or "/download/").casefold()
            in urllib.parse.urlparse(urllib.parse.urljoin(row["pageUrl"], href)).path.casefold()
        ]
        if not choices:
            return None
        resolved = dict(row)
        resolved["downloadUrl"] = choices[0]
        resolved["downloadChoices"] = list(dict.fromkeys(choices))
        resolved["artifactType"] = "disk-image"
        resolved["description"] = resolved["description"].replace(" Download availability is checked when installed.", "")
        return resolved

    def _load_category_crawl(self, source: dict, _query: str, _machine: str) -> list[dict]:
        cached = self._catalogues.get(source["id"])
        if cached and cached[0] > time.time():
            return [dict(row) for row in cached[1]]
        options = source["options"]
        cache_seconds = max(60, int(options.get("cacheSeconds", 86400)))
        categories = [dict(category) for category in options.get("categories", []) if isinstance(category, dict)]

        def category_pages(category):
            label = str(category.get("name") or "Electron software")
            root_url = urllib.parse.urljoin(source["url"], str(category.get("url") or ""))
            required_path = str(category.get("childPath") or "")
            if not required_path:
                return [(label, root_url, str(category.get("parser") or options.get("parser") or "links"))]
            try:
                body = self._fetch(root_url, limit=2 * 1024 * 1024, ttl=cache_seconds).decode("latin-1", "replace")
            except DiskError:
                return []
            links = {
                urllib.parse.urljoin(root_url, href)
                for href in re.findall(r'href\s*=\s*["\']([^"\']+)', body, re.I)
                if required_path in urllib.parse.urljoin(root_url, href)
                and urllib.parse.urlparse(urllib.parse.urljoin(root_url, href)).path.lower().endswith(".html")
            }
            return [(label, url, str(category.get("parser") or options.get("parser") or "links")) for url in links]

        pages = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for found in pool.map(category_pages, categories):
                pages.extend(found)

        def parse_page(page):
            category, url, parser = page
            try:
                body = self._fetch(url, limit=2 * 1024 * 1024, ttl=cache_seconds).decode("latin-1", "replace")
            except DiskError:
                return []
            return self._parse_rows(source, body, parser, {"url": url, "category": category})

        rows = []
        crawl_threads = max(1, min(16, int(options.get("crawlThreads", 8))))
        with ThreadPoolExecutor(max_workers=crawl_threads) as pool:
            for found in pool.map(parse_page, sorted(set(pages))):
                rows.extend(found)
        unique = {}
        for row in rows:
            key = (row["pageUrl"].casefold(), row["title"].casefold())
            unique[key] = row
        catalogue = list(unique.values())
        self._catalogues[source["id"]] = (time.time() + cache_seconds, catalogue)
        return [dict(row) for row in catalogue]

    @staticmethod
    def _parse_section_catalogue(source: dict, body: str, context: dict) -> list[dict]:
        url = str(context.get("url") or source["url"])
        category = str(context.get("category") or source["name"])
        publisher_match = re.search(r'id\s*=\s*["\']cat_table_title_bar["\'][^>]*>(.*?)</h6>', body, re.I | re.S)
        publisher = _plain_text(publisher_match.group(1)) if publisher_match else str(source.get("name") or "")
        rows = []
        sections = re.findall(r'<section\s+id\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</section>', body, re.I | re.S)
        for section_id, block in sections:
            title_match = re.search(r'<b>(.*?)</b>', block, re.I | re.S)
            if not title_match:
                continue
            title = _plain_text(title_match.group(1))
            if not title:
                continue
            date_match = re.search(r'Release Date:\s*<br\s*/?>\s*([^<]+)', block, re.I)
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', date_match.group(1) if date_match else "")
            compatibility = re.search(r'Stated Compatibility:\s*<br\s*/?>\s*(.*?)\s*<br', block, re.I | re.S)
            media = [
                urllib.parse.urljoin(url, href)
                for href in re.findall(r'href\s*=\s*["\']([^"\']+)', block, re.I)
                if re.search(r'\.(?:zip|uef|ssd|dsd|adf|hfe)(?:$|[?#])', href, re.I)
            ]
            download = media[0] if media else None
            description = category
            if compatibility:
                description += f". {_plain_text(compatibility.group(1))}"
            rows.append(_item(
                title, publisher, year_match.group(1) if year_match else "", download,
                f"{url}#{urllib.parse.quote(section_id)}", "disk-image" if download else "external",
                description=description, machines=source.get("machines", []), downloadable=bool(download),
            ))
        if rows:
            return rows
        downloads = [
            urllib.parse.urljoin(url, href)
            for href in re.findall(r'href\s*=\s*["\']([^"\']+)', body, re.I)
            if re.search(r'\.(?:zip|uef|ssd|dsd|adf|hfe)(?:$|[?#])', href, re.I)
        ]
        if not downloads:
            return []
        title_match = re.search(r'<title>(.*?)</title>', body, re.I | re.S)
        title = _plain_text(title_match.group(1)).split(" - ")[0] if title_match else Path(urllib.parse.urlparse(url).path).stem
        return [_item(title, publisher, "", downloads[0], url, "disk-image", description=category, machines=["electron"])]

    def _load_machine_index(self, source: dict, _query: str, machine: str) -> list[dict]:
        options = source["options"]
        profiles = options.get("machineProfiles", {})
        selected_profile_items = list(profiles.items()) if machine == "all" else [(machine, profiles.get(machine, {}))]
        machine_ids = list(dict.fromkeys(
            int(machine_id)
            for _machine_name, profile in selected_profile_items if isinstance(profile, dict)
            for machine_id in profile.get("ids", [])
        ))
        if not machine_ids:
            return []
        profile_by_id = {
            int(machine_id): {"label": str(profile.get("label") or machine_name), "machines": [machine_name]}
            for machine_name, profile in selected_profile_items if isinstance(profile, dict)
            for machine_id in profile.get("ids", [])
        }
        cache_key = f"{source['id']}:{','.join(map(str, machine_ids))}"
        cached = self._catalogues.get(cache_key)
        if cached and cached[0] > time.time():
            return [dict(row) for row in cached[1]]

        def load_machine(machine_id):
            template = str(options.get("landingTemplate") or "")
            url = urllib.parse.urljoin(source["url"], template.replace("{machineId}", str(machine_id)))
            cache_seconds = max(60, int(options.get("cacheSeconds", 86400)))
            body = self._fetch(url, limit=8 * 1024 * 1024, ttl=cache_seconds).decode("utf-8", "replace")
            return self._parse_rows(
                source,
                body,
                str(options.get("parser") or "links"),
                {"url": url, "profile": profile_by_id.get(machine_id, {})},
            )

        rows = []
        with ThreadPoolExecutor(max_workers=min(4, len(machine_ids))) as pool:
            for found in pool.map(load_machine, machine_ids):
                rows.extend(found)
        unique = {(row["pageUrl"], row["title"]): row for row in rows}
        catalogue = list(unique.values())
        self._catalogues[cache_key] = (time.time() + max(60, int(options.get("cacheSeconds", 86400))), catalogue)
        return [dict(row) for row in catalogue]

    @staticmethod
    def _parse_item_rows(source: dict, body: str, context: dict) -> list[dict]:
        profile = context.get("profile", {})
        rows = []
        item_path = str(source.get("options", {}).get("itemPathPrefix") or "/litem/")
        pattern = re.compile(
            r'<a\s+href\s*=\s*["\'](' + re.escape(item_path) + r'[^"\']+)["\'][^>]*>(.*?)</a>(.*?)</td>',
            re.I | re.S,
        )
        for href, label, tail in pattern.findall(body):
            title = _plain_text(label)
            if not title:
                continue
            details = _plain_text(tail)
            groups = re.findall(r'\(([^()]*)\)', details)
            publisher = groups[1] if len(groups) > 1 else ""
            year = next(iter(re.findall(r'\b(?:19|20)\d{2}\b', details)), "")
            page_url = urllib.parse.urljoin(source["url"], href)
            rows.append(_item(
                title, publisher, year, None, page_url, "remote-item",
                description=f"{profile.get('label', 'Acorn software')}. Download availability is checked when installed.",
                machines=profile.get("machines", []), downloadable=True,
                resolver=str(source.get("options", {}).get("resolver") or "media-links"),
            ))
            rows[-1]["resolverOptions"] = {"downloadPathContains": source["options"].get("downloadPathContains", "/download/")}
        return rows

    @staticmethod
    def _parse_thumbnail_cards(source: dict, body: str, _context: dict) -> list[dict]:
        rows = []
        pattern = re.compile(r'<div class="thumbnail[^>]*>(.*?)</div>\s*</div>', re.I | re.S)
        for block in pattern.findall(body):
            title = re.search(r'class="row-title".*?<a[^>]*>([^<]+)</a>', block, re.I | re.S)
            download = re.search(r'href="([^"]+\.(?:ssd|dsd|zip))"', block, re.I)
            if not title or not download:
                continue
            publisher = re.search(r'class="row-pub"[^>]*>.*?<a[^>]*>([^<]+)', block, re.I | re.S)
            year = re.search(r'class="row-dt"[^>]*>.*?<a[^>]*>([^<]+)', block, re.I | re.S)
            page = re.search(r'href="(game\.php\?id=\d+)"', block, re.I)
            rows.append(_item(title.group(1), publisher.group(1) if publisher else "", year.group(1) if year else "", urllib.parse.urljoin(source["url"], download.group(1)), urllib.parse.urljoin(source["url"], page.group(1)) if page else source["url"], "disk-image"))
        return rows

    @staticmethod
    def _parse_function_calls(source: dict, body: str, context: dict) -> list[dict]:
        rows = []
        options = source.get("options", {})
        call_name = re.escape(str(options.get("callName") or "record"))
        fields = options.get("callFields", {})
        for call in re.findall(call_name + r'\((.*?)\);', body, re.I | re.S):
            values = [html.unescape(single or double) for double, single in re.findall(r'"((?:\\.|[^"])*)"|\'((?:\\.|[^\'])*)\'', call)]
            indexes = [int(fields.get(key, default)) for key, default in (("publisher", 0), ("stem", 3), ("title", 4), ("description", 7))]
            if len(values) <= max(indexes):
                continue
            publisher, stem, title, summary = (values[index] for index in indexes)
            template = str(options.get("downloadTemplate") or "")
            download = template.replace("{publisher}", urllib.parse.quote(publisher)).replace("{stem}", urllib.parse.quote(stem)) if template else None
            description = f"{context.get('category', '')}. {summary}".strip(". ")
            rows.append(_item(title, publisher.replace("_", " "), "", download, str(context.get("url") or source["url"]), "disk-image", description=description, machines=source.get("machines", [])))
        return rows

    @staticmethod
    def _parse_zip_links(source: dict, body: str, _context: dict) -> list[dict]:
        pattern = re.compile(r'<a\s+href=["\']?([^"\'> ]+\.zip)["\']?[^>]*>([^<]+)</a>\s*(?:<b>([^<]*)</b>)?', re.I)
        publisher = str(source.get("options", {}).get("defaultPublisher") or source.get("name") or "")
        return [_item((title or code).strip(), publisher, "", urllib.parse.urljoin(source["url"], url), source["url"], "disk-image", description=code.strip()) for url, code, title in pattern.findall(body)]

    @staticmethod
    def _parse_package_paragraphs(source: dict, body: str, _context: dict) -> list[dict]:
        rows = []
        for paragraph in re.split(r"\r?\n\r?\n", body):
            fields = {}
            for line in paragraph.splitlines():
                if ": " in line:
                    key, value = line.split(": ", 1); fields[key] = value
            if not fields.get("Package") or not fields.get("URL"):
                continue
            rows.append(_item(fields.get("Package"), fields.get("Maintainer", ""), "", urllib.parse.urljoin(source["url"], fields["URL"]), source["url"], "riscos-package", description=fields.get("Description", ""), machines=source.get("machines", []), version=fields.get("Version", "")))
        return rows

    @staticmethod
    def _parse_links(source: dict, body: str, _context: dict) -> list[dict]:
        rows, seen = [], set()
        for href, title in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', body, re.I | re.S):
            clean = re.sub(r"<[^>]+>", " ", title); clean = html.unescape(re.sub(r"\s+", " ", clean)).strip()
            if len(clean) < 2 or href in seen:
                continue
            seen.add(href); rows.append(_item(clean, "", "", None, href, "external", downloadable=False))
        return rows[:300]

    def item(self, token: str) -> dict:
        cached = self._items.get(token)
        if not cached or cached[0] < time.time():
            raise DiskError("That online catalogue result has expired. Search again before installing it.")
        return dict(cached[1])

    def download(self, token: str, preferred: str = "dfs") -> tuple[str, bytes, dict]:
        item = self.item(token)
        choices = item.get("downloadChoices") or [item.get("downloadUrl")]
        choices = [url for url in choices if url]
        def score(url):
            lowered = urllib.parse.urlparse(url).path.casefold()
            dfs_hint = any(hint in lowered for hint in ("/dfs/", "5_25", ".ssd", ".dsd"))
            adfs_hint = any(hint in lowered for hint in ("/adfs/", "3_5", ".adf"))
            return (adfs_hint if preferred == "adfs" else dfs_hint, not (dfs_hint or adfs_hint))
        url = max(choices, key=score) if choices else None
        if not item.get("downloadable", True) or not url:
            raise DiskError("This catalogue item links to its publisher page and cannot be installed automatically.")
        name = Path(urllib.parse.urlparse(url).path).name or f"{item['title']}.zip"
        return name, self._fetch(url, ttl=60, limit=128 * 1024 * 1024), item


def _item(title, publisher, year, download, page, artifact, *, description="", machines=None, downloadable=True, version="", resolver=None):
    return {"title": html.unescape(str(title)).strip(), "publisher": html.unescape(str(publisher)).strip(), "year": str(year).strip(), "description": html.unescape(str(description)).strip(), "downloadUrl": download, "pageUrl": page, "artifactType": artifact, "downloadable": bool(downloadable and (download or resolver)), "machines": machines or [], "version": version, "resolver": resolver}


def _plain_text(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value)))).strip()


def _merge_settings(defaults: dict, configured: dict) -> dict:
    """Add newly supported settings without replacing a user's configured values."""
    merged = copy.deepcopy(defaults)
    for key, value in configured.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_settings(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def archive_members(name: str, data: bytes) -> list[tuple[str, bytes]]:
    if not name.lower().endswith(".zip") and not data.startswith(b"PK"):
        return [(name, data)]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = []
            total = 0
            for info in archive.infolist():
                if info.is_dir() or info.filename.startswith(("/", "\\")) or ".." in Path(info.filename).parts:
                    continue
                total += info.file_size
                if total > 256 * 1024 * 1024:
                    raise DiskError("The ZIP expands beyond the 256 MB safety limit.")
                members.append((info.filename, archive.read(info)))
            return members
    except zipfile.BadZipFile as exc:
        raise DiskError("The downloaded ZIP file is damaged or incomplete.") from exc
