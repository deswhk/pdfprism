"""Services layer: pure-logic operations on documents.

Services take an adapter and inputs, return outputs, and raise typed
exceptions. They never import Qt and never know which engine the adapter
wraps. They are the home for cross-page, cross-document, and multi-step
operations that would otherwise leak into the UI.
"""
