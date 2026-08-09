"""Compatibility shim — daemon management moved to clay.daemon.

The Qt UI now connects to clayd as a client via WorkflowManager.
"""
from ..daemon.client import DaemonClient, EventSubscriber
