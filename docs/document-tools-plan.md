# Document read/write tools — implementation plan

> Status: **Planned** (not yet implemented)
> Decided: 2026-05-06

## Summary

Add first-class document read and write tools for **.docx**, **.pptx**, and **.pdf** to the
standard toolset (available to all users including gateway bots).

### Formats supported (v1)

| Format | Read | Write | Library |
|--------|------|-------|---------|
| `.docx` (Word) | ✓ | ✓ (markdown → docx) | `python-docx` (already bundled) |
| `.pptx` (PowerPoint) | ✓ | ✓ (slides content → pptx) | `python-pptx` (new dep) |
| `.pdf` | ✓ (pypdf) | ✓ (markdown → pdf with basic layout) | `pypdf` (already bundled) + `fpdf2` + `markdown` (new deps) |

### Excluded (v1)

- `.doc` / `.ppt` (legacy OLE binary) — `python-docx`/`python-pptx` do not support
  them; would require LibreOffice headless (~500 MB dep)

## Changes

### 1. New dependency (`python/requirements-desktop.txt`)

```
python-pptx>=0.6.23,<1
fpdf2>=2.7.0,<3
markdown>=3.5,<4
```

### 2. New tool file (`hermes_core/tools/document_tools.py`)

Six tools registered via `registry.register()`:

| Tool name | Description | Handler |
|-----------|-------------|---------|
| `docx_read` | Extract paragraphs, headers, tables from `.docx` | `python-docx` `Document` |
| `docx_write` | Create `.docx` from markdown/text, auto heading styles | `python-docx` `Document` |
| `pptx_read` | Extract text from each slide + speaker notes | `python-pptx` `Presentation` |
| `pptx_write` | Create `.pptx` from structured slide content | `python-pptx` `Presentation` |
| `pdf_read` | Extract text with page-range support | `pypdf` `PdfReader` |
| `pdf_write` | Convert markdown to formatted PDF | `markdown` → `fpdf2` |

### 3. Binary extension blocklist (`hermes_core/tools/binary_extensions.py`)

Remove `.docx` and `.pptx` from `BINARY_EXTENSIONS` (line 20).
Keep `.doc`, `.ppt` (still unsupported legacy formats).
`.pdf` is already excluded (line 19 comment).

### 4. New toolset (`hermes_core/toolsets.py`)

```python
"documents": {
    "description": "Document read/write: docx, pptx, pdf",
    "tools": ["docx_read", "docx_write", "pptx_read", "pptx_write", "pdf_read", "pdf_write"],
    "includes": [],
},
```

### 5. Tool policy (`python/src/tool_policy.py`)

Add `"documents"` to both `KEEP_LIST` and `GATEWAY_KEEP_LIST` so it is
available to all users (standard, power-user, and gateway bots).

### 6. Tests (`python/tests/test_policy_contract.py`)

Update standard-mode tool count assertion from 8 → 9.

## Rationale

- Upstream Hermes has no native document read/write tools — `file` toolset only
  handles plain text and blocks binary extensions including `.docx`/`.pptx`.
- `python-docx` and `pypdf` are already bundled for L1 helpers (`pdf_digest`,
  `excel_to_word`); `python-pptx` and `fpdf2` extend the document coverage.
- Adding to `KEEP_LIST` means all users get the tools without requiring power-user
  toggle, consistent with "browser" being in the standard keep-list.
