"""clay.daemon — system-level workflow process manager.

The daemon (`clayd`) runs as a persistent background process, managing
workflow subprocesses independently of any UI.  Clients (CLI, Qt UI, web)
connect via a unix domain socket at ~/.clay/clayd.sock.

Architecture:
    clayd (server.py)
      ├── WorkflowProc  ← real subprocess per workflow
      │     ├── stdout/stderr capture
      │     ├── stdin relay
      │     └── event socket bridge
      └── unix socket API  ← JSON-line protocol
            ├── CLI client
            ├── Qt UI client
            └── any other client
"""
