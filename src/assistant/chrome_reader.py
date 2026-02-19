"""
Chrome reader module for reading content from existing Chrome browser.
Connects to Chrome via CDP (Chrome DevTools Protocol) remote debugging.
Can auto-launch Chrome with remote debugging.
"""

import subprocess
import time
from typing import Optional

from src.utils import get_logger

logger = get_logger(__name__)

CHROME_CDP_PORT = 9222
CHROME_USER_DATA_DIR = None  # Set to a custom profile path if needed

try:
    from playwright.sync_api import sync_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("playwright not installed. Chrome reading will not be available.")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


TAX_SOFTWARE_DOMAINS = [
    "taxact",
    "turbotax",
    "hrblock",
    "taxslayer",
    "credit karma tax",
    "freefilefillableforms",
    "secureefile",
    "104.com",
    "taxwise",
    "atx",
]


def detect_tax_software_type(url: str, title: str) -> str:
    """Detect which tax software is being used based on URL/title."""
    url_lower = url.lower()
    title_lower = title.lower()
    
    if "taxact" in url_lower or "taxact" in title_lower:
        return "TaxAct"
    elif "turbotax" in url_lower or "turbotax" in title_lower:
        return "TurboTax"
    elif "hrblock" in url_lower or "h&r block" in title_lower or "hrblock" in title_lower:
        return "H&R Block"
    elif "taxslayer" in url_lower or "taxslayer" in title_lower:
        return "TaxSlayer"
    elif "credit karma" in url_lower or "creditkarma" in url_lower:
        return "Credit Karma Tax"
    else:
        return "Tax Software"


def is_chrome_running() -> bool:
    """Check if Chrome is running with remote debugging."""
    if not REQUESTS_AVAILABLE:
        return False
    
    try:
        response = requests.get(
            f"http://localhost:{CHROME_CDP_PORT}/json",
            timeout=2
        )
        return response.status_code == 200
    except Exception:
        return False


