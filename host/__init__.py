"""Mac host runtime for LSC-1.

The host owns the program, the VM memory image, the write-once bitmap, the
pointer map, deferred-equality state, witnesses and every service the ASIC
delegates upward.  LSC-1 sees one self-contained instruction transaction at a
time and answers with transition effects only.
"""
