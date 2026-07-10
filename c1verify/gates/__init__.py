"""c1verify.gates — one fail-closed reverifier per certificate gate.

Each module here reduces a gate to a total pure function over the SEALED bundle payload, importing
only c1verify._decision + c1verify.jcs (+ stdlib) — never c1verify.core and never lakatos/server.
A gate reverifier PROVES ACCEPT from the bytes or REJECTs; it never trusts a pointer.
"""
