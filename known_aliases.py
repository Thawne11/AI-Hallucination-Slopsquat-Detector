"""
Import name -> PyPI distribution name mappings.

A Python module's importable name is not always the name you install. This
module is the single place those differences are recorded, so the mapping
can grow without touching scanner logic.

The first three entries were found empirically rather than copied from a
list: each was flagged as "hallucinated" by this project's own exists-check
during a real run, and manual verification showed a real, correctly-used
package under a different distribution name. See README "Import ->
Distribution resolution" for that discovery story.

This mapping is inherently incomplete. That is deliberate and safe: an
import missing from it resolves as *unresolved*, never as nonexistent (see
import_resolver.py). Adding an entry improves precision; omitting one
cannot manufacture a false accusation.
"""

# import name -> the distribution you would actually `pip install`
KNOWN_PYTHON_ALIASES = {
    # Found by this project, during real scans
    "jwt": "PyJWT",
    "paho": "paho-mqtt",
    "saml2": "pysaml2",

    # Commonly-hit mismatches
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "Crypto": "pycryptodome",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dns": "dnspython",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "fitz": "PyMuPDF",
    "git": "GitPython",
    "magic": "python-magic",
    "MySQLdb": "mysqlclient",
    "nacl": "PyNaCl",
    "OpenSSL": "pyOpenSSL",
    "PIL": "Pillow",
    "pkg_resources": "setuptools",
    "pptx": "python-pptx",
    "serial": "pyserial",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "usb": "pyusb",
    "win32com": "pywin32",
    "yaml": "PyYAML",
    "zmq": "pyzmq",

    # Names that differ only by case or are simply themselves. Listing them
    # costs nothing and short-circuits a network round-trip.
    "django": "Django",
    "flask": "Flask",
    "requests": "requests",
}

# Import names legitimately provided by more than one distribution. These
# must never resolve to a single answer: picking one would mean making a
# security judgement about a package the developer may not even be using.
AMBIGUOUS_PYTHON_IMPORTS = {
    # Both distributions publish a top-level `slugify` module, and which one
    # is installed changes the API you get.
    "slugify": ["python-slugify", "awesome-slugify"],
}