def launch_chrome_with_debugging(user_data_dir: str = None) -> bool:
    """
    Launch Chrome with remote debugging enabled.
    
    Args:
        user_data_dir: Optional Chrome profile directory
        
    Returns:
        True if Chrome was launched successfully
    """
    import sys
    import os
    
    # Find Chrome executable
    chrome_paths = []
    
    if sys.platform == "win32":
        # Windows paths
        chrome_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ]
    elif sys.platform == "darwin":
        # macOS paths
        chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expand.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:
        # Linux paths
        chrome_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/chrome",
            "/opt/google/chrome/chrome",
        ]
    
    chrome_exe = None
    for path in chrome_paths:
        if os.path.exists(path):
            chrome_exe = path
            break
    
    if not chrome_exe:
        logger.warning("Chrome executable not found")
        return False
    
    # Build Chrome command
    cmd = [
        chrome_exe,
        f"--remote-debugging-port={CHROME_CDP_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    
    if user_data_dir:
        cmd.append(f"--user-data-dir={user_data_dir}")
    else:
        # Use a temporary profile to avoid conflicts
        import tempfile
        temp_profile = tempfile.mkdtemp(prefix="tax_assistant_")
        cmd.append(f"--user-data-dir={temp_profile}")
    
    try:
        # Start Chrome
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait for Chrome to be ready
        for _ in range(10):
            time.sleep(1)
            if is_chrome_running():
                logger.info("Chrome launched with remote debugging")
                return True
        
        logger.warning("Chrome launched but debugging port not ready")
        return False
        
    except Exception as e:
        logger.error(f"Failed to launch Chrome: {e}")
        return False


def ensure_chrome_running(console=None) -> bool:
    """
    Ensure Chrome is running with remote debugging.
    Launches Chrome if not already running.
    
    Args:
        console: Optional console for status output
        
    Returns:
        True if Chrome is available
    """
    if is_chrome_running():
        return True
    
    if console:
        console.print("[blue]Launching Chrome with remote debugging...[/blue]")
    
    success = launch_chrome_with_debugging()
    
    if success:
        if console:
            console.print("[green]Chrome launched successfully![/green]")
            console.print("[yellow]Please sign into your tax software (TaxAct, TurboTax, etc.)[/yellow]")
    else:
        if console:
            console.print("[red]Failed to launch Chrome[/red]")
    
    return success


def get_chrome_tabs() -> list[dict]:
    """Get list of open Chrome tabs."""
    if not REQUESTS_AVAILABLE:
        return []
    
    try:
        response = requests.get(
            f"http://localhost:{CHROME_CDP_PORT}/json",
            timeout=2
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.debug(f"Could not connect to Chrome: {e}")
    
    return []


def find_tax_software_tabs() -> list[dict]:
    """Find tabs that appear to be tax software pages."""
    tabs = get_chrome_tabs()
    tax_tabs = []
    
    for tab in tabs:
        url = tab.get("url", "").lower()
        title = tab.get("title", "").lower()
        
        for domain in TAX_SOFTWARE_DOMAINS:
            if domain in url or domain in title:
                tax_tabs.append(tab)
                break
    
    return tax_tabs


class ChromeReader:
    """
    Read content from existing Chrome browser tabs.
    Connects via CDP (Chrome DevTools Protocol).
    """
    
    def __init__(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright not installed. Run: pip install playwright")
        
        self._playwright = None
        self._browser = None
        self._connected = False
    
    def connect(self) -> bool:
        """Connect to existing Chrome browser."""
        if self._connected:
            return True
        
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                f"http://localhost:{CHROME_CDP_PORT}"
            )
            self._connected = True
            return True
        except Exception as e:
            logger.debug(f"Failed to connect to Chrome: {e}")
            if self._playwright:
                try:
                    self._playwright.stop()
                except:
                    pass
                self._playwright = None
            return False
    
    def disconnect(self) -> None:
        """Disconnect from Chrome."""
        if self._browser:
            try:
                self._browser.close()
            except:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except:
                pass
            self._playwright = None
        self._connected = False
    
    def get_all_tabs(self) -> list[dict]:
        """Get all open tabs with their content."""
        if not self._connected and not self.connect():
            return []
        
        tabs = []
        for context in self._browser.contexts:
            for page in context.pages:
                try:
                    tabs.append({
                        "url": page.url,
                        "title": page.title(),
                        "page": page,
                    })
                except Exception:
                    pass
        
        return tabs
    
    def get_tax_software_tabs(self) -> list[dict]:
        """Get tabs that appear to be tax software."""
        all_tabs = self.get_all_tabs()
        tax_tabs = []
        
        for tab in all_tabs:
            url = tab.get("url", "").lower()
            title = tab.get("title", "").lower()
            
            for domain in TAX_SOFTWARE_DOMAINS:
                if domain in url or domain in title:
                    tax_tabs.append(tab)
                    break
        
        return tax_tabs
    
    def read_page_content(self, page: Page) -> str:
        """Extract readable content from a page."""
        try:
            content_parts = []
            
            # Get page title
            title = page.title()
            if title:
                content_parts.append(f"Page Title: {title}")
            
            # Get visible text
            try:
                visible_text = page.evaluate("""
                    () => {
                        const walker = document.createTreeWalker(
                            document.body,
                            NodeFilter.SHOW_TEXT,
                            null,
                            false
                        );
                        let text = '';
                        let node;
                        while (node = walker.nextNode()) {
                            const parent = node.parentElement;
                            if (parent && 
                                getComputedStyle(parent).display !== 'none' &&
                                getComputedStyle(parent).visibility !== 'hidden' &&
                                parent.tagName !== 'SCRIPT' &&
                                parent.tagName !== 'STYLE' &&
                                parent.tagName !== 'NOSCRIPT') {
                                text += node.textContent + ' ';
                            }
                        }
                        return text.replace(/\\s+/g, ' ').trim();
                    }
                """)
                if visible_text:
                    content_parts.append(f"Page Content:\n{visible_text}")
            except Exception as e:
                logger.debug(f"Could not get visible text: {e}")
            
            # Get form values
            try:
                form_data = page.evaluate("""
                    () => {
                        const data = {};
                        const inputs = document.querySelectorAll('input, select, textarea');
                        inputs.forEach(input => {
                            if (input.name || input.id) {
                                const label = document.querySelector(`label[for="${input.id}"]`) 
                                           || input.closest('label')
                                           || input.previousElementSibling;
                                const labelText = label ? label.textContent.trim() : '';
                                data[input.name || input.id] = {
                                    value: input.value,
                                    type: input.type,
                                    label: labelText
                                };
                            }
                        });
                        return data;
                    }
                """)
                
                if form_data:
                    form_lines = ["Form Values:"]
                    for name, info in list(form_data.items())[:20]:
                        if info.get('value'):
                            label = info.get('label', name)
                            form_lines.append(f"  {label}: {info.get('value')}")
                    if len(form_lines) > 1:
                        content_parts.append("\n".join(form_lines))
            except Exception as e:
                logger.debug(f"Could not get form data: {e}")
            
            return "\n\n".join(content_parts)
        
        except Exception as e:
            logger.error(f"Error reading page content: {e}")
            return f"Error reading page: {e}"
    
    def read_tax_software_content(self) -> Optional[str]:
        """Read content from tax software tabs if available."""
        if not self._connected and not self.connect():
            return None
        
        tax_tabs = self.get_tax_software_tabs()
        
        if not tax_tabs:
            return None
        
        contents = []
        for tab in tax_tabs[:3]:
            page = tab.get("page")
            if page:
                content = self.read_page_content(page)
                if content:
                    contents.append(content)
        
        if contents:
            return "\n\n---\n\n".join(contents)
        
        return None
    
    def read_active_tab_content(self) -> Optional[str]:
        """Read content from the active/foreground tab."""
        if not self._connected and not self.connect():
            return None
        
        try:
            for context in self._browser.contexts:
                for page in context.pages:
                    if page.url and not page.url.startswith("chrome"):
                        return self.read_page_content(page)
        except Exception as e:
            logger.debug(f"Could not read active tab: {e}")
        
        return None
    
    def get_tax_page_snapshot(self) -> Optional[dict]:
        """
        Get a snapshot of the current tax software page.
        Returns structured data for change detection and comparison.
        """
        if not self._connected and not self.connect():
            return None
        
        try:
            tax_tabs = self.get_tax_software_tabs()
            
            if not tax_tabs:
                return None
            
            tab = tax_tabs[0]
            page = tab.get("page")
            
            if not page:
                return None
            
            url = page.url
            title = page.title()
            software = detect_tax_software_type(url, title)
            
            # Get visible text - filter for form/field content
            visible_text = ""
            try:
                visible_text = page.evaluate("""
                    () => {
                        // Get text near form fields (labels + values)
                        let results = [];
                        
                        // Find all labels
                        const labels = document.querySelectorAll('label, .label, [class*='label'], [class*='field'], [class*='entry'], [id*='lbl']');
                        labels.forEach(label => {
                            const text = label.textContent.trim();
                            const rect = label.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0 && text.length > 0 && text.length < 100) {
                                // Find nearby input
                                const forAttr = label.getAttribute('for');
                                let value = '';
                                if (forAttr) {
                                    const input = document.getElementById(forAttr);
                                    if (input) value = input.value || input.textContent || '';
                                } else {
                                    const input = label.querySelector('input, select, textarea, span.value, span.data');
                                    if (input) value = input.value || input.textContent || '';
                                }
                                if (value) {
                                    results.push(text + ': ' + value);
                                }
                            }
                        });
                        
                        // Find tables with financial data (common in tax software)
                        const tables = document.querySelectorAll('table');
                        tables.forEach(table => {
                            const rows = table.querySelectorAll('tr');
                            rows.forEach(row => {
                                const cells = row.querySelectorAll('td, th');
                                if (cells.length >= 2) {
                                    const cellText = Array.from(cells).map(c => c.textContent.trim()).join(' | ');
                                    if (cellText.length > 5 && cellText.length < 200) {
                                        results.push(cellText);
                                    }
                                }
                            });
                        });
                        
                        // Get headers/section titles
                        const headers = document.querySelectorAll('h1, h2, h3, h4, .section-title, .panel-title, [class*='header']');
                        headers.forEach(h => {
                            const text = h.textContent.trim();
                            if (text.length > 2 && text.length < 100) {
                                results.push('== ' + text + ' ==');
                            }
                        });
                        
                        return results.join('\\n');
                    }
                """) or ""
            except Exception as e:
                logger.debug(f"Could not get visible text: {e}")
                pass
            
            # Get form values as dict - improved
            form_values = {}
            checkboxes = {}
            try:
                form_data = page.evaluate("""
                    () => {
                        const data = {};
                        const checkboxes = {};
                        // Get all inputs with their visible labels
                        const inputs = document.querySelectorAll('input:not([type=hidden]), select, textarea');
                        inputs.forEach(input => {
                            if (input.type === 'hidden') return;
                            
                            // Try to find associated label
                            let label = '';
                            if (input.id) {
                                const labelEl = document.querySelector(`label[for="${input.id}"]`);
                                if (labelEl) label = labelEl.textContent.trim();
                            }
                            if (!label) {
                                const parent = input.closest('div, td, th, label');
                                if (parent) {
                                    const prev = parent.querySelector('label, span, div');
                                    if (prev) label = prev.textContent.trim();
                                }
                            }
                            if (!label) {
                                label = input.name || input.id || 'unnamed';
                            }
                            
                            // Handle checkboxes specially
                            if (input.type === 'checkbox') {
                                // Get the full label text
                                let fullLabel = label;
                                const parent = input.closest('div, td, label');
                                if (parent) {
                                    const textEl = parent.textContent ? parent.textContent.trim() : label;
                                    if (textEl && textEl.length > label.length) {
                                        fullLabel = textEl.substring(0, 100);
                                    }
                                }
                                checkboxes[fullLabel] = {
                                    checked: input.checked,
                                    value: input.value
                                };
                            }
                            
                            if (input.value && input.value.length > 0 && input.value.length < 50) {
                                data[label] = {
                                    value: input.value,
                                    type: input.type
                                };
                            }
                        });
                        return { data, checkboxes };
                    }
                """)
                
                if form_data:
                    # Handle both old format (dict) and new format ({data, checkboxes})
                    if isinstance(form_data, dict):
                        if 'data' in form_data and 'checkboxes' in form_data:
                            # New format
                            for name, info in form_data['data'].items():
                                if info.get('value'):
                                    form_values[name] = {
                                        'value': str(info.get('value', '')),
                                        'label': name
                                    }
                            for cb_label, cb_info in form_data.get('checkboxes', {}).items():
                                checkboxes[cb_label] = cb_info
                        else:
                            # Old format (just data)
                            for name, info in form_data.items():
                                if info.get('value'):
                                    form_values[name] = {
                                        'value': str(info.get('value', '')),
                                        'label': name
                                    }
            except Exception as e:
                pass
            
            return {
                'url': url,
                'title': title,
                'software': software,
                'text': visible_text,
                'form_values': form_values,
                'checkboxes': checkboxes,
                'hash': hash((url, title, visible_text[:1000])),
            }
            
        except Exception as e:
            logger.debug(f"Error getting tax page snapshot: {e}")
            return None
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


_chrome_reader: Optional[ChromeReader] = None


def get_chrome_reader() -> Optional[ChromeReader]:
    """Get a singleton Chrome reader instance."""
    global _chrome_reader
    
    if _chrome_reader is None:
        try:
            _chrome_reader = ChromeReader()
            if not _chrome_reader.connect():
                _chrome_reader = None
        except Exception as e:
            logger.debug(f"Could not create Chrome reader: {e}")
            _chrome_reader = None
    
    return _chrome_reader


def reset_chrome_reader() -> None:
    """Reset the Chrome reader singleton."""
    global _chrome_reader
    
    if _chrome_reader:
        _chrome_reader.disconnect()
        _chrome_reader = None


def read_tax_software_if_available() -> Optional[str]:
    """Convenience function to read tax software content if available."""
    try:
        reader = get_chrome_reader()
        if reader:
            return reader.read_tax_software_content()
    except Exception as e:
        logger.debug(f"Could not read tax software: {e}")
    
    return None
