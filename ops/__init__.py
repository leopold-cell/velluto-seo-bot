"""
Shared operational helpers, usable by any project in this repo.

Extracted from the Velluto SEO pipeline so a second project (Hermes) can reuse
the same guarded mechanisms without importing Velluto-specific modules. The
original call sites keep working: review/_common.py re-exports from here, the
same way review/whatsapp.py shims the removed WhatsApp sender.

Nothing in here knows about Velluto, Shopify, or any single brand. Anything
brand-specific stays in its own project package.
"""
