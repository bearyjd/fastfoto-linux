"""Shared builders for XMP packet tests."""

NAMESPACES = (
    b'xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    b'xmlns:tiff="http://ns.adobe.com/tiff/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


def doc(body: bytes, attributes: bytes = b"", *, head: bytes = b"") -> bytes:
    """A packet: ``head`` (declaration, DTD), then one description with ``body`` inside."""
    return (
        head + b"<x:xmpmeta " + NAMESPACES + b"><rdf:RDF><rdf:Description " + attributes + b">"
        b"" + body + b"</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
